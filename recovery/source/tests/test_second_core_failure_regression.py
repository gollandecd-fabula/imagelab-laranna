from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.main import app
from app.services.image_processing import _ai_subject_result

client = TestClient(app)
PROJECT = "TEST-C2-CORE-RECOVERY"


def cleanup() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    (settings.project_dir / f"{PROJECT}.json").unlink(missing_ok=True)


def flat_art_bytes() -> bytes:
    image = Image.new("RGBA", (420, 360), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((45, 35, 375, 330), fill=(245, 190, 105, 255), outline=(20, 20, 25, 255), width=12)
    draw.ellipse((110, 100, 185, 225), fill=(255, 255, 255, 255), outline=(10, 10, 15, 255), width=8)
    draw.ellipse((230, 100, 305, 225), fill=(255, 255, 255, 255), outline=(10, 10, 15, 255), width=8)
    draw.ellipse((142, 145, 165, 190), fill=(15, 35, 80, 255))
    draw.ellipse((252, 145, 275, 190), fill=(15, 35, 80, 255))
    draw.ellipse((165, 205, 255, 285), fill=(35, 45, 55, 255), outline=(10, 10, 15, 255), width=7)
    buffer = io.BytesIO(); image.save(buffer, "PNG", dpi=(300, 300)); return buffer.getvalue()


def upload_flat() -> dict:
    cleanup()
    response = client.post(
        f"/api/projects/{PROJECT}/upload",
        files=[("files", ("flat-art.png", flat_art_bytes(), "image/png"))],
    )
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def test_runtime_identity_is_visible_and_update_safe() -> None:
    health = client.get("/api/health").json()
    assert health["version"] == settings.app_version
    assert health["scope"] == "IUL_M6_UPDATE_LOCK_CANDIDATE"
    html = (settings.static_dir / "index.html").read_text("utf-8")
    js = (settings.static_dir / "app.js").read_text("utf-8")
    bootstrap = Path("bootstrap.py").read_text("utf-8")
    installer = Path("windows_installer/installer/main.go").read_text("utf-8")
    assert 'id="buildVersionChip"' in html
    assert "runtime.version" in js and "/api/health" in js
    assert "require_current_identity=True" in bootstrap
    assert "stopRunningImageLab" in installer and settings.app_version in installer


def test_repinning_same_asset_still_confirms_server_state() -> None:
    source = upload_flat()
    first = client.post(f"/api/projects/{PROJECT}/active", json={"asset_id": source["id"]})
    assert first.status_code == 200
    revision1 = first.json()["workspace"]["active_revision"]
    second = client.post(f"/api/projects/{PROJECT}/active", json={"asset_id": source["id"]})
    assert second.status_code == 200
    assert second.json()["workspace"]["active_asset_id"] == source["id"]
    assert second.json()["workspace"]["active_revision"] > revision1
    cleanup()


def test_vectorization_uses_exact_selected_asset_and_preserves_flat_art() -> None:
    source = upload_flat()
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"],
        "operation": "vectorize",
        "parameters": {
            "mode": "color", "colors": 8, "simplify_mm": 0.08,
            "min_area_mm2": 0.02, "optimize": True, "ai_auto": True,
            "auto_repair": False,
        },
    })
    assert response.status_code == 200, response.text
    payload = response.json(); result = payload["result"]
    assert payload["source_asset_id"] == source["id"]
    assert result["source_asset_id"] == source["id"]
    assert result["parameters"]["vector_input_policy"] == "exact_selected_asset_no_auto_segmentation"
    fidelity = result["parameters"]["vector_diagnostics"]
    assert fidelity["coverage_ratio"] >= 0.84
    assert fidelity["quality_score"] >= 0.70
    assert fidelity["path_count"] >= 6
    assert result["parameters"]["colors"] == 8
    assert result["parameters"]["simplify_mm"] == 0.08
    cleanup()


def test_background_hybrid_removes_textured_frame_and_keeps_subject() -> None:
    width, height = 360, 300
    y, x = np.mgrid[:height, :width]
    rgb = np.stack([175 + x // 9, 165 + y // 8, 155 + (x + y) // 16], axis=2).clip(0, 255).astype(np.uint8)
    noise = np.random.default_rng(20260724).integers(-10, 11, size=(height, width, 1), dtype=np.int16)
    rgb = np.clip(rgb.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    image = Image.fromarray(rgb, "RGB").convert("RGBA")
    truth = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(image); truth_draw = ImageDraw.Draw(truth)
    box = (72, 30, 288, 278)
    draw.rounded_rectangle(box, radius=36, fill=(28, 35, 48, 255))
    truth_draw.rounded_rectangle(box, radius=36, fill=255)
    draw.ellipse((118, 72, 246, 202), fill=(232, 72, 48, 255))

    result, evidence = _ai_subject_result(image, {"feather": 0, "ai_sensitivity": 55}, module="cleanup")
    predicted = np.asarray(result.getchannel("A"), dtype=np.uint8) > 16
    expected = np.asarray(truth, dtype=np.uint8) > 16
    intersection = int(np.count_nonzero(predicted & expected))
    union = int(np.count_nonzero(predicted | expected))
    iou = intersection / max(1, union)
    assert iou >= 0.88
    assert not predicted[1, 1]
    assert predicted[150, 180]
    assert evidence["details"]["hybrid_selection"]["selected"] in {
        "learned", "border_connected", "union", "intersection"
    }


def test_frontend_never_short_circuits_server_confirmation_for_same_asset() -> None:
    js = (settings.static_dir / "app.js").read_text("utf-8")
    assert "assetId === state.selectedId" not in js
    assert "activeSelectionEpoch" in js
    assert "result.source_asset_id !== asset.id" in js
