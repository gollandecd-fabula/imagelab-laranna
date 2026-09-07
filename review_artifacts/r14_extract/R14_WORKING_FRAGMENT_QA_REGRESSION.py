from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from app.config import settings
from app.models import AssetRecord
from app.services import qa_service
from app.services import repair_service


def _asset(tmp_path: Path, *, working: bool = True, broken: str | None = None) -> AssetRecord:
    width, height = 80, 60
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.arange(width, dtype=np.uint8)[None, :] * 3
    rgb[:, :, 1] = np.arange(height, dtype=np.uint8)[:, None] * 4
    rgb[:, :, 2] = 91
    image = Image.fromarray(rgb, "RGB")
    stored = "r14-working.png"
    path = tmp_path / stored
    image.save(path, format="PNG")
    raw = path.read_bytes()
    now = datetime.now(timezone.utc).isoformat()
    diagnostics = {
        "coverage_ratio": 1.0,
        "region_box_px": [10, 20, 90, 80],
    }
    if working:
        fragment = {
            "strategy": "manual_roi_working_fragment_v1",
            "semantics": "working_fragment",
            "region_box_px": [10, 20, 90, 80],
            "strict_roi": True,
            "coverage_ratio": 1.0,
            "coverage_semantics": "source_alpha_coverage_working_fragment",
            "segmentation_applied": False,
            "background_removed": False,
            "texture_reduction_applied": False,
            "alpha_silhouette_dewarp_applied": False,
            "fallback": False,
            "transform_requested": False,
            "transform_applied": False,
        }
        if broken == "segmentation":
            fragment["segmentation_applied"] = True
        elif broken == "fallback":
            fragment["fallback"] = True
        elif broken == "coverage_semantics":
            fragment["coverage_semantics"] = "print_mask_coverage"
        elif broken == "strict_roi":
            fragment["strict_roi"] = False
        elif broken == "box":
            fragment["region_box_px"] = [10, 20, 95, 80]
        diagnostics["manual_roi_working_fragment"] = dict(fragment)
        diagnostics["extract_fidelity"] = dict(fragment)
    return AssetRecord(
        id="r14qa" + (broken or "ok").replace("_", "") + "0" * 20,
        original_name="source.png",
        stored_name=stored,
        preview_name=stored,
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        mime_type="image/png",
        format="PNG",
        width_px=width,
        height_px=height,
        ppi_x=300,
        ppi_y=300,
        ppi_origin="generated_embedded",
        print_width_mm=round(width / 300 * 25.4, 4),
        print_height_mm=round(height / 300 * 25.4, 4),
        color_mode="RGB",
        color_profile="none",
        has_alpha=False,
        created_at=now,
        preview_url="/preview/r14",
        download_url="/file/r14",
        source_asset_id="a" * 32,
        operation="extract_print",
        parameters={
            "mode": "region" if working else "auto",
            "input_asset_id": "a" * 32,
            "input_width_px": 100,
            "input_height_px": 100,
            "diagnostics": diagnostics,
        },
        ai={"analysis": {"model_id": "r14-qa-test", "model_version": "1", "details": {}}},
    )


def _patched_settings(tmp_path: Path):
    return replace(settings, upload_dir=tmp_path, preview_dir=tmp_path, data_dir=tmp_path)


def test_working_fragment_qa_passes_without_cutout_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_service, "settings", _patched_settings(tmp_path))
    asset = _asset(tmp_path)
    evaluation = qa_service.evaluate_asset_record(asset)
    by_code = {item["code"]: item for item in evaluation["checks"]}
    assert evaluation["passed"] is True, evaluation
    assert all(by_code[code]["passed"] for code in (
        "working_fragment_semantics",
        "working_fragment_strict_roi",
        "working_fragment_dimensions",
        "working_fragment_non_destructive",
        "working_fragment_no_fallback",
        "working_fragment_coverage_contract",
        "ai_visual_preflight",
    ))
    assert "print_coverage" not in by_code
    assert "print_transparency" not in by_code
    assert "print_garment_gate" not in by_code
    assert "print_border_purity" not in by_code
    assert "working_fragment:generic_geometry_output_gate" in by_code["ai_visual_preflight"]["detail"]


