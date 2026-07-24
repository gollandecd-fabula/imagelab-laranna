from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-SLU-M1"


def make_image() -> bytes:
    image = Image.new("RGBA", (80, 40), (255, 255, 255, 255))
    for y in range(8, 32):
        for x in range(18, 62):
            image.putpixel((x, y), (20, 70, 160, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def clear() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    path = settings.project_dir / f"{PROJECT}.json"
    if path.exists():
        path.unlink()


def upload() -> dict:
    clear()
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("sample.png", make_image(), "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def process(asset_id: str, operation: str, parameters: dict) -> dict:
    response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": asset_id, "operation": operation, "parameters": {**parameters, "auto_repair": False}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_ui_uses_millimetres_keeps_size_tab_and_feather_pixels() -> None:
    html = client.get("/").text
    assert 'data-module="geometry"' in html
    assert 'id="improveWidthMm"' in html and 'Желаемая ширина, мм' in html
    assert 'id="improveHeightMm"' in html and 'Желаемая высота, мм' in html
    assert 'id="improvePpi"' in html and 'min="100" max="1000"' in html
    assert 'id="selectionBrushMm"' in html and 'Диаметр кисти, мм' in html
    assert 'id="selectionGrowMm"' in html and 'Расширение края, мм' in html
    assert 'id="selectionFeather"' in html and '2 px' in html
    assert 'id="extractFeather"' in html and '1 px' in html
    assert 'id="backgroundFeather"' in html and '2 px' in html
    assert 'мм / см' not in html and 'unitSelector' not in html


def test_improvement_target_mm_and_ppi_exact_dimensions() -> None:
    source = upload()
    result = process(source["id"], "enhance", {
        "preset": "standard",
        "width_mm": 25.4,
        "height_mm": "",
        "ppi": 100,
        "preserve_aspect": True,
        "ai_auto": False,
    })
    assert result["width_px"] == 100
    assert result["height_px"] == 50
    assert 99 <= result["ppi_x"] <= 101
    assert 25.3 <= result["print_width_mm"] <= 25.5
    assert result["parameters"]["physical_size_unit"] == "mm"
    clear()


def test_ppi_boundaries_are_fail_closed() -> None:
    source = upload()
    for operation, parameters in [
        ("enhance", {"width_mm": 25.4, "ppi": 99, "ai_auto": False}),
        ("enhance", {"width_mm": 25.4, "ppi": 1001, "ai_auto": False}),
        ("geometry", {"width_mm": 25.4, "ppi": 99}),
        ("geometry", {"width_mm": 25.4, "ppi": 1001}),
    ]:
        response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": source["id"], "operation": operation, "parameters": {**parameters, "auto_repair": False}})
        assert response.status_code == 422, response.text
    clear()


def test_manual_selection_uses_brush_mm_and_feather_px() -> None:
    source = upload()
    result = process(source["id"], "select", {
        "mode": "element",
        "ai_auto": False,
        "brush_mm": 2.54,
        "grow_mm": 0,
        "feather": 2,
        "manual_edits": [{"tool": "rectangle", "points": [[0.20, 0.20], [0.80, 0.80]]}],
    })
    assert result["has_alpha"] is True
    assert result["parameters"]["brush_mm"] == 2.54
    assert result["parameters"]["feather"] == 2
    clear()


def test_halftone_and_vector_physical_parameters_are_stored_in_mm() -> None:
    source = upload()
    selected = process(source["id"], "select", {
        "mode": "color", "target_color": "#1446a0", "tolerance": 15, "feather": 0,
    })
    half = process(selected["id"], "halftone", {
        "mode": "mono", "raster": "dot", "shape": "diamond", "size_mm": 0.25,
        "min_size_mm": 0.08, "max_size_mm": 0.45, "lpi": 35, "angle": 30,
        "density": 65, "alpha_threshold": 8, "ai_auto": False,
    })
    assert half["parameters"]["physical_size_unit"] == "mm"
    assert half["parameters"]["lpi"] <= half["parameters"]["validator_max_lpi"]
    vector = process(selected["id"], "vectorize", {
        "mode": "mono", "colors": 2, "simplify_mm": 0.15, "min_area_mm2": 0.2, "ai_auto": False,
    })
    assert vector["parameters"]["simplify_mm"] == 0.15
    assert vector["parameters"]["min_area_mm2"] == 0.2
    clear()
