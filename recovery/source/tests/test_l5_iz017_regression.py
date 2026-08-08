from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-L5-IZ017"
FIXTURE = Path(__file__).with_name("fixtures_iz017.png")


def clear() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    project_path = settings.project_dir / f"{PROJECT}.json"
    if project_path.exists():
        project_path.unlink()


def upload() -> dict:
    clear()
    response = client.post(
        f"/api/projects/{PROJECT}/upload",
        files=[("files", ("iz017.png", FIXTURE.read_bytes(), "image/png"))],
    )
    assert response.status_code == 200, response.text
    project = response.json()["project"]
    asset = response.json()["uploaded"][0]
    assert project["workspace"]["active_asset_id"] == asset["id"]
    return asset


def process(asset_id: str, operation: str, parameters: dict) -> dict:
    response = client.post(
        f"/api/projects/{PROJECT}/process",
        json={"asset_id": asset_id, "operation": operation, "parameters": parameters},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project"]["workspace"]["active_asset_id"] == payload["result"]["id"]
    return payload["result"]


def read_rgba(asset: dict) -> np.ndarray:
    response = client.get(asset["download_url"])
    assert response.status_code == 200
    from io import BytesIO
    return np.asarray(Image.open(BytesIO(response.content)).convert("RGBA"), dtype=np.uint8)


def test_real_iz017_extract_background_and_lineage() -> None:
    source = upload()
    extracted = process(source["id"], "extract_print", {
        "mode": "auto", "sensitivity": 58, "texture_reduction": 35,
        "reduce_fabric_texture": True, "feather": 0, "crop_output": True, "padding": 8,
    })
    assert extracted["source_asset_id"] == source["id"]
    assert extracted["parameters"]["input_asset_id"] == source["id"]
    diagnostics = extracted["parameters"]["diagnostics"]
    assert diagnostics["outside_subject_ratio"] <= 0.001
    assert diagnostics["border_ratio"] <= 0.01
    assert 0.06 <= diagnostics["coverage_ratio"] <= 0.14
    rgba = read_rgba(extracted)
    alpha = rgba[:, :, 3]
    assert alpha.min() == 0 and alpha.max() == 255
    assert 0.30 <= float((alpha > 16).mean()) <= 0.65
    assert max(alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]) == 0

    background = process(source["id"], "background", {"action": "remove", "ai_sensitivity": 55, "feather": 0})
    background_diag = background["parameters"]["diagnostics"]
    assert 0.55 <= background_diag["coverage_ratio"] <= 0.68
    assert background_diag["border_ratio"] <= 0.01
    subject_rgba = read_rgba(background)
    subject_alpha = subject_rgba[:, :, 3]
    assert subject_alpha.min() == 0 and subject_alpha.max() == 255
    assert max(subject_alpha[0, 0], subject_alpha[0, -1], subject_alpha[-1, 0], subject_alpha[-1, -1]) == 0

    pinned = client.post(f"/api/projects/{PROJECT}/active", json={"asset_id": extracted["id"]})
    assert pinned.status_code == 200, pinned.text
    assert client.get(f"/api/projects/{PROJECT}").json()["workspace"]["active_asset_id"] == extracted["id"]

    for asset in (extracted, background):
        qa = client.get(f"/api/projects/{PROJECT}/qa?asset_id={asset['id']}")
        assert qa.status_code == 200, qa.text
        assert qa.json()["overall_passed"] is True, qa.text
    clear()


def test_real_iz017_derived_print_halftone_vector_and_ai_routing() -> None:
    source = upload()
    extracted = process(source["id"], "extract_print", {
        "mode": "auto", "sensitivity": 58, "texture_reduction": 0,
        "reduce_fabric_texture": False, "feather": 0, "crop_output": True, "padding": 8,
    })
    halftone = process(extracted["id"], "halftone", {
        "ai_auto": True, "mode": "color", "raster": "dot", "size_mm": 0.05, "density": 90,
    })
    assert halftone["source_asset_id"] == extracted["id"]
    assert halftone["parameters"]["input_asset_id"] == extracted["id"]
    assert halftone["parameters"]["size_mm"] >= halftone["parameters"]["validator_min_size_mm"]
    half_alpha = read_rgba(halftone)[:, :, 3]
    assert 0.02 <= float((half_alpha > 16).mean()) <= 0.85

    vector = process(extracted["id"], "vectorize", {
        "ai_auto": True, "mode": "color", "colors": 8, "simplify": 2.0, "min_area": 12,
    })
    assert vector["source_asset_id"] == extracted["id"]
    assert vector["parameters"]["input_asset_id"] == extracted["id"]
    svg = client.get(vector["download_url"])
    assert svg.status_code == 200
    assert len(re.findall(r"<(?:[A-Za-z0-9_-]+:)?path\b", svg.text)) >= 10

    expectations = {
        "extract": "print_segmentation",
        "cleanup": "subject_segmentation",
        "halftone": "halftone_recommendation",
        "vector": "vector_recommendation",
        "geometry": "layout_assistant",
        "export": "export_recommendation",
    }
    for module, task_fragment in expectations.items():
        target = extracted if module in {"halftone", "vector", "geometry", "export"} else source
        response = client.post(f"/api/assets/{target['id']}/ai/analyze?module={module}")
        assert response.status_code == 200, f"{module}: {response.text}"
        assert task_fragment in response.json()["task"]

    for asset in (halftone, vector):
        qa = client.get(f"/api/projects/{PROJECT}/qa?asset_id={asset['id']}")
        assert qa.status_code == 200, qa.text
        assert qa.json()["overall_passed"] is True, qa.text
    clear()


def test_ui_pins_input_and_isolates_training_module() -> None:
    html = client.get("/").text
    js = client.get("/static/app.js").text
    assert 'id="activeInputName"' in html
    assert 'id="activeInputLineage"' in html
    assert '/active' in js
    assert 'feedbackModuleMap[state.module]' in js
    assert "$('#aiTrainModule').disabled = true" in js
