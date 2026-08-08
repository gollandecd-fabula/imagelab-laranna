from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import app.ai.registry as registry_module
import app.main as main_module
from app.ai.feedback import AIFeedbackError, AIFeedbackStore
from app.ai.registry import AIModelError, AIModelRegistry
from app.config import settings
from app.models import AssetRecord, ProjectRecord
from app.services.export_service import ExportError, build_project_bundle, export_asset
from app.services.file_inspector import UploadValidationError, inspect_and_sanitize_svg
from app.services.image_processing import ProcessingError, _halftone, _perspective, _vectorize
from app.services.project_store import ProjectStore
from app.services.qa_service import build_qa_response

client = TestClient(main_module.app)
PROJECT = "REDTEAM-ADV"


def _png(size: tuple[int, int] = (96, 80), alpha: bool = True) -> bytes:
    mode = "RGBA" if alpha else "RGB"
    background = (245, 245, 245, 0) if alpha else (245, 245, 245)
    image = Image.new(mode, size, background)
    draw = ImageDraw.Draw(image)
    fill = (210, 45, 25, 255) if alpha else (210, 45, 25)
    draw.rectangle((15, 12, size[0] - 15, size[1] - 12), fill=fill)
    buffer = io.BytesIO(); image.save(buffer, "PNG", dpi=(300, 300)); return buffer.getvalue()


def _cleanup() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    (settings.project_dir / f"{PROJECT}.json").unlink(missing_ok=True)


def _upload(alpha: bool = True) -> dict:
    _cleanup()
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("sample.png", _png(alpha=alpha), "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def test_degenerate_perspective_is_rejected() -> None:
    image = Image.new("RGBA", (100, 100), (1, 2, 3, 255))
    with pytest.raises(ProcessingError):
        _perspective(image, [[0, 0], [100, 100], [100, 0], [0, 100]])
    with pytest.raises(ProcessingError):
        _perspective(image, [[0, 0], [0, 0], [100, 100], [0, 100]])


def test_halftone_cell_dos_is_rejected() -> None:
    image = Image.new("RGBA", (2000, 2000), (20, 30, 40, 255))
    with pytest.raises(ProcessingError, match="чрезмерное количество"):
        _halftone(image, 300, {"size_mm": 0.05, "lpi": 300, "density": 80, "mode": "mono", "raster": "dot"})


def test_vectorization_limits_and_transparency() -> None:
    too_large = Image.new("RGBA", (2001, 2000), (1, 2, 3, 255))
    large_svg = _vectorize(too_large, {"mode": "color", "colors": 2, "simplify": 2, "min_area": 8})
    assert 'width="2001px"' in large_svg
    assert 'height="2000px"' in large_svg
    assert 'transform="scale(' in large_svg
    image = Image.open(io.BytesIO(_png())).convert("RGBA")
    svg = _vectorize(image, {"mode": "color", "colors": 4, "simplify": 1, "min_area": 2})
    assert "<path" in svg
    assert "fill-rule=\"evenodd\"" in svg
    assert len(svg.encode("utf-8")) < 20 * 1024 * 1024


@pytest.mark.parametrize("payload", [
    b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://evil.test/x.css)</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AAAA"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><a href="https://evil.test"><path d="M0 0L1 1"/></a></svg>',
])
def test_svg_active_content_is_rejected(payload: bytes) -> None:
    with pytest.raises(UploadValidationError):
        inspect_and_sanitize_svg(payload)


def test_qa_detects_file_tampering() -> None:
    asset_json = _upload()
    project = main_module.store.get_or_create(PROJECT)
    asset = next(item for item in project.assets if item.id == asset_json["id"])
    path = settings.upload_dir / asset.stored_name
    path.write_bytes(path.read_bytes() + b"tamper")
    qa = build_qa_response(project, asset)
    by_code = {item.code: item for item in qa.checks}
    assert by_code["sha256"].passed is False
    assert by_code["file_size"].passed is False
    _cleanup()


def test_bundle_is_deterministic() -> None:
    _upload()
    project = main_module.store.get_or_create(PROJECT)
    first, _ = build_project_bundle(project)
    second, _ = build_project_bundle(project)
    assert first == second
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
    _cleanup()


def test_dtf_export_requires_transparency() -> None:
    asset_json = _upload(alpha=False)
    project = main_module.store.get_or_create(PROJECT)
    asset = next(item for item in project.assets if item.id == asset_json["id"])
    with pytest.raises(ExportError, match="прозрачного фона"):
        export_asset(asset, "PNG_DTF", {})
    _cleanup()


def test_upload_rolls_back_files_when_ai_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _cleanup()
    before_uploads = {p.name for p in settings.upload_dir.iterdir() if p.is_file()}
    before_previews = {p.name for p in settings.preview_dir.iterdir() if p.is_file()}

    class BrokenEngine:
        def analyze(self, *_args, **_kwargs):
            raise AIModelError("forced failure")

    monkeypatch.setattr(main_module, "get_ai_engine", lambda: BrokenEngine())
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("sample.png", _png(), "image/png"))])
    assert response.status_code == 422
    assert {p.name for p in settings.upload_dir.iterdir() if p.is_file()} == before_uploads
    assert {p.name for p in settings.preview_dir.iterdir() if p.is_file()} == before_previews
    _cleanup()


