from __future__ import annotations

import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-PRINT-EXTRACTION"


def make_garment_image() -> bytes:
    image = Image.new("RGB", (400, 500), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 30, 330, 480), radius=35, fill=(35, 36, 42))
    draw.ellipse((125, 145, 275, 300), fill=(232, 77, 18))
    draw.rectangle((182, 108, 218, 342), fill=(246, 181, 22))
    draw.polygon([(135, 320), (200, 360), (265, 320), (235, 410), (165, 410)], fill=(205, 45, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def make_plain_garment() -> bytes:
    image = Image.new("RGB", (300, 400), (230, 230, 230))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 25, 245, 380), radius=30, fill=(40, 40, 45))
    buffer = io.BytesIO(); image.save(buffer, format="PNG", dpi=(300, 300)); return buffer.getvalue()


def cleanup() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    path = settings.project_dir / f"{PROJECT}.json"
    if path.exists():
        path.unlink()


def upload(data: bytes, name: str = "garment.png") -> dict:
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", (name, data, "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def extract(asset_id: str, parameters: dict) -> dict:
    response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id": asset_id, "operation": "extract_print", "parameters": parameters})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def read_rgba(asset: dict) -> Image.Image:
    response = client.get(asset["download_url"])
    assert response.status_code == 200
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def test_extract_print_region_produces_transparent_png_and_preserves_source() -> None:
    cleanup()
    source = upload(make_garment_image())
    result = extract(source["id"], {
        "mode": "region", "x": 20, "y": 20, "width": 60, "height": 68,
        "sensitivity": 58, "texture_reduction": 35, "feather": 1,
        "crop_output": True,
    })
    assert result["operation"] == "extract_print"
    assert result["source_asset_id"] == source["id"]
    assert result["format"] == "PNG"
    assert result["has_alpha"] is True
    diagnostics = result["parameters"]["diagnostics"]
    assert 0.002 <= diagnostics["coverage_ratio"] <= 0.88

    output = read_rgba(result)
    alpha = np.asarray(output.getchannel("A"))
    assert int(alpha.min()) == 0
    assert int(alpha.max()) == 255
    assert output.width < source["width_px"]
    assert output.height < source["height_px"]

    project = client.get(f"/api/projects/{PROJECT}").json()
    source_after = next(item for item in project["assets"] if item["id"] == source["id"])
    assert source_after["sha256"] == source["sha256"]
    cleanup()


def test_extract_print_auto_mode_and_identity_perspective() -> None:
    cleanup()
    source = upload(make_garment_image())
    result = extract(source["id"], {
        "mode": "auto", "sensitivity": 60, "crop_output": False,
        "perspective": [[0, 0], [100, 0], [100, 100], [0, 100]],
    })
    image = read_rgba(result)
    assert image.width > 0 and image.height > 0
    assert result["parameters"]["diagnostics"]["region_box_px"] == [0, 0, 400, 500]
    cleanup()


def test_extract_print_rejects_plain_garment_instead_of_false_success() -> None:
    cleanup()
    source = upload(make_plain_garment(), "plain.png")
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "extract_print",
        "parameters": {"mode": "region", "x": 18, "y": 15, "width": 64, "height": 70, "sensitivity": 45}
    })
    assert response.status_code == 422
    assert "Принт не обнаружен" in response.json()["detail"]
    cleanup()


def test_extract_print_qa_checks_coverage_and_transparency() -> None:
    cleanup()
    source = upload(make_garment_image())
    result = extract(source["id"], {"mode": "region", "x": 20, "y": 20, "width": 60, "height": 68, "sensitivity": 58})
    qa = client.get(f"/api/projects/{PROJECT}/qa?asset_id={result['id']}")
    assert qa.status_code == 200, qa.text
    data = qa.json()
    assert data["overall_passed"] is True
    by_code = {item["code"]: item for item in data["checks"]}
    assert by_code["print_coverage"]["passed"] is True
    assert by_code["print_transparency"]["passed"] is True
    cleanup()
