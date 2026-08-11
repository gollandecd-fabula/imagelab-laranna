from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.entry import app
from app.main import store
from app.models import AssetRecord
from app.services.project_store import ProjectStore

client = TestClient(app)


def _project_id(prefix: str = "M2A") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGBA", (64, 32), (20, 90, 180, 255)).save(stream, format="PNG", dpi=(300, 300))
    return stream.getvalue()


def _cleanup(project_id: str) -> None:
    try:
        client.delete(f"/api/projects/{project_id}/assets")
    except Exception:
        pass
    path = settings.project_dir / f"{project_id}.json"
    path.unlink(missing_ok=True)
    path.with_suffix(".lock").unlink(missing_ok=True)


def test_workspace_round_trip_masks_settings_size_and_reports() -> None:
    project_id = _project_id()
    try:
        created = client.post(f"/api/projects/{project_id}", json={"title": "M2A workspace"})
        assert created.status_code == 200, created.text
        upload = client.post(
            f"/api/projects/{project_id}/upload",
            files=[("files", ("m2a.png", _png(), "image/png"))],
        )
        assert upload.status_code == 200, upload.text
        asset_id = upload.json()["uploaded"][0]["id"]

        payloads = {
            "settings": {"default_ppi": 300, "privacy": {"local_only": True}, "requested_model_packs": ["restore"]},
            "size_controller": {"linked": True, "width_mm": "100", "height_mm": "50", "ppi": 300, "canvas": {"top_mm": 1}},
            "masks": {asset_id: {"edits": [{"tool": "add", "points": [[0.1, 0.2], [0.3, 0.4]]}], "inverted": False}},
            "batch_reports": [{"id": "batch-1", "status": "CANCELLED", "completed": 1}],
        }
        for section, value in payloads.items():
            response = client.put(f"/api/m2a/projects/{project_id}/workspace/{section}", json={"value": value})
            assert response.status_code == 200, response.text
            assert response.json()["project"]["workspace"][section] == value

        current = client.get(f"/api/m2a/projects/{project_id}/workspace")
        assert current.status_code == 200
        assert current.json()["workspace"] == payloads
    finally:
        _cleanup(project_id)


def test_workspace_and_presets_reject_secrets_unbounded_data_and_unknown_masks() -> None:
    project_id = _project_id("M2A-SAFE")
    try:
        assert client.post(f"/api/projects/{project_id}", json={"title": "safe"}).status_code == 200
        secret = client.put(
            f"/api/m2a/projects/{project_id}/workspace/settings",
            json={"value": {"api_key": "must-not-be-stored"}},
        )
        assert secret.status_code == 422
        assert "Секретные данные" in secret.text

        oversized = client.put(
            f"/api/m2a/projects/{project_id}/workspace/settings",
            json={"value": {"note": "x" * 5000}},
        )
        assert oversized.status_code == 422

        unknown_mask = client.put(
            f"/api/m2a/projects/{project_id}/workspace/masks",
            json={"value": {"aaaaaaaa": {"edits": []}}},
        )
        assert unknown_mask.status_code == 422

        preset = client.put(
            f"/api/m2a/projects/{project_id}/presets",
            json={"name": "bad", "module": "geometry", "parameters": {"access_token": "no"}},
        )
        assert preset.status_code == 422
    finally:
        _cleanup(project_id)


def test_diagnostics_report_is_privacy_bounded_and_downloadable() -> None:
    response = client.get("/api/m2a/diagnostics")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"] == "M2A_UI_DIAGNOSTICS"
    assert payload["release_status"] == "RELEASE_BLOCKED"
    assert payload["privacy"] == {
        "image_content_included": False,
        "secrets_included": False,
        "absolute_paths_included": False,
        "cloud_upload_default": False,
    }
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("api_key", "access_token", "password", "data:image", str(Path.home()).lower()):
        assert forbidden not in serialized

    download = client.get("/api/m2a/diagnostics-report")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.json() == payload


def test_project_typed_collections_survive_save_reload() -> None:
    project_id = _project_id("M2A-COLLECTIONS")
    try:
        created = client.post(f"/api/projects/{project_id}", json={"title": "typed collections"})
        assert created.status_code == 200, created.text
        upload = client.post(
            f"/api/projects/{project_id}/upload",
            files=[("files", ("source.png", _png(), "image/png"))],
        )
        assert upload.status_code == 200, upload.text
        source = AssetRecord.model_validate(upload.json()["uploaded"][0])

        def derived(asset_id: str, operation: str, digest: str) -> AssetRecord:
            return source.model_copy(
                update={
                    "id": asset_id,
                    "original_name": f"{operation}.png",
                    "stored_name": f"{asset_id}.png",
                    "preview_name": f"{asset_id}.png",
                    "sha256": digest * 64,
                    "source_asset_id": source.id,
                    "operation": operation,
                    "parameters": {"input_asset_id": source.id},
                }
            )

        normal = derived("dddddddd", "enhance", "d")
        master = derived("mmmmmmmm", "master_dtf", "a")
        export = derived("eeeeeeee", "export", "e")
        store.commit_derived_assets(project_id, source.id, [normal, master, export], active_asset_id=export.id)

        mask = {source.id: {"edits": [{"tool": "add", "points": [[0.1, 0.2]]}], "inverted": False}}
        assert client.put(
            f"/api/m2a/projects/{project_id}/workspace/masks", json={"value": mask}
        ).status_code == 200
        qa_reports = [{"id": "qa-1", "status": "PASS", "asset_id": export.id}]
        assert client.put(
            f"/api/m2a/projects/{project_id}/workspace/qa_reports", json={"value": qa_reports}
        ).status_code == 200
        assert client.put(
            f"/api/m2a/projects/{project_id}/presets",
            json={"name": "print", "module": "geometry", "parameters": {"ppi": 300}},
        ).status_code == 200

        reopened_store = ProjectStore(settings.project_dir)
        reloaded = reopened_store.get(project_id)
        assert project_id in {project.id for project in reopened_store.list_projects()}
        assert reloaded.collections.sources == [source.id]
        assert reloaded.collections.derivatives == [normal.id, master.id, export.id]
        assert reloaded.collections.masters == [master.id]
        assert reloaded.collections.exports == [export.id]
        assert reloaded.collections.masks == mask
        assert reloaded.collections.presets == {
            "print": {"module": "geometry", "parameters": {"ppi": 300}}
        }
        assert reloaded.collections.qa_reports == qa_reports

        persisted = json.loads((settings.project_dir / f"{project_id}.json").read_text("utf-8"))
        assert persisted["collections"] == reloaded.collections.model_dump()
    finally:
        _cleanup(project_id)
