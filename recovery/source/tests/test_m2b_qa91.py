from __future__ import annotations

import io

from PIL import Image

from app.config import settings
from app.models import ProjectRecord
from app.services.file_inspector import inspect_upload
import app.services.qa_service as qa_service
import app.services.qa_contract as qa_contract


class PermissiveEngine:
    def preflight(self, image, operation, *, module="qa"):
        return {"details": {"passed": True, "hard_fail_reasons": [], "warning_reasons": []}}


def make_asset(*, visible: bool, operation: str, parameters: dict | None = None, ai: dict | None = None):
    image = Image.new("RGBA", (20, 16), (40, 80, 120, 255) if visible else (0, 0, 0, 0))
    buffer = io.BytesIO(); image.save(buffer, format="PNG", dpi=(300, 300))
    asset = inspect_upload(buffer.getvalue(), f"qa91-{operation}.png")
    asset.operation = operation
    asset.source_asset_id = "SRCQA001"
    asset.parameters = {"input_asset_id": "SRCQA001", **(parameters or {})}
    asset.ai = ai or {"qa91": {"model_id": "qa91-test", "model_version": "1", "confidence": 1.0, "details": {}}}
    return asset


def cleanup(asset) -> None:
    for path in (settings.upload_dir / asset.stored_name, settings.preview_dir / asset.preview_name):
        path.unlink(missing_ok=True)


def test_technical_pass_never_implies_visual_pass(monkeypatch) -> None:
    asset = make_asset(visible=False, operation="enhance")
    monkeypatch.setattr(qa_service, "get_ai_engine", lambda: PermissiveEngine())
    try:
        result = qa_service.evaluate_asset_record(asset)
        layers = result["layers"]
        by_code = {item["code"]: item for item in result["checks"]}
        assert tuple(layers) == qa_contract.QA_LAYER_ORDER
        assert layers["technical"]["status"] == "PASS"
        assert layers["visual"]["status"] == "FAIL"
        assert by_code["ai_visual_preflight"]["passed"] is True
        assert by_code["visual_content_present"]["passed"] is False
        assert "deterministic_visual_oracle" in layers["visual"]["oracles"]
        assert result["passed"] is False
    finally:
        cleanup(asset)


def test_response_exposes_four_independent_layers_and_opaque_rgba_alpha_is_valid(monkeypatch) -> None:
    asset = make_asset(visible=True, operation="enhance")
    monkeypatch.setattr(qa_service, "get_ai_engine", lambda: PermissiveEngine())
    project = ProjectRecord(id="QA91PROJECT", title="QA 9.1", created_at=asset.created_at, updated_at=asset.created_at, assets=[asset])
    try:
        response = qa_service.build_qa_response(project, asset)
        layers = response.summary["layers"]
        by_code = {item.code: item for item in response.checks}
        assert tuple(layers) == qa_contract.QA_LAYER_ORDER
        assert layers["technical"]["status"] == "PASS"
        assert layers["visual"]["status"] == "PASS"
        assert layers["fidelity"]["status"] == "NOT_APPLICABLE"
        assert layers["production"]["status"] == "NOT_APPLICABLE"
        assert by_code["alpha"].passed is True
        assert "Alpha-channel есть" in (by_code["alpha"].detail or "")
        assert response.summary["qa_separation_contract"]["processing_engine_is_not_sole_oracle"] is True
        assert response.overall_passed is True
    finally:
        cleanup(asset)


def test_fidelity_and_production_applicability_are_separate(monkeypatch) -> None:
    restore = make_asset(visible=True, operation="reconstruct", ai={"restore": {"model_id": "qa91-restore", "model_version": "1", "details": {"restore_fidelity": {"result_status": "REVIEW", "exact_recovery_claimed": False}}}})
    halftone = make_asset(visible=True, operation="halftone", parameters={"size_mm": 0.22, "validator_min_size_mm": 0.08})
    monkeypatch.setattr(qa_service, "get_ai_engine", lambda: PermissiveEngine())
    try:
        restore_result = qa_service.evaluate_asset_record(restore)
        assert restore_result["layers"]["fidelity"]["status"] == "PASS"
        assert restore_result["layers"]["production"]["status"] == "NOT_APPLICABLE"
        halftone_result = qa_service.evaluate_asset_record(halftone)
        assert halftone_result["layers"]["fidelity"]["status"] == "NOT_APPLICABLE"
        assert halftone_result["layers"]["production"]["status"] == "PASS"
        assert halftone_result["passed"] is True
    finally:
        cleanup(restore); cleanup(halftone)