def test_process_rolls_back_result_when_project_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    asset = _upload()
    before_uploads = {p.name for p in settings.upload_dir.iterdir() if p.is_file()}
    original = main_module.store.commit_derived_assets

    def fail_add(project_id, source_asset_id, assets, *, active_asset_id=None):
        if assets and assets[0].operation:
            raise ValueError("forced store failure")
        return original(project_id, source_asset_id, assets, active_asset_id=active_asset_id)

    monkeypatch.setattr(main_module.store, "commit_derived_assets", fail_add)
    response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": asset["id"], "operation": "color", "parameters": {"hue": 10}})
    assert response.status_code == 400
    assert {p.name for p in settings.upload_dir.iterdir() if p.is_file()} == before_uploads
    _cleanup()


def test_feedback_nan_and_forged_api_vector_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = replace(settings, ai_feedback_dir=tmp_path / "feedback", ai_promoted_model_dir=tmp_path / "models")
    import app.ai.feedback as feedback_module
    monkeypatch.setattr(feedback_module, "settings", fake_settings)
    store = AIFeedbackStore()
    with pytest.raises(AIFeedbackError):
        store.add("upload", {"accepted": True, "features": [1.0, float("nan")]})

    asset = _upload()
    response = client.post("/api/ai/feedback", json={"module": "upload", "asset_id": asset["id"], "accepted": True, "features": [0.0] * 20})
    assert response.status_code == 422
    _cleanup()


