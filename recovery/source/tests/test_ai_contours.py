from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.main import app

client = TestClient(app)
PROJECT = "TEST-AI-M6"


def _fixture_scene() -> tuple[Image.Image, np.ndarray, np.ndarray]:
    width, height = 220, 240
    yy, xx = np.mgrid[0:height, 0:width]
    background = np.zeros((height, width, 3), dtype=np.uint8)
    background[:, :, 0] = np.clip(225 - yy * 0.20, 150, 240)
    background[:, :, 1] = np.clip(235 - xx * 0.15, 155, 245)
    background[:, :, 2] = np.clip(245 - yy * 0.10, 170, 250)
    image = Image.fromarray(background, "RGB")
    subject_mask_image = Image.new("L", (width, height), 0)
    subject_draw = ImageDraw.Draw(subject_mask_image)
    shirt = [(58,35),(92,28),(101,47),(119,47),(128,28),(162,35),(199,74),(178,105),(160,91),(157,216),(63,216),(60,91),(42,105),(21,74)]
    subject_draw.polygon(shirt, fill=255)
    subject_draw.ellipse((94,24,126,60), fill=0)
    subject_mask = np.asarray(subject_mask_image, dtype=np.uint8)
    rgb = np.asarray(image).copy()
    fabric = np.array([39, 48, 59], dtype=np.float32)
    weave = 4.5 * np.sin(xx / 3.4) + 3.0 * np.sin(yy / 5.1)
    shade = 1.0 - 0.12 * ((xx - 110) / 100) ** 2 + 0.05 * np.sin(yy / 19)
    shirt_rgb = np.clip(fabric[None,None,:] * shade[:,:,None] + weave[:,:,None], 0, 255).astype(np.uint8)
    rgb[subject_mask > 0] = shirt_rgb[subject_mask > 0]
    print_mask_image = Image.new("L", (width, height), 0)
    pd = ImageDraw.Draw(print_mask_image)
    pd.ellipse((78,82,143,153), fill=255)
    pd.rectangle((91,145,130,184), fill=255)
    pd.polygon([(65,154),(88,126),(101,169)], fill=255)
    print_mask = np.minimum(np.asarray(print_mask_image, dtype=np.uint8), subject_mask)
    pidx = print_mask > 0
    rgb[pidx] = np.where((xx[pidx,None] % 2)==0, np.array([225,74,31]), np.array([235,168,42]))
    return Image.fromarray(rgb, "RGB").convert("RGBA"), subject_mask, print_mask


def _iou(pred: np.ndarray, truth: np.ndarray) -> float:
    p = pred > 16; t = truth > 0
    union = np.logical_or(p, t).sum()
    return float(np.logical_and(p, t).sum() / max(1, union))


def _clear() -> None:
    client.delete(f"/api/projects/{PROJECT}/assets")
    path = settings.project_dir / f"{PROJECT}.json"
    if path.exists():
        path.unlink()


def _upload(image: Image.Image) -> dict:
    _clear()
    buffer = io.BytesIO(); image.save(buffer, format="PNG", dpi=(300,300))
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files",("ai-scene.png",buffer.getvalue(),"image/png"))])
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]


def _records(value):
    found=[]
    def walk(v):
        if isinstance(v,dict):
            if v.get("model_id") and v.get("model_version"): found.append(v)
            for x in v.values(): walk(x)
        elif isinstance(v,list):
            for x in v: walk(x)
    walk(value); return found


