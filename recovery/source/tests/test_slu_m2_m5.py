from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-SLU-M2M5"


def make_subject() -> bytes:
    image = Image.new("RGBA", (160, 160), (236, 238, 242, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 18, 132, 148), radius=12, fill=(28, 31, 38, 255))
    draw.ellipse((58, 45, 105, 92), fill=(230, 75, 32, 255))
    draw.rectangle((68, 88, 96, 120), fill=(235, 170, 42, 255))
    buffer = io.BytesIO(); image.save(buffer, "PNG", dpi=(300, 300)); return buffer.getvalue()


def clear() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    path = settings.project_dir / f"{PROJECT}.json"
    if path.exists(): path.unlink()


def upload() -> dict:
    clear()
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("subject.png", make_subject(), "image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def source_hash(asset: dict) -> str:
    path = settings.upload_dir / asset["stored_name"]
    return __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_auto_repair_is_bounded_versioned_and_source_immutable() -> None:
    source = upload(); before = source_hash(source)
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "halftone",
        "parameters": {"mode":"mono","raster":"dot","size_mm":0.05,"min_size_mm":0.05,"max_size_mm":0.5,"lpi":150,"density":100,"alpha_threshold":0,"auto_repair":True,"ai_auto":False},
    })
    assert response.status_code == 200, response.text
    payload = response.json(); repair = payload["repair"]
    assert 1 <= repair["attempt_count"] <= 3
    assert repair["source_immutable"] is True
    assert payload["result"]["source_asset_id"] == source["id"]
    assert source_hash(source) == before
    assert len(payload["attempts"]) == repair["successful_attempt_count"]
    assert all(item["parameters"]["repair_attempt"] >= 1 for item in payload["attempts"])
    clear()


def test_auto_repair_disabled_runs_one_attempt_only() -> None:
    source = upload()
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "enhance",
        "parameters": {"preset":"standard","auto_repair":False,"ai_auto":False},
    })
    assert response.status_code == 200, response.text
    repair = response.json()["repair"]
    assert repair["attempt_count"] == 1
    assert repair["auto_repair_enabled"] is False
    clear()


def test_processing_records_objective_learning_without_overwriting_source() -> None:
    source = upload(); before = source_hash(source)
    response = client.post(f"/api/projects/{PROJECT}/process", json={
        "asset_id": source["id"], "operation": "enhance",
        "parameters": {"preset":"detail","auto_repair":True,"ai_auto":True,"width_mm":25.4,"ppi":100,"preserve_aspect":True},
    })
    assert response.status_code == 200, response.text
    payload = response.json(); learning = payload["learning"]
    assert learning["module"] == "improve"
    assert learning["stored"] + learning["skipped"] >= 1
    assert learning["training"]["status"] in {"not_triggered","not_trainable","promoted","candidate_rejected"}
    assert source_hash(source) == before
    clear()


def test_cleanup_pipeline_contract_has_auto_repair_controls_in_ui() -> None:
    js = (settings.static_dir / "app.js").read_text("utf-8")
    assert "/cleanup-pipeline" in js
    assert "background_parameters" in js and "auto_repair:autoRepair" in js
    assert "cleanup_parameters" in js and "response.atomic !== true" in js
    assert "quality not" not in js.lower()


def test_export_records_continual_learning_and_ppi_bounds() -> None:
    source = upload()
    response = client.post(f"/api/projects/{PROJECT}/export", json={
        "asset_id": source["id"], "format":"PNG",
        "parameters":{"quality":92,"keep_alpha":True,"ppi":300,"ai_auto":False,"allow_ai_warning":True},
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["learning"]["module"] == "export"
    assert payload["result"]["parameters"]["ppi"] == 300
    invalid = client.post(f"/api/projects/{PROJECT}/export", json={
        "asset_id": source["id"], "format":"PNG",
        "parameters":{"ppi":99,"allow_ai_warning":True},
    })
    assert invalid.status_code == 422
    clear()
