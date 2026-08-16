from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from app.models import AssetRecord, CheckItem, ProjectRecord, QaResponse
from app.services import qa_service as legacy


_ORIGINAL_EVALUATE = legacy.evaluate_asset_record
_ORIGINAL_BUILD_QA_RESPONSE = legacy.build_qa_response

QA_LAYER_ORDER = ("technical", "visual", "fidelity", "production")
VISUAL_CHECK_CODES = {
    "visual_content_present", "vector_content", "print_coverage", "print_transparency",
    "print_garment_gate", "print_border_purity", "background_subject_coverage",
    "background_border_purity", "ai_visual_preflight",
}
FIDELITY_CHECK_CODES = {"fidelity_lineage", "fidelity_evidence_recorded", "fidelity_claim_bounded"}
PRODUCTION_CHECK_CODES = {"physical_ppi_range", "physical_size_match", "halftone_parameter_consistency", "exportable"}
FIDELITY_REQUIRED_OPERATIONS = {"reconstruct", "vectorize"}
PRODUCTION_REQUIRED_OPERATIONS = {"geometry", "halftone", "master_dtf", "export"}


def _asset_path(asset: AssetRecord):
    return legacy.settings.upload_dir / asset.stored_name


def _replace_alpha_check(asset: AssetRecord, checks: list[CheckItem]) -> list[CheckItem]:
    if asset.format == "SVG" or not _asset_path(asset).is_file():
        return checks
    replacement = None
    try:
        with Image.open(_asset_path(asset)) as opened:
            actual_alpha = bool("A" in opened.getbands() or "transparency" in opened.info)
        replacement = CheckItem(
            code="alpha",
            label="Прозрачность согласована",
            passed=actual_alpha == bool(asset.has_alpha),
            detail="Alpha-channel есть" if actual_alpha else "Alpha-channel отсутствует",
        )
    except Exception:
        return checks
    return [replacement if item.code == "alpha" else item for item in checks]


def _visual_content_check(asset: AssetRecord, checks: list[CheckItem]) -> CheckItem:
    if asset.format == "SVG":
        vector = next((item for item in checks if item.code == "vector_content"), None)
        return CheckItem(
            code="visual_content_present",
            label="Детерминированный visual-oracle: SVG содержит видимый контент",
            passed=bool(vector and vector.passed),
            detail=vector.detail if vector else "Vector-content evidence отсутствует",
        )
    path = _asset_path(asset)
    if not path.is_file():
        return CheckItem(code="visual_content_present", label="Детерминированный visual-oracle: видимый результат присутствует", passed=False, detail="Файл отсутствует")
    try:
        with Image.open(path) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        visible = rgba[:, :, 3] > 16
        visible_pixels = int(np.count_nonzero(visible))
        total = max(1, int(visible.size))
        return CheckItem(
            code="visual_content_present",
            label="Детерминированный visual-oracle: видимый результат присутствует",
            passed=visible_pixels > 0,
            detail=f"{visible_pixels}/{total} px ({visible_pixels / total * 100:.3f}%)",
        )
    except Exception as exc:
        return CheckItem(code="visual_content_present", label="Детерминированный visual-oracle: видимый результат присутствует", passed=False, detail=str(exc))


def _iter_ai_records(value: Any):
    yield from legacy._iter_ai_records(value)


def _fidelity_details(asset: AssetRecord) -> dict[str, Any] | None:
    if asset.operation == "reconstruct":
        for record in _iter_ai_records(asset.ai):
            details = record.get("details") if isinstance(record, dict) else None
            if not isinstance(details, dict):
                continue
            nested = details.get("restore_fidelity")
            if isinstance(nested, dict):
                return nested
            if "result_status" in details or "exact_recovery_claimed" in details:
                return details
    if asset.operation == "vectorize":
        diagnostics = asset.parameters.get("vector_diagnostics") if isinstance(asset.parameters, dict) else None
        if isinstance(diagnostics, dict):
            return diagnostics
        for record in _iter_ai_records(asset.ai):
            details = record.get("details") if isinstance(record, dict) else None
            if isinstance(details, dict) and isinstance(details.get("fidelity"), dict):
                return details["fidelity"]
    return None


def _fidelity_checks(asset: AssetRecord) -> list[CheckItem]:
    if (asset.operation or "upload") not in FIDELITY_REQUIRED_OPERATIONS:
        return []
    lineage_ok = bool(asset.source_asset_id) and asset.parameters.get("input_asset_id") in {None, asset.source_asset_id}
    details = _fidelity_details(asset)
    recorded = isinstance(details, dict) and bool(details)
    bounded = False
    detail = "Fidelity evidence отсутствует"
    if asset.operation == "reconstruct" and recorded:
        status = str(details.get("result_status", "")).upper()
        exact_claimed = details.get("exact_recovery_claimed") is True
        bounded = status in {"READY", "REVIEW"} and not exact_claimed
        detail = f"status={status or 'UNSET'}; exact_recovery_claimed={exact_claimed}"
    elif asset.operation == "vectorize" and recorded:
        metric_names = ("quality_score", "normalized_mae", "minimum_cluster_iou", "coverage_ratio")
        metrics = [name for name in metric_names if isinstance(details.get(name), (int, float))]
        bounded = bool(metrics) and isinstance(details.get("suitability", {}), dict)
        detail = "metrics=" + (",".join(metrics) if metrics else "none")
    return [
        CheckItem(code="fidelity_lineage", label="Fidelity QA: исходный asset/lineage зафиксирован", passed=lineage_ok, detail=asset.source_asset_id or "Источник отсутствует"),
        CheckItem(code="fidelity_evidence_recorded", label="Fidelity QA: evidence записан отдельно", passed=recorded, detail=detail),
        CheckItem(code="fidelity_claim_bounded", label="Fidelity QA: claim ограничен доказательствами", passed=bounded, detail=detail),
    ]


