from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ai.feedback import AIFeedbackError
from app.ai.runtime import get_ai_engine
from app.models import AssetRecord
from app.services.image_processing import ProcessingError, process_image
from app.services.qa_service import evaluate_asset_record


MAX_AUTO_REPAIR_ATTEMPTS = 3
OPERATION_MODULE = {
    "enhance": "improve",
    "reconstruct": "improve",
    "extract_print": "extract",
    "select": "selection",
    "background": "cleanup",
    "cleanup": "cleanup",
    "logo": "cleanup",
    "halftone": "halftone",
    "vectorize": "vector",
    "geometry": "geometry",
    "export": "export",
}


def _ai_features(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        details = value.get("details")
        if isinstance(details, dict) and isinstance(details.get("features"), list):
            try:
                return [float(item) for item in details["features"]]
            except (TypeError, ValueError):
                return None
        for nested in value.values():
            result = _ai_features(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _ai_features(nested)
            if result:
                return result
    return None


def _next_parameters(operation: str, params: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any] | None:
    defects = set(evaluation.get("defects", [])) | set(evaluation.get("critical_defects", []))
    nxt = deepcopy(params)
    changed = False

    def set_value(key: str, value: Any) -> None:
        nonlocal changed
        if nxt.get(key) != value:
            nxt[key] = value
            changed = True

    if operation == "halftone":
        density = float(nxt.get("density", 75))
        size = float(nxt.get("size_mm", 0.2))
        lpi = float(nxt.get("lpi", 45))
        if defects & {"ai_visual_preflight", "halftone_parameter_consistency"}:
            if any(code in defects for code in {"overfilled_halftone", "near_solid_halftone"}) or density > 70:
                # A near-solid result needs a decisive correction; small nudges can exhaust
                # the three-attempt safety budget without ever reaching a printable raster.
                set_value("density", max(18.0, density * 0.55))
                set_value("lpi", max(5.0, min(55.0, lpi * 0.60)))
                set_value("size_mm", min(float(nxt.get("max_size_mm", 5.0)), max(0.18, size * 1.80)))
            else:
                set_value("density", min(100.0, density * 1.18))
                set_value("lpi", max(5.0, lpi * 0.88))
                set_value("size_mm", min(float(nxt.get("max_size_mm", 5.0)), size * 1.15))
        elif defects:
            set_value("density", max(30.0, density * 0.85))

    elif operation == "extract_print":
        sensitivity = float(nxt.get("sensitivity", 58))
        if defects & {"print_garment_gate", "print_border_purity", "print_coverage", "ai_visual_preflight"}:
            if "print_coverage" in defects and sensitivity < 55:
                set_value("sensitivity", min(100.0, sensitivity + 10.0))
            else:
                set_value("sensitivity", max(10.0, sensitivity - 8.0))
                set_value("auto_margin_x", min(0.38, float(nxt.get("auto_margin_x", 0.18)) + 0.04))
                set_value("auto_margin_top", min(0.30, float(nxt.get("auto_margin_top", 0.08)) + 0.03))
                set_value("auto_margin_bottom", min(0.40, float(nxt.get("auto_margin_bottom", 0.18)) + 0.03))
            set_value("texture_reduction", min(100.0, float(nxt.get("texture_reduction", 35)) + 10.0))

    elif operation in {"background", "cleanup"}:
        sensitivity = float(nxt.get("ai_sensitivity", 55))
        if defects & {"background_subject_coverage", "background_border_purity", "ai_visual_preflight"}:
            if "background_subject_coverage" in defects and sensitivity < 45:
                set_value("ai_sensitivity", min(100.0, sensitivity + 8.0))
            else:
                set_value("ai_sensitivity", max(10.0, sensitivity - 8.0))
            set_value("feather", min(6.0, max(0.0, float(nxt.get("feather", 2)) + 1.0)))
            if operation == "cleanup":
                set_value("remove_halo", True)
                set_value("defect_cleanup", min(60, int(nxt.get("defect_cleanup", 0)) + 15))

    elif operation == "vectorize":
        if "vector_content" in defects:
            # Empty output means useful elements were filtered out; relax thresholds.
            set_value("simplify_mm", max(0.01, float(nxt.get("simplify_mm", 0.2)) * 0.55))
            set_value("min_area_mm2", max(0.01, float(nxt.get("min_area_mm2", 0.5)) * 0.30))
            set_value("colors", max(2, int(nxt.get("colors", 6))))
        elif defects & {"vector_complexity", "safe_svg", "exportable"}:
            # Excessive complexity needs the opposite correction.
            set_value("simplify_mm", min(20.0, float(nxt.get("simplify_mm", 0.2)) * 1.6))
            set_value("min_area_mm2", min(10000.0, float(nxt.get("min_area_mm2", 0.5)) * 2.0))
            set_value("colors", max(2, int(nxt.get("colors", 6)) - 1))

    elif operation in {"enhance", "reconstruct"}:
        if defects:
            set_value("denoise", min(100, int(nxt.get("denoise", 20)) + 10))
            set_value("sharpness", max(0.8, float(nxt.get("sharpness", 1.3)) * 0.9))

    if not changed:
        return None
    nxt["auto_repair"] = True
    return nxt


def _evaluation_from_error(operation: str, error: ProcessingError) -> dict[str, Any]:
    text = str(error).lower()
    defects = ["processing_error"]
    if "полутон" in text or "растров" in text or "lpi" in text:
        defects.extend(["ai_visual_preflight", "overfilled_halftone" if "сплош" in text else "no_raster_structure"])
    if "вектор" in text or "svg" in text or "контур" in text:
        if "не создала" in text or "нет видимой" in text or "пуст" in text:
            defects.append("vector_content")
        else:
            defects.append("vector_complexity")
    if "маск" in text or "фон" in text or "принт" in text:
        defects.append("ai_visual_preflight")
        defects.append("print_coverage" if operation == "extract_print" else "background_subject_coverage")
    return {
        "passed": False,
        "quality_score": 0.0,
        "defects": sorted(set(defects)),
        "critical_defects": sorted(set(defects)),
        "warnings": [],
        "checks": [],
        "error": str(error),
    }


def run_processing_with_repair(source: AssetRecord, operation: str, parameters: dict[str, Any]) -> tuple[AssetRecord, list[AssetRecord], dict[str, Any]]:
    auto_repair = bool(parameters.get("auto_repair", True))
    max_attempts = MAX_AUTO_REPAIR_ATTEMPTS if auto_repair else 1
    current = deepcopy(parameters)
    attempts: list[AssetRecord] = []
    evaluations: list[dict[str, Any]] = []
    failed_attempts: list[dict[str, Any]] = []
    previous_score: float | None = None
    stop_reason = "attempt_limit"

    for index in range(max_attempts):
        try:
            result = process_image(source, operation, current)
            evaluation = evaluate_asset_record(result)
        except ProcessingError as exc:
            evaluation = _evaluation_from_error(operation, exc)
            failed_attempts.append({
                "attempt": index + 1,
                "parameters": deepcopy(current),
                "error": str(exc),
                "defects": evaluation["defects"],
            })
            if not auto_repair:
                raise
            next_params = _next_parameters(operation, current, evaluation)
            if next_params is None or index + 1 >= max_attempts:
                if attempts:
                    stop_reason = "processing_error_after_valid_attempt"
                    break
                raise ProcessingError(f"Автоисправление не смогло создать безопасный результат: {exc}") from exc
            current = next_params
            continue

        result.parameters = {
            **result.parameters,
            "repair_attempt": index + 1,
            "repair_quality_score": evaluation["quality_score"],
            "repair_defects": evaluation["defects"],
            "repair_critical_defects": evaluation["critical_defects"],
            "auto_repair_enabled": auto_repair,
        }
        attempts.append(result)
        evaluations.append(evaluation)
        score = float(evaluation["quality_score"])
        if evaluation["passed"]:
            stop_reason = "quality_gate_passed"
            break
        if not auto_repair:
            stop_reason = "auto_repair_disabled"
            break
        if previous_score is not None and score <= previous_score + 0.25:
            stop_reason = "quality_plateau"
            break
        next_params = _next_parameters(operation, current, evaluation)
        if next_params is None:
            stop_reason = "no_safe_repair_plan"
            break
        previous_score = score
        current = next_params

    if not attempts:
        raise ProcessingError("Автоисправление не создало ни одной проверяемой версии")
    ranked = sorted(
        zip(attempts, evaluations),
        key=lambda item: (bool(item[1]["passed"]), float(item[1]["quality_score"])),
        reverse=True,
    )
    best, best_evaluation = ranked[0]
    best.parameters = {
        **best.parameters,
        "repair_selected": True,
        "repair_stop_reason": stop_reason,
        "repair_attempt_count": len(attempts) + len(failed_attempts),
    }
    summary = {
        "operation": operation,
        "source_asset_id": source.id,
        "auto_repair_enabled": auto_repair,
        "attempt_count": len(attempts) + len(failed_attempts),
        "successful_attempt_count": len(attempts),
        "failed_attempts": failed_attempts,
        "attempts": [
            {
                "asset_id": asset.id,
                "attempt": int(asset.parameters.get("repair_attempt", index + 1)),
                "quality_score": evaluation["quality_score"],
                "passed": evaluation["passed"],
                "defects": evaluation["defects"],
                "critical_defects": evaluation["critical_defects"],
            }
            for index, (asset, evaluation) in enumerate(zip(attempts, evaluations))
        ],
        "selected_asset_id": best.id,
        "selected_quality_score": best_evaluation["quality_score"],
        "passed": bool(best_evaluation["passed"]),
        "stop_reason": stop_reason,
        "source_immutable": True,
    }
    return best, attempts, summary


def record_continual_learning(attempts: list[AssetRecord], operation: str) -> dict[str, Any]:
    module = OPERATION_MODULE.get(operation, operation)
    engine = get_ai_engine()
    stored = 0
    skipped = 0
    rows_before = len(engine.feedback.list(module))
    for asset in attempts:
        features = _ai_features(asset.ai)
        if not features:
            skipped += 1
            continue
        evaluation = evaluate_asset_record(asset)
        accepted = bool(evaluation["passed"])
        try:
            engine.feedback.add(module, {
                "accepted": accepted,
                "features": features,
                "asset_id": asset.id,
                "note": f"auto_qa:{operation}:score={evaluation['quality_score']}",
                "label_source": "automatic_objective_qa",
                "quality_score": evaluation["quality_score"],
                "operation": operation,
                "evidence_codes": evaluation["defects"],
                "parameters": asset.parameters,
            })
            stored += 1
        except AIFeedbackError:
            skipped += 1
    rows_after = len(engine.feedback.list(module))
    training: dict[str, Any] = {"status": "not_triggered"}
    if rows_after >= 8 and rows_after != rows_before and rows_after % 4 == 0:
        try:
            candidate = engine.feedback.train(module)
            training = {"status": "promoted" if candidate.get("promoted") else "candidate_rejected", "candidate": candidate}
        except AIFeedbackError as exc:
            training = {"status": "not_trainable", "reason": str(exc)}
    return {
        "module": module,
        "stored": stored,
        "skipped": skipped,
        "dataset_rows": rows_after,
        "training": training,
    }