def test_working_fragment_fail_closed_on_destructive_or_contract_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_service, "settings", _patched_settings(tmp_path))
    cases = {
        "segmentation": "working_fragment_non_destructive",
        "fallback": "working_fragment_no_fallback",
        "coverage_semantics": "working_fragment_coverage_contract",
        "strict_roi": "working_fragment_strict_roi",
        "box": "working_fragment_dimensions",
    }
    for broken, expected_code in cases.items():
        asset = _asset(tmp_path, broken=broken)
        evaluation = qa_service.evaluate_asset_record(asset)
        by_code = {item["code"]: item for item in evaluation["checks"]}
        assert evaluation["passed"] is False, (broken, evaluation)
        assert expected_code in evaluation["critical_defects"], (broken, evaluation)
        assert by_code[expected_code]["passed"] is False


def test_auto_extract_keeps_legacy_cutout_qa(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_service, "settings", _patched_settings(tmp_path))
    asset = _asset(tmp_path, working=False)
    path = tmp_path / asset.stored_name
    rgba = np.asarray(Image.open(path).convert("RGBA")).copy()
    rgba[:, :40, 3] = 0
    Image.fromarray(rgba, "RGBA").save(path, format="PNG")
    raw = path.read_bytes()
    asset.size_bytes = len(raw)
    asset.sha256 = hashlib.sha256(raw).hexdigest()
    asset.has_alpha = True
    asset.parameters["diagnostics"] = {"coverage_ratio": 0.5, "outside_subject_ratio": 0.0, "border_ratio": 0.0}
    evaluation = qa_service.evaluate_asset_record(asset)
    by_code = {item["code"]: item for item in evaluation["checks"]}
    assert "print_coverage" in by_code
    assert "print_transparency" in by_code
    assert "working_fragment_semantics" not in by_code
    assert by_code["print_coverage"]["passed"] is True
    assert by_code["print_transparency"]["passed"] is True
    assert "extract_print:" in by_code["ai_visual_preflight"]["detail"]


def test_manual_region_repair_never_tunes_cutout_controls():
    evaluation = {
        "defects": ["ai_visual_preflight", "working_fragment_non_destructive"],
        "critical_defects": ["ai_visual_preflight", "working_fragment_non_destructive"],
    }
    assert repair_service._next_parameters("extract_print", {"mode": "region", "sensitivity": 58, "texture_reduction": 35}, evaluation) is None
    auto = repair_service._next_parameters("extract_print", {"mode": "auto", "sensitivity": 58, "texture_reduction": 35}, evaluation)
    assert auto is not None
    assert auto["sensitivity"] != 58 or auto["texture_reduction"] != 35


def test_working_fragment_api_qa_and_layer_contract(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as main_module
    from app.models import ProjectRecord
    from app.services.project_store import ProjectStore

    upload_dir = tmp_path / "uploads"
    project_dir = tmp_path / "projects"
    upload_dir.mkdir(); project_dir.mkdir()
    monkeypatch.setattr(qa_service, "settings", replace(settings, upload_dir=upload_dir, preview_dir=tmp_path / "previews", project_dir=project_dir, data_dir=tmp_path))

    asset = _asset(upload_dir)
    source = asset.model_copy(deep=True)
    source.id = "a" * 32
    source.source_asset_id = None
    source.operation = None
    source.parameters = {}
    source.ai = {}
    source.original_name = "source-root.png"
    now = datetime.now(timezone.utc).isoformat()
    project = ProjectRecord(id="R14-QA-API", title="R14 QA API", created_at=now, updated_at=now, assets=[source, asset])
    store = ProjectStore(project_dir)
    store.save(project)
    monkeypatch.setattr(main_module, "store", store)

    response = TestClient(main_module.app).get(f"/api/projects/{project.id}/qa?asset_id={asset.id}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["overall_passed"] is True, data
    by_code = {item["code"]: item for item in data["checks"]}
    assert by_code["working_fragment_semantics"]["passed"] is True
    assert by_code["ai_visual_preflight"]["passed"] is True
    assert "print_transparency" not in by_code
    layers = data["summary"]["layers"]
    assert layers["technical"]["status"] == "PASS"
    assert layers["visual"]["status"] == "PASS"
