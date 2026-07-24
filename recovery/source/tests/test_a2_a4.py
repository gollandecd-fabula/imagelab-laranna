from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-A2A4"


def make_image() -> bytes:
    image = Image.new("RGBA", (80, 60), (255, 255, 255, 255))
    for y in range(10, 50):
        for x in range(18, 62):
            image.putpixel((x, y), (220, 90 if (x + y) % 2 else 20, 30, 255))
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


def export_asset(asset_id: str, fmt: str, parameters: dict) -> dict:
    response = client.post(f"/api/projects/{PROJECT}/export", json={"asset_id": asset_id, "format": fmt, "parameters": parameters})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def open_result(asset: dict) -> Image.Image:
    response = client.get(asset["download_url"])
    assert response.status_code == 200
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def test_a2_halftone_vectorization_and_masters() -> None:
    source = upload()
    halftone = process(source["id"], "halftone", {"raster": "dot", "mode": "mono", "size_mm": 0.2, "density": 90})
    halftone_image = open_result(halftone)
    assert halftone_image.size == (80, 60)

    vector = process(source["id"], "vectorize", {"mode": "color", "colors": 4, "simplify": 1.5, "min_area": 5})
    vector_file = client.get(vector["download_url"])
    assert vector_file.status_code == 200
    assert vector_file.text.startswith("<?xml")
    assert "svg" in vector_file.text.lower()

    clean_master = process(source["id"], "master_clean", {})
    assert open_result(clean_master).getpixel((2, 2))[3] == 0

    card_master = process(source["id"], "master_card", {"width_px": 1200, "height_px": 1600})
    assert (card_master["width_px"], card_master["height_px"]) == (1200, 1600)

    dtf_master = process(source["id"], "master_dtf", {})
    dtf_image = open_result(dtf_master)
    assert dtf_image.width > 0 and dtf_image.height > 0
    import numpy as np
    alpha = np.asarray(dtf_image.getchannel("A"))
    assert int(alpha.min()) == 0
    clear()


def test_a2_export_and_a4_reports_qa_bundle() -> None:
    source = upload()
    vector = process(source["id"], "vectorize", {"mode": "mono", "simplify": 1.5, "min_area": 5})
    jpg = export_asset(source["id"], "JPG", {"quality": 90, "keep_alpha": False, "filename": "TS-001_print", "ppi": 300})
    jpg_image = open_result(jpg)
    assert jpg_image.size == (80, 60)
    assert jpg["original_name"] == "TS-001_print.jpg"

    svg_export = export_asset(vector["id"], "SVG", {})
    svg_file = client.get(svg_export["download_url"])
    assert svg_file.status_code == 200
    assert "image/svg+xml" in svg_file.headers["content-type"]

    qa = client.get(f"/api/projects/{PROJECT}/qa?asset_id={jpg['id']}")
    assert qa.status_code == 200, qa.text
    qa_json = qa.json()
    assert qa_json["overall_passed"] is True
    assert any(item["code"] == "file_exists" for item in qa_json["checks"])

    report = client.get(f"/api/projects/{PROJECT}/report?asset_id={jpg['id']}")
    assert report.status_code == 200, report.text
    report_json = report.json()
    assert report_json["assets_total"] >= 3
    assert "export" in report_json["operations"]

    bundle = client.get(f"/api/projects/{PROJECT}/bundle")
    assert bundle.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    names = set(archive.namelist())
    assert "project.json" in names
    assert "report.json" in names
    assert any(name.startswith("assets/") for name in names)
    clear()
