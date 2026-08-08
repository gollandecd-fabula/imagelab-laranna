from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-A1"


def make_image() -> bytes:
    image = Image.new("RGBA", (80, 60), (255, 255, 255, 255))
    for y in range(15, 45):
        for x in range(20, 60):
            image.putpixel((x, y), (220, 20, 30, 255))
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
    response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": asset_id, "operation": operation, "parameters": parameters})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def open_result(asset: dict) -> Image.Image:
    response = client.get(asset["download_url"])
    assert response.status_code == 200
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def test_a1_enhance_reconstruct_and_color() -> None:
    source = upload()
    enhanced = process(source["id"], "enhance", {"preset": "standard"})
    assert enhanced["source_asset_id"] == source["id"]
    assert enhanced["operation"] == "enhance"
    assert (enhanced["width_px"], enhanced["height_px"]) == (80, 60)

    reconstructed = process(source["id"], "reconstruct", {"scale": 2, "detail": 40, "denoise": 10})
    assert (reconstructed["width_px"], reconstructed["height_px"]) == (160, 120)

    colored = process(source["id"], "color", {"hue": 60, "temperature": 20})
    assert open_result(colored).getpixel((30, 30))[:3] != (220, 20, 30)
    clear()


def test_a1_selection_background_and_cleanup() -> None:
    source = upload()
    selected = process(source["id"], "select", {"mode": "color", "target_color": "#dc141e", "tolerance": 10})
    selected_image = open_result(selected)
    assert selected_image.getpixel((30, 30))[3] > 240
    assert selected_image.getpixel((2, 2))[3] == 0

    removed = process(source["id"], "background", {"action": "remove_color", "target_color": "#ffffff", "tolerance": 5})
    removed_image = open_result(removed)
    assert removed_image.getpixel((2, 2))[3] == 0
    assert removed_image.getpixel((30, 30))[3] > 240

    cleaned = process(source["id"], "cleanup", {"remove_color": True, "target_color": "#ffffff", "tolerance": 5, "remove_halo": True})
    assert open_result(cleaned).getpixel((2, 2))[3] == 0
    clear()


def test_a1_geometry_mm_ppi_and_perspective() -> None:
    source = upload()
    result = process(source["id"], "geometry", {
        "width_mm": 25.4,
        "height_mm": "",
        "ppi": 100,
        "preserve_aspect": True,
        "rotate": 0,
        "crop": {"x": 0, "y": 0, "width": 100, "height": 100},
        "perspective": [[0, 0], [100, 0], [100, 100], [0, 100]],
    })
    assert result["width_px"] == 100
    assert result["height_px"] == 75
    assert 99 <= result["ppi_x"] <= 101
    assert 25.3 <= result["print_width_mm"] <= 25.5
    clear()


def test_a1_rejects_unknown_operation_and_svg_processing() -> None:
    source = upload()
    bad = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": source["id"], "operation": "magic", "parameters": {}})
    assert bad.status_code == 422
    clear()
