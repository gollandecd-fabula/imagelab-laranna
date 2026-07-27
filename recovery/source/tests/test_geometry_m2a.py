from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-M2A-GEOMETRY"


def make_image() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (80, 40), (30, 90, 180, 255)).save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def clear() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    path = settings.project_dir / f"{PROJECT}.json"
    if path.exists():
        path.unlink()


def upload() -> dict:
    clear()
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("geometry.png", make_image(), "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def process(asset_id: str, parameters: dict) -> dict:
    response = client.post(
        f"/api/projects/{PROJECT}/process",
        json={"asset_id": asset_id, "operation": "geometry", "parameters": {**parameters, "auto_repair": False}},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_resample_on_uses_requested_mm_and_ppi() -> None:
    source = upload()
    result = process(source["id"], {
        "width_mm": 25.4,
        "height_mm": 12.7,
        "ppi": 100,
        "preserve_aspect": True,
        "leading_side": "width",
        "resample": True,
    })
    assert (result["width_px"], result["height_px"]) == (100, 50)
    assert result["parameters"]["content_resampled"] is True
    assert result["parameters"]["resolved_width_mm"] == 25.4
    assert result["parameters"]["resolved_height_mm"] == 12.7
    clear()


def test_resample_off_changes_ppi_without_resizing_content() -> None:
    source = upload()
    result = process(source["id"], {
        "width_mm": 20.32,
        "height_mm": 10.16,
        "ppi": 300,
        "preserve_aspect": True,
        "leading_side": "auto",
        "resample": False,
    })
    assert (result["width_px"], result["height_px"]) == (80, 40)
    assert 99.9 <= result["ppi_x"] <= 100.1
    assert result["parameters"]["content_resampled"] is False
    assert result["parameters"]["pixel_dimensions_changed"] is False
    assert result["parameters"]["ppi_derived_from_print_size"] == 100.0
    clear()


def test_canvas_margins_are_converted_from_mm_to_pixels() -> None:
    source = upload()
    result = process(source["id"], {
        "width_mm": 20.32,
        "height_mm": 10.16,
        "ppi": 100,
        "preserve_aspect": True,
        "resample": True,
        "canvas": {"top_mm": 2.54, "bottom_mm": 2.54, "left_mm": 2.54, "right_mm": 2.54},
    })
    assert (result["width_px"], result["height_px"]) == (100, 60)
    assert result["parameters"]["canvas_applied"] is True
    assert result["parameters"]["canvas_pixels"] == {"top": 10, "bottom": 10, "left": 10, "right": 10}
    clear()


def test_height_can_be_the_leading_linked_dimension() -> None:
    source = upload()
    result = process(source["id"], {
        "width_mm": 10,
        "height_mm": 20,
        "ppi": 100,
        "preserve_aspect": True,
        "leading_side": "height",
        "resample": True,
    })
    assert result["parameters"]["resolved_width_mm"] == 40.0
    assert result["parameters"]["resolved_height_mm"] == 20.0
    assert (result["width_px"], result["height_px"]) == (157, 79)
    clear()


def test_resample_off_rejects_mismatched_unlinked_print_dimensions() -> None:
    source = upload()
    response = client.post(
        f"/api/projects/{PROJECT}/process",
        json={
            "asset_id": source["id"],
            "operation": "geometry",
            "parameters": {
                "width_mm": 20.32,
                "height_mm": 20.32,
                "ppi": 300,
                "preserve_aspect": False,
                "resample": False,
                "auto_repair": False,
            },
        },
    )
    assert response.status_code == 422
    assert "не соответствуют пропорциям" in response.text
    clear()
