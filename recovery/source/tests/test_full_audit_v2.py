from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import settings
from app.models import AssetRecord, sanitize_original_filename
from app.services.project_store import ProjectStore
from app.services.image_processing import ProcessingError


client = TestClient(main_module.app)
ROOT = Path(__file__).resolve().parents[1]


def _asset(asset_id: str, source_asset_id: str | None, operation: str) -> AssetRecord:
    now = datetime.now(timezone.utc).isoformat()
    return AssetRecord(
        id=asset_id,
        original_name=f"{asset_id}.png",
        stored_name=f"{asset_id}.png",
        preview_name=f"{asset_id}.preview.png",
        size_bytes=4,
        sha256=asset_id[0] * 64,
        mime_type="image/png",
        format="PNG",
        width_px=1,
        height_px=1,
        ppi_x=300,
        ppi_y=300,
        ppi_origin="test",
        created_at=now,
        preview_url=f"/api/assets/{asset_id}/preview",
        download_url=f"/api/assets/{asset_id}/file",
        source_asset_id=source_asset_id,
        operation=operation,
        parameters={"input_asset_id": source_asset_id},
    )


def test_original_filename_is_cross_platform_and_header_safe() -> None:
    assert sanitize_original_filename(r"C:\\Users\\Dmitry\\print.png") == "print.png"
    assert sanitize_original_filename("../../print.png") == "print.png"
    with pytest.raises(ValueError, match="управляющие"):
        sanitize_original_filename("print\r\nX-Evil: 1.png")


def test_missing_project_get_is_404_and_does_not_create_file() -> None:
    project_id = "AUDIT-MISSING-PROJECT"
    path = settings.project_dir / f"{project_id}.json"
    path.unlink(missing_ok=True)
    response = client.get(f"/api/projects/{project_id}")
    assert response.status_code == 404
    assert not path.exists()


def test_cleanup_pipeline_failure_is_atomic_and_removes_staged_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProjectStore(tmp_path / "projects")
    source = _asset("11111111", None, "upload")
    source.source_asset_id = None
    source.operation = None
    source.parameters = {}
    store.add_assets("ATOMIC-CLEANUP", [source])
    monkeypatch.setattr(main_module, "store", store)
    runtime_settings = SimpleNamespace(
        **{
            **settings.__dict__,
            "upload_dir": tmp_path / "uploads",
            "preview_dir": tmp_path / "previews",
        }
    )
    runtime_settings.upload_dir.mkdir()
    runtime_settings.preview_dir.mkdir()
    monkeypatch.setattr(main_module, "settings", runtime_settings)

    first = _asset("22222222", source.id, "background")

    calls = 0

    def fake_processing(current, operation, parameters):
        nonlocal calls
        calls += 1
        if calls == 1:
            (runtime_settings.upload_dir / first.stored_name).write_bytes(b"data")
            (runtime_settings.preview_dir / first.preview_name).write_bytes(b"data")
            return first, [first], {"passed": True, "attempt_count": 1}
        raise ProcessingError("forced second-stage failure")

    monkeypatch.setattr(main_module, "run_processing_with_repair", fake_processing)
    response = client.post(
        "/api/projects/ATOMIC-CLEANUP/cleanup-pipeline",
        json={
            "asset_id": source.id,
            "remove_background": True,
            "background_parameters": {},
            "run_cleanup": True,
            "cleanup_parameters": {},
        },
    )
    assert response.status_code == 422
    current = store.get("ATOMIC-CLEANUP")
    assert [asset.id for asset in current.assets] == [source.id]
    assert current.workspace["active_asset_id"] == source.id
    assert not (runtime_settings.upload_dir / first.stored_name).exists()
    assert not (runtime_settings.preview_dir / first.preview_name).exists()


def test_cleanup_pipeline_success_commits_complete_lineage_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProjectStore(tmp_path / "projects")
    source = _asset("33333333", None, "upload")
    source.source_asset_id = None
    source.operation = None
    source.parameters = {}
    store.add_assets("ATOMIC-CLEANUP-OK", [source])
    monkeypatch.setattr(main_module, "store", store)
    runtime_settings = SimpleNamespace(
        **{
            **settings.__dict__,
            "upload_dir": tmp_path / "uploads",
            "preview_dir": tmp_path / "previews",
        }
    )
    runtime_settings.upload_dir.mkdir()
    runtime_settings.preview_dir.mkdir()
    monkeypatch.setattr(main_module, "settings", runtime_settings)
    first = _asset("44444444", source.id, "background")
    second = _asset("55555555", first.id, "cleanup")
    generated = iter([first, second])

    def fake_processing(current, operation, parameters):
        item = next(generated)
        assert item.source_asset_id == current.id
        (runtime_settings.upload_dir / item.stored_name).write_bytes(b"data")
        (runtime_settings.preview_dir / item.preview_name).write_bytes(b"data")
        return item, [item], {"passed": True, "attempt_count": 1}

    monkeypatch.setattr(main_module, "run_processing_with_repair", fake_processing)
    monkeypatch.setattr(
        main_module,
        "record_continual_learning",
        lambda attempts, operation: {"status": "recorded", "module": operation},
    )
    response = client.post(
        "/api/projects/ATOMIC-CLEANUP-OK/cleanup-pipeline",
        json={
            "asset_id": source.id,
            "remove_background": True,
            "background_parameters": {},
            "run_cleanup": True,
            "cleanup_parameters": {},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["atomic"] is True
    assert payload["source_asset_id"] == source.id
    assert payload["result"]["id"] == second.id
    current = store.get("ATOMIC-CLEANUP-OK")
    assert [asset.id for asset in current.assets] == [source.id, first.id, second.id]
    assert current.workspace["active_asset_id"] == second.id


def test_ui_resets_manual_selection_on_asset_change_and_uses_atomic_cleanup() -> None:
    js = (ROOT / "app" / "static" / "app.js").read_text("utf-8")
    assert "selectionAssetId" in js
    assert "if (state.selectionAssetId !== asset.id) resetSelectionState(asset.id)" in js
    assert "/cleanup-pipeline" in js
    assert "response.atomic !== true" in js
    assert "Сервер не подтвердил атомарную очистку" in js


def test_ui_static_identity_security_and_destructive_action_guards() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text("utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text("utf-8")
    assert "1.4.5-recovery" not in html
    assert "1.4.9-recovery-candidate" in html
    assert 'role="status" aria-live="polite"' in html
    assert "confirm(`Обучить кандидат модели" in js
    assert "confirm(`Откатить активную AI-модель" in js
    assert "effectiveAutoRepair" in js
    assert "Быстрый режим: повторные автоисправления отключены" in js


def test_main_page_has_strict_browser_security_headers() -> None:
    response = client.get("/")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["permissions-policy"].startswith("camera=()")
