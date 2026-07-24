from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.main import app
from app.services.image_processing import _clean_subject_mask

client = TestClient(app)
PROJECT = "TEST-CORE-FAILURE"


def cleanup() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    (settings.project_dir / f"{PROJECT}.json").unlink(missing_ok=True)


def make_raster(size=(100, 50), ppi=300) -> bytes:
    image = Image.new("RGB", size, (232, 234, 238))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 6, size[0]-8, size[1]-6), fill=(25, 30, 38))
    draw.ellipse((size[0]//3, size[1]//5, size[0]*2//3, size[1]*4//5), fill=(230, 65, 35))
    buffer = io.BytesIO(); image.save(buffer, "PNG", dpi=(ppi, ppi)); return buffer.getvalue()


def upload() -> dict:
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("sample.png", make_raster(), "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def test_resize_ppi_are_applied_to_pixels_file_and_metadata() -> None:
    cleanup(); source = upload()
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "enhance", "parameters": {
            "preset": "standard", "width_mm": 50.8, "height_mm": "", "ppi": 200,
            "preserve_aspect": True, "ai_auto": False, "auto_repair": False,
        },
    })
    assert response.status_code == 200, response.text
    payload = response.json(); result = payload["result"]
    assert (result["width_px"], result["height_px"]) == (400, 200)
    assert result["ppi_x"] == 200 and result["ppi_y"] == 200
    assert abs(result["print_width_mm"] - 50.8) < 0.01
    assert payload["project"]["workspace"]["active_asset_id"] == result["id"]
    stored = settings.upload_dir / result["stored_name"]
    with Image.open(stored) as image:
        assert image.size == (400, 200)
        dpi = image.info.get("dpi")
        assert dpi and abs(float(dpi[0]) - 200) < 1
    cleanup()


def test_active_asset_switch_controls_next_operation_source() -> None:
    cleanup(); source = upload()
    first = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "enhance", "parameters": {
            "preset":"detail", "width_mm":25.4, "ppi":100, "preserve_aspect":True,
            "auto_repair":False, "ai_auto":False,
        },
    }).json()["result"]
    pin_source = client.post(f"/api/projects/{PROJECT}/active", json={"asset_id": source["id"]})
    assert pin_source.status_code == 200
    assert pin_source.json()["workspace"]["active_asset_id"] == source["id"]
    pin_first = client.post(f"/api/projects/{PROJECT}/active", json={"asset_id": first["id"]})
    assert pin_first.status_code == 200
    assert pin_first.json()["workspace"]["active_asset_id"] == first["id"]
    second = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": first["id"], "operation":"enhance", "parameters": {
            "preset":"standard", "ppi":250, "auto_repair":False, "ai_auto":False,
        },
    })
    assert second.status_code == 200, second.text
    assert second.json()["result"]["source_asset_id"] == first["id"]
    cleanup()


def test_generic_opaque_raster_vectorizes_and_becomes_active() -> None:
    cleanup(); source = upload()
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation":"vectorize", "parameters": {
            "mode":"color", "colors":5, "simplify_mm":0.15, "min_area_mm2":0.05,
            "ai_auto":True, "auto_repair":False,
        },
    })
    assert response.status_code == 200, response.text
    payload = response.json(); result = payload["result"]
    assert result["format"] == "SVG"
    assert payload["project"]["workspace"]["active_asset_id"] == result["id"]
    svg = client.get(result["download_url"])
    assert svg.status_code == 200 and "path" in svg.text and "svg" in svg.text
    preview = client.get(result["preview_url"])
    assert preview.status_code == 200 and preview.headers["content-type"].startswith("image/svg+xml")
    cleanup()


def test_subject_mask_cleanup_removes_disconnected_background_islands() -> None:
    image = Image.new("RGBA", (120, 100), (238, 238, 238, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 12, 90, 92), fill=(30, 32, 38, 255))
    mask = np.zeros((100, 120), dtype=np.uint8)
    mask[12:93, 30:91] = 255
    mask[2:18, 2:18] = 255
    mask[80:98, 100:118] = 255
    cleaned, diagnostics = _clean_subject_mask(image, mask, feather=0)
    assert cleaned[8, 8] == 0 and cleaned[90, 110] == 0
    assert cleaned[50, 60] == 255
    assert diagnostics["largest_component_enforced"] is True


def test_frontend_uses_optimistic_persistent_switch_and_svg_img_preview() -> None:
    js = (settings.static_dir / "app.js").read_text("utf-8")
    html = (settings.static_dir / "index.html").read_text("utf-8")
    assert "activeSelectionEpoch" in js
    assert "state.selectedId = assetId; renderProject();" in js
    assert "project.workspace?.active_asset_id" in js
    assert "asset.format === 'SVG'" in js and "image.src=previewUrl" in js
    assert "1.4.1-update-lock" in html
    assert 'id="buildVersionChip"' in html