def test_manifest_tampering_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_dir = tmp_path / "models"
    shutil.copytree(settings.ai_model_dir, model_dir)
    manifest = json.loads((model_dir / "manifest.json").read_text("utf-8"))
    manifest["models"][0]["version"] = "tampered"
    (model_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(registry_module, "settings", replace(settings, ai_model_dir=model_dir))
    with pytest.raises(AIModelError, match="Манифест|manifest"):
        AIModelRegistry()


def test_corrupt_neighbor_project_does_not_hide_valid_asset(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    now = "2026-07-23T00:00:00+00:00"
    asset = AssetRecord(
        id="a" * 32, original_name="x.png", stored_name="a" * 32 + ".png", preview_name="a" * 32 + ".preview.png",
        size_bytes=1, sha256="0" * 64, mime_type="image/png", format="PNG", width_px=1, height_px=1,
        ppi_x=300, ppi_y=300, ppi_origin="embedded", print_width_mm=.08, print_height_mm=.08,
        color_mode="RGBA", color_profile="none", has_alpha=True, created_at=now, preview_url="/x",
    )
    project = ProjectRecord(id="VALID-01", title="valid", created_at=now, updated_at=now, assets=[asset])
    store.save(project)
    (tmp_path / "AAA-CORRUPT.json").write_text("{bad", "utf-8")
    found = store.find_asset(asset.id)
    assert found and found[1].id == asset.id


def test_request_size_limit_and_security_headers() -> None:
    response = client.get("/", headers={"content-length": str(5 * 1024 * 1024)})
    assert response.status_code == 413
    normal = client.get("/")
    assert normal.headers["x-content-type-options"] == "nosniff"
    assert normal.headers["x-frame-options"] == "DENY"
    assert normal.headers["cache-control"] == "no-store"


def test_frontend_has_real_report_tab_and_keyboard_upload() -> None:
    html = (settings.static_dir / "index.html").read_text("utf-8")
    js = (settings.static_dir / "app.js").read_text("utf-8")
    assert 'data-info-tab="report"' in html
    assert 'id="reportContent"' in html
    assert "event.key === 'Enter'" in js and "event.key === ' '" in js
    assert 'title="Меню"' not in html
    assert "activateInfoTab('report')" in js


def test_localhost_host_and_cross_site_guards() -> None:
    bad_host = client.get("/api/health", headers={"host": "evil.test"})
    assert bad_host.status_code == 421
    cross = client.post("/api/ai/train", json={"module": "upload"}, headers={"origin": "https://evil.test", "sec-fetch-site": "cross-site"})
    assert cross.status_code == 403
    same = client.get("/api/health", headers={"host": "127.0.0.1:8765"})
    assert same.status_code == 200


def test_manual_ai_analysis_is_persisted_and_feedback_can_use_it() -> None:
    asset = _upload()
    analysis = client.post(f"/api/assets/{asset['id']}/ai/analyze")
    assert analysis.status_code == 200, analysis.text
    payload = analysis.json()
    project = client.get(f"/api/projects/{PROJECT}").json()
    stored = next(item for item in project["assets"] if item["id"] == asset["id"])
    assert stored["ai"]["manual_analysis"]["input_sha256"] == payload["input_sha256"]
    response = client.post("/api/ai/feedback", json={
        "module": "upload", "asset_id": asset["id"], "accepted": True,
        "features": payload["details"]["features"], "note": "red-team persistence test",
    })
    assert response.status_code == 200, response.text
    _cleanup()


def test_high_probability_subject_touching_frame_is_not_forced_to_background(monkeypatch: pytest.MonkeyPatch) -> None:
    image = Image.new("RGBA", (120, 100), (30, 40, 50, 255))
    from app.ai.runtime import get_ai_engine
    engine = get_ai_engine()
    probability = np.full((100, 120), 0.95, dtype=np.float32)
    alpha = np.full((100, 120), 255, dtype=np.uint8)
    rgb = np.full((100, 120, 3), (30, 40, 50), dtype=np.uint8)
    monkeypatch.setattr(engine, "_probability_map", lambda *_args, **_kwargs: (probability, alpha, rgb, [120, 100]))
    mask, _ = engine.segment_subject(image, threshold=0.42, feather=0, module="frame_test")
    assert float((mask > 16).mean()) > 0.98


def test_registry_rejects_nonpositive_scale_and_payload_is_copy() -> None:
    with pytest.raises(AIModelError, match="Scale"):
        AIModelRegistry._validate_payload("bad", {
            "kind": "binary_logistic", "mean": [0.0], "scale": [0.0], "coef": [1.0], "intercept": 0.0,
        })
    registry = AIModelRegistry()
    first = registry.payload("pixel_subject")
    first["kind"] = "tampered-in-memory"
    assert registry.payload("pixel_subject")["kind"] != "tampered-in-memory"


def test_feedback_deduplicates_and_rejects_conflicting_training_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = replace(settings, ai_feedback_dir=tmp_path / "feedback", ai_promoted_model_dir=tmp_path / "models")
    import app.ai.feedback as feedback_module
    monkeypatch.setattr(feedback_module, "settings", fake_settings)
    store = AIFeedbackStore()
    payload = {"accepted": True, "features": [1.0, 2.0], "asset_id": "a" * 32}
    store.add("upload", payload)
    with pytest.raises(AIFeedbackError, match="повтор"):
        store.add("upload", payload)

    path = fake_settings.ai_feedback_dir / "conflict.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(8):
        rows.append({"accepted": index % 2 == 0, "features": [float(index), 1.0], "asset_id": str(index)})
    rows.append({"accepted": False, "features": [0.0, 1.0], "asset_id": "conflict"})
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")
    with pytest.raises(AIFeedbackError, match="противоречивые"):
        store.train("conflict")


def test_audit_sanitizes_nonfinite_values_and_detects_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ai.audit as audit_module
    fake_settings = replace(settings, ai_audit_dir=tmp_path / "audit")
    monkeypatch.setattr(audit_module, "settings", fake_settings)
    store = audit_module.AIAuditStore()
    first = store.append({"operation": "probe", "value": float("nan"), "features": [1, 2, 3]})
    second = store.append({"operation": "probe2"})
    assert first["value"] == "[non-finite]"
    assert first["feature_count"] == 3
    verification = store.verify_all()[0]
    assert verification["valid"] is True and verification["checked"] == 2

    path = next(fake_settings.ai_audit_dir.glob("*.jsonl"))
    text = path.read_text("utf-8").replace("probe2", "tampered", 1)
    path.write_text(text, "utf-8")
    assert store.verify_all()[0]["valid"] is False


def test_unsupported_parser_magic_is_rejected_before_pillow() -> None:
    from app.services.file_inspector import inspect_upload
    for payload in (
        b"%!PS-Adobe-3.0 EPSF-3.0\n%%BeginBinary: -5\n",
        b"\x00\x00\x00\x0cjP  \r\n\x87\n" + b"x" * 32,
        b"SIMPLE  =                    T" + b" " * 64,
        b"%PDF-1.7\n" + b"x" * 32,
    ):
        with pytest.raises(UploadValidationError, match="Сигнатура"):
            inspect_upload(payload, "renamed.png")


def test_negative_content_length_is_rejected() -> None:
    response = client.post("/api/ai/train", content=b"{}", headers={"content-type": "application/json", "content-length": "-1"})
    assert response.status_code == 400
    assert "отрицательным" in response.json()["detail"]


def test_ai_health_reports_audit_integrity() -> None:
    response = client.get("/api/ai/health")
    assert response.status_code == 200
    payload = response.json()
    assert "audit_integrity" in payload
    assert all(item["valid"] for item in payload["audit_integrity"])


def test_ipv6_loopback_host_is_accepted() -> None:
    response = client.get("/api/health", headers={"host": "[::1]:8765"})
    assert response.status_code == 200


def test_feedback_rejects_unrelated_correction_asset() -> None:
    source = _upload()
    analysis = client.post(f"/api/assets/{source['id']}/ai/analyze").json()
    unrelated_response = client.post(
        f"/api/projects/{PROJECT}/upload",
        files=[("files", ("unrelated.png", _png(size=(88, 72)), "image/png"))],
    )
    assert unrelated_response.status_code == 200
    unrelated = unrelated_response.json()["uploaded"][0]
    response = client.post("/api/ai/feedback", json={
        "module": "upload", "asset_id": source["id"], "accepted": False,
        "features": analysis["details"]["features"], "correction_asset_id": unrelated["id"],
    })
    assert response.status_code == 422
    assert "производным" in response.json()["detail"]
    _cleanup()


def test_chunked_request_without_content_length_is_byte_limited() -> None:
    import asyncio

    chunks = [b"{" + b"x" * (2 * 1024 * 1024), b"y" * (2 * 1024 * 1024 + 32) + b"}"]
    sent: list[dict] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/ai/train",
        "raw_path": b"/api/ai/train",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8765"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "state": {},
    }

    async def receive():
        body = chunks.pop(0) if chunks else b""
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    asyncio.run(main_module.app(scope, receive, send))
    starts = [item for item in sent if item.get("type") == "http.response.start"]
    assert starts and starts[0]["status"] == 413


def test_project_store_threaded_updates_remain_valid(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone

    store = ProjectStore(tmp_path / "projects")
    project_id = "THREAD-SAFE"
    now = datetime.now(timezone.utc).isoformat()

    def add(index: int) -> None:
        ident = f"{index:032x}"
        asset = AssetRecord(
            id=ident,
            original_name=f"{index}.png",
            stored_name=f"{ident}.png",
            preview_name=f"{ident}.preview.png",
            size_bytes=1,
            sha256=f"{index:064x}",
            mime_type="image/png",
            format="PNG",
            width_px=1,
            height_px=1,
            ppi_x=300,
            ppi_y=300,
            ppi_origin="embedded",
            print_width_mm=0.08,
            print_height_mm=0.08,
            color_mode="RGBA",
            color_profile="none",
            has_alpha=True,
            created_at=now,
            preview_url=f"/api/assets/{ident}/preview",
        )
        store.add_assets(project_id, [asset])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(32)))
    reloaded = store.get_or_create(project_id)
    assert len(reloaded.assets) == 32
    assert len({item.id for item in reloaded.assets}) == 32
    json.loads((tmp_path / "projects" / f"{project_id}.json").read_text("utf-8"))


def test_audit_threaded_appends_preserve_hash_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import app.ai.audit as audit_module

    fake_settings = replace(settings, ai_audit_dir=tmp_path / "audit")
    monkeypatch.setattr(audit_module, "settings", fake_settings)
    audit = audit_module.AIAuditStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: audit.append({"task": "thread", "index": index}), range(64)))
    verification = audit.verify_all()
    assert verification and all(item["valid"] for item in verification)
    assert sum(item["checked"] for item in verification) == 64