def _layer(name: str, checks: list[CheckItem], *, required: bool, oracles: list[str]) -> dict[str, Any]:
    if not required:
        status = "NOT_APPLICABLE"
        passed: bool | None = None
    elif not checks:
        status = "UNVERIFIED"
        passed = False
    else:
        passed = all(item.passed for item in checks)
        status = "PASS" if passed else "FAIL"
    return {
        "name": name,
        "required": required,
        "status": status,
        "passed": passed,
        "oracles": list(oracles),
        "checks": [item.model_dump() for item in checks],
        "defects": [item.code for item in checks if not item.passed],
    }


def build_layers(asset: AssetRecord, checks: list[CheckItem]) -> dict[str, dict[str, Any]]:
    operation = asset.operation or "upload"
    visual = [item for item in checks if item.code in VISUAL_CHECK_CODES]
    fidelity = [item for item in checks if item.code in FIDELITY_CHECK_CODES]
    production = [item for item in checks if item.code in PRODUCTION_CHECK_CODES]
    technical = [
        item for item in checks
        if item.code not in VISUAL_CHECK_CODES
        and item.code not in FIDELITY_CHECK_CODES
        and item.code not in {"physical_ppi_range", "physical_size_match", "halftone_parameter_consistency"}
    ]
    visual_oracles: list[str] = []
    if any(item.code != "ai_visual_preflight" for item in visual):
        visual_oracles.append("deterministic_visual_oracle")
    if any(item.code == "ai_visual_preflight" for item in visual):
        visual_oracles.append("processing_engine_advisory")
    return {
        "technical": _layer("technical", technical, required=True, oracles=["deterministic_file_metadata_oracle"]),
        "visual": _layer("visual", visual, required=True, oracles=visual_oracles),
        "fidelity": _layer("fidelity", fidelity, required=operation in FIDELITY_REQUIRED_OPERATIONS, oracles=["lineage_contract", "recorded_fidelity_diagnostics"]),
        "production": _layer("production", production, required=operation in PRODUCTION_REQUIRED_OPERATIONS, oracles=["deterministic_production_contract"]),
    }


def evaluate_asset_record(asset: AssetRecord) -> dict[str, Any]:
    base = _ORIGINAL_EVALUATE(asset)
    checks = [CheckItem.model_validate(item) for item in base["checks"]]
    checks = _replace_alpha_check(asset, checks)
    checks = [item for item in checks if item.code != "visual_content_present"]
    checks.append(_visual_content_check(asset, checks))
    checks.extend(_fidelity_checks(asset))

    defects = [item.code for item in checks if not item.passed]
    weighted_total = 0.0
    weighted_passed = 0.0
    for item in checks:
        weight = 3.0 if item.code in legacy.CRITICAL_CHECK_CODES else 1.0
        weighted_total += weight
        if item.passed:
            weighted_passed += weight
    score = round(100.0 * weighted_passed / max(1.0, weighted_total), 3)
    critical_failed = [code for code in defects if code in legacy.CRITICAL_CHECK_CODES]
    layers = build_layers(asset, checks)
    layered_passed = all(layer["status"] == "PASS" for layer in layers.values() if layer["required"])
    legacy_gate = not critical_failed and score >= 85.0

    result = dict(base)
    result.update({
        "passed": legacy_gate and layered_passed,
        "legacy_gate_passed": legacy_gate,
        "quality_score": score,
        "defects": defects,
        "critical_defects": critical_failed,
        "checks": [item.model_dump() for item in checks],
        "layers": layers,
        "layered_passed": layered_passed,
    })
    return result


def build_qa_response(project: ProjectRecord, asset: AssetRecord | None = None) -> QaResponse:
    response = _ORIGINAL_BUILD_QA_RESPONSE(project, asset)
    target = asset or (project.assets[-1] if project.assets else None)
    if target is None:
        response.summary["layers"] = {
            name: {"name": name, "required": True, "status": "UNVERIFIED", "passed": False, "oracles": [], "checks": [], "defects": ["project_empty"]}
            for name in QA_LAYER_ORDER
        }
    else:
        response.summary["layers"] = build_layers(target, response.checks)
    response.summary["qa_separation_contract"] = {
        "technical_pass_does_not_imply_visual_pass": True,
        "processing_engine_is_not_sole_oracle": True,
    }
    return response


def install() -> None:
    if getattr(legacy, "_qa91_contract_installed", False):
        return
    legacy.evaluate_asset_record = evaluate_asset_record
    legacy.build_qa_response = build_qa_response
    legacy._qa91_contract_installed = True