def test_ai_m0_manifest_integrity_and_health() -> None:
    manifest = json.loads((settings.ai_model_dir / "manifest.json").read_text("utf-8"))
    assert len(manifest["models"]) >= 10
    for spec in manifest["models"]:
        path = settings.ai_model_dir / spec["filename"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec["sha256"]
    health = get_ai_engine().health()
    assert health["status"] == "ready"
    assert len(health["models"]) == len(manifest["models"])
    assert health["provider"] == "CPU"


def test_ai_m1_subject_and_print_segmentation_holdout() -> None:
    image, subject_truth, print_truth = _fixture_scene()
    subject, subject_ai = get_ai_engine().segment_subject(image, module="test_subject")
    print_mask, print_ai = get_ai_engine().segment_print(image, module="test_print")
    assert _iou(subject, subject_truth) >= 0.90
    assert _iou(print_mask, print_truth) >= 0.90
    assert subject_ai["model_id"] == "pixel_subject"
    assert print_ai["model_id"] == "pixel_print"
    assert subject_ai["output_sha256"]
    assert print_ai["output_sha256"]


def test_ai_m2_restoration_improves_blur_holdout() -> None:
    clean, _, _ = _fixture_scene()
    clean_rgb = np.asarray(clean.convert("RGB"))
    blurred = cv2.GaussianBlur(clean_rgb, (0,0), 1.8)
    restored, evidence = get_ai_engine().restore(Image.fromarray(blurred).convert("RGBA"), module="test_restore")
    before = float(np.mean((blurred.astype(np.float32) - clean_rgb.astype(np.float32)) ** 2))
    after = float(np.mean((np.asarray(restored.convert("RGB"),dtype=np.float32) - clean_rgb.astype(np.float32)) ** 2))
    assert after < before
    assert evidence["model_id"] == "tiny_restorer"
    assert evidence["details"]["learned_weight"] > 0


def test_ai_m3_recommendations_and_fail_closed_preflight() -> None:
    image, _, _ = _fixture_scene()
    half = get_ai_engine().recommend_halftone(image)
    vector = get_ai_engine().recommend_vector(image)
    size = get_ai_engine().recommend_size(image)
    export = get_ai_engine().recommend_export(image)
    assert half["details"]["raster"] in {"dot","line","hybrid"}
    assert 0.05 <= half["details"]["size_mm"] <= 5
    assert 2 <= vector["details"]["colors"] <= 16
    assert set(size["details"]["safe_margins"]) == {"left","top","right","bottom"}
    assert export["details"]["format"] in {"PNG_DTF","WEBP","SVG"}
    solid = Image.new("RGBA", (100,100), (20,20,20,255))
    bad = get_ai_engine().preflight(solid,"halftone")
    assert bad["details"]["passed"] is False
    assert "near_solid_halftone" in bad["details"]["hard_fail_reasons"]
    full = Image.new("RGBA",(100,100),(200,30,20,255))
    bad_print = get_ai_engine().preflight(full,"extract_print")
    assert bad_print["details"]["passed"] is False
    assert "full_mask" in bad_print["details"]["hard_fail_reasons"]


def test_ai_evidence_present_across_all_processing_sections() -> None:
    image, _, _ = _fixture_scene(); source = _upload(image)
    operations = [
        ("enhance", {"preset":"standard"}),
        ("reconstruct", {"scale":2,"detail":25}),
        ("extract_print", {"mode":"region","x":25,"y":25,"width":50,"height":60,"sensitivity":65,"crop_output":True}),
        ("select", {"mode":"object","feather":1}),
        ("background", {"action":"remove","feather":1}),
        ("cleanup", {"remove_halo":True,"defect_cleanup":10}),
        ("halftone", {"ai_auto":True,"mode":"mono","raster":"dot","size_mm":0.2,"density":80}),
        ("vectorize", {"ai_auto":True,"mode":"color","colors":5,"simplify":2,"min_area":8}),
        ("geometry", {"ai_auto_crop":True,"ppi":300,"rotate":0,"crop":{"x":0,"y":0,"width":100,"height":100}}),
    ]
    for operation, parameters in operations:
        response = client.post(f"/api/projects/{PROJECT}/process", json={"asset_id":source["id"],"operation":operation,"parameters":parameters})
        assert response.status_code == 200, f"{operation}: {response.text}"
        result = response.json()["result"]
        assert _records(result["ai"]), operation
    export = client.post(f"/api/projects/{PROJECT}/export",json={"asset_id":source["id"],"format":"PNG","parameters":{"ai_auto":False,"quality":95,"keep_alpha":True}})
    assert export.status_code == 200, export.text
    assert _records(export.json()["result"]["ai"])
    _clear()


def test_ai_m4_api_audit_explain_and_truthful_report() -> None:
    image, _, _ = _fixture_scene(); source = _upload(image)
    analysis = client.post(f"/api/assets/{source['id']}/ai/analyze")
    assert analysis.status_code == 200
    assert analysis.json()["model_id"] == "content_classifier"
    explanation = client.get(f"/api/assets/{source['id']}/ai/explain")
    assert explanation.status_code == 200
    assert explanation.json()["evidence"]["model_id"] == "content_classifier"
    audit = client.get("/api/ai/audit?limit=20")
    assert audit.status_code == 200 and audit.json()["count"] > 0
    report = client.get(f"/api/projects/{PROJECT}/report?asset_id={source['id']}")
    assert report.status_code == 200
    payload = report.json()
    assert payload["ai_summary"]["runtime"]["status"] == "ready"
    assert "claim_boundary" in payload["ai_summary"]
    _clear()


def test_ai_m5_feedback_training_promotion_and_rollback() -> None:
    import shutil
    from app.ai.feedback import AIFeedbackStore
    module = "test_feedback_m5"
    dataset = settings.ai_feedback_dir / f"{module}.jsonl"
    module_dir = settings.ai_promoted_model_dir / module
    if dataset.exists(): dataset.unlink()
    if module_dir.exists(): shutil.rmtree(module_dir)
    store = AIFeedbackStore()
    for index in range(20):
        features = np.zeros(20, dtype=float)
        features[0] = (index - 10) / 10
        features[1] = 1.0
        features[2] = ((index % 3) - 1) / 3
        store.add(module, {"features":features.tolist(),"accepted":index >= 10,"asset_id":f"asset-{index}"})
    candidate = store.train(module)
    assert candidate["promoted"] is True
    current = module_dir / "current.json"
    assert current.exists()
    # Simulate a prior promoted version to verify deterministic rollback mechanics.
    rollback = module_dir / "rollback-20260723T000000Z.json"
    previous = dict(candidate); previous["version"] = "previous-version"; previous["validation_accuracy"] = 0.70
    rollback.write_text(json.dumps(previous), encoding="utf-8")
    rolled = store.rollback(module)
    assert rolled["version"] == "previous-version"
    if dataset.exists(): dataset.unlink()
    if module_dir.exists(): shutil.rmtree(module_dir)
