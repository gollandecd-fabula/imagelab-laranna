from __future__ import annotations

from collections import Counter
import hashlib
import re
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord, CheckItem, ProjectRecord, QaResponse, ProjectReportResponse
from app.services.file_inspector import inspect_and_sanitize_svg


def _asset_path(asset: AssetRecord) -> Path:
    return settings.upload_dir / asset.stored_name


def _provided(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and value == "")


def _iter_ai_records(value: Any):
    if isinstance(value, dict):
        if value.get("model_id") and value.get("model_version"):
            yield value
        for nested in value.values():
            yield from _iter_ai_records(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_ai_records(nested)


def _ai_evidence_check(asset: AssetRecord) -> CheckItem:
    records = list(_iter_ai_records(asset.ai))
    requires_ai = bool(asset.operation) and asset.operation not in {"export"} or asset.format != "SVG"
    if records:
        models = sorted({f"{item['model_id']}@{item['model_version']}" for item in records})
        return CheckItem(code="ai_evidence", label="AI-evidence присутствует", passed=True, detail=", ".join(models[:6]))
    return CheckItem(
        code="ai_evidence",
        label="AI-evidence присутствует",
        passed=not requires_ai,
        detail="AI-модель не зафиксирована" if requires_ai else "Не требуется для исходного SVG",
    )


def _alpha_border_ratio(image: Image.Image, border_fraction: float = 0.02) -> float:
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8) > 16
    height, width = alpha.shape
    border = max(1, int(round(min(height, width) * border_fraction)))
    frame = np.zeros_like(alpha)
    frame[:border, :] = True; frame[-border:, :] = True
    frame[:, :border] = True; frame[:, -border:] = True
    return float((alpha & frame).sum()) / max(1, int(alpha.sum()))


def _asset_checks(asset: AssetRecord) -> list[CheckItem]:
    checks: list[CheckItem] = []
    path = _asset_path(asset)
    checks.append(CheckItem(code="file_exists", label="Файл результата существует", passed=path.exists(), detail=str(path.name)))
    checks.append(_ai_evidence_check(asset))
    if not path.exists():
        checks.append(CheckItem(code="metadata", label="Метаданные не проверены", passed=False, detail="Файл отсутствует"))
        return checks

    if asset.operation:
        lineage_ok = bool(asset.source_asset_id) and asset.parameters.get("input_asset_id") in {None, asset.source_asset_id}
        checks.append(CheckItem(code="lineage", label="Источник операции зафиксирован", passed=lineage_ok, detail=asset.source_asset_id or "Источник отсутствует"))

    try:
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        checks.append(CheckItem(code="sha256", label="Контрольная сумма совпадает", passed=actual_hash == asset.sha256, detail=actual_hash[:16]))
        checks.append(CheckItem(code="file_size", label="Размер файла совпадает", passed=len(raw) == asset.size_bytes, detail=f"{len(raw)} байт"))
    except OSError as exc:
        checks.append(CheckItem(code="read", label="Файл читается", passed=False, detail=str(exc)))
        return checks

    if asset.format == "SVG":
        data = path.read_bytes()
        try:
            info = inspect_and_sanitize_svg(data)
            text = data.decode("utf-8", errors="ignore").lower()
            same_dimensions = (
                (asset.width_px is None or info.width_px is None or abs(asset.width_px - info.width_px) <= 1)
                and (asset.height_px is None or info.height_px is None or abs(asset.height_px - info.height_px) <= 1)
            )
            path_count = len(re.findall(r"<(?:[A-Za-z0-9_-]+:)?path\b", text))
            has_paths = path_count > 0
            reasonable_complexity = path_count <= 5000 and len(data) <= 20 * 1024 * 1024
            checks.append(CheckItem(code="safe_svg", label="SVG безопасен", passed=True))
            checks.append(CheckItem(code="dimensions", label="Размеры SVG совпадают", passed=same_dimensions, detail=f"{info.width_px}×{info.height_px}px"))
            checks.append(CheckItem(code="vector_content", label="SVG содержит контуры", passed=has_paths, detail=f"Контуров: {path_count}" if has_paths else "Пустой SVG"))
            checks.append(CheckItem(code="vector_complexity", label="Сложность SVG допустима", passed=reasonable_complexity, detail=f"{path_count} контуров, {len(data)} байт"))
        except Exception as exc:
            checks.append(CheckItem(code="safe_svg", label="SVG безопасен", passed=False, detail=str(exc)))
        checks.append(CheckItem(code="exportable", label="Файл готов к экспорту", passed=path.stat().st_size > 0))
        return checks

    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
            width, height = opened.size
            checks.append(CheckItem(code="dimensions", label="Размеры совпадают", passed=width == asset.width_px and height == asset.height_px, detail=f"{width}×{height}px"))
            pilot_size_ok = width >= 64 and height >= 64
            checks.append(CheckItem(code="pilot_min_dimensions", label="Минимальный размер Pilot QA", passed=pilot_size_ok, detail=f"{width}×{height}px; минимум 64×64px"))
            checks.append(CheckItem(code="mode", label="Цветовой режим определён", passed=True, detail=opened.mode))
            alpha = image.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            actual_alpha = bool(alpha_min < 255 or "transparency" in opened.info)
            alpha_ok = actual_alpha == bool(asset.has_alpha)
            checks.append(CheckItem(code="alpha", label="Прозрачность согласована", passed=alpha_ok, detail="Есть" if actual_alpha else "Нет"))

            operation = asset.operation or "upload"
            if operation == "extract_print":
                diagnostics = asset.parameters.get("diagnostics", {}) if isinstance(asset.parameters, dict) else {}
                coverage = diagnostics.get("coverage_ratio")
                if coverage is None:
                    alpha = image.getchannel("A")
                    histogram = alpha.histogram()
                    coverage = 1.0 - (histogram[0] / max(1, width * height))
                coverage_value = float(coverage)
                useful = 0.002 <= coverage_value <= 0.94
                checks.append(CheckItem(code="print_coverage", label="Полезная область принта", passed=useful, detail=f"{coverage_value * 100:.2f}% области"))
                transparent = image.getchannel("A").getextrema()[0] < 255
                checks.append(CheckItem(code="print_transparency", label="Фон принта прозрачен", passed=transparent))
                outside_subject = float(diagnostics.get("outside_subject_ratio", 0.0))
                mask_border = float(diagnostics.get("border_ratio", _alpha_border_ratio(image)))
                checks.append(CheckItem(code="print_garment_gate", label="Принт не содержит фон вне изделия", passed=outside_subject <= 0.001, detail=f"{outside_subject * 100:.4f}%"))
                checks.append(CheckItem(code="print_border_purity", label="Принт не прилип к границе кадра", passed=mask_border <= 0.03, detail=f"{mask_border * 100:.3f}%"))

            if operation in {"background", "master_clean"}:
                diagnostics = asset.parameters.get("diagnostics", {}) if isinstance(asset.parameters, dict) else {}
                coverage_value = float(diagnostics.get("coverage_ratio", (np.asarray(image.getchannel("A")) > 16).mean()))
                border_value = float(diagnostics.get("border_ratio", _alpha_border_ratio(image)))
                checks.append(CheckItem(code="background_subject_coverage", label="Маска объекта имеет допустимую площадь", passed=0.01 <= coverage_value <= 0.90, detail=f"{coverage_value * 100:.2f}%"))
                checks.append(CheckItem(code="background_border_purity", label="Остаточный фон на границе отсутствует", passed=border_value <= 0.03, detail=f"{border_value * 100:.3f}%"))

            if operation == "halftone":
                final_size = float(asset.parameters.get("size_mm", 0.0))
                minimum_size = float(asset.parameters.get("validator_min_size_mm", 0.0))
                checks.append(CheckItem(code="halftone_parameter_consistency", label="AI-параметры совместимы с валидатором", passed=final_size + 1e-9 >= minimum_size, detail=f"{final_size:.4f} мм ≥ {minimum_size:.4f} мм"))

            if operation == "vectorize":
                input_size = asset.parameters.get("vector_input_size_px")
                checks.append(CheckItem(code="vector_input_recorded", label="Размер входа векторизации зафиксирован", passed=isinstance(input_size, list) and len(input_size) == 2, detail=str(input_size)))

            preflight_operation = {
                "master_clean": "background",
                "master_card": "background",
                "master_dtf": "extract_print",
                "select": "background" if asset.has_alpha else "selection",
            }.get(operation, operation)
            if preflight_operation != "upload":
                preflight = get_ai_engine().preflight(image, preflight_operation, module="qa")
                details = preflight["details"]
                reasons = details.get("hard_fail_reasons", [])
                warnings = details.get("warning_reasons", [])
                detail = "PASS"
                if reasons:
                    detail = "BLOCK: " + ", ".join(reasons)
                elif warnings:
                    detail = "WARN: " + ", ".join(warnings)
                checks.append(CheckItem(code="ai_visual_preflight", label="AI-визуальная проверка", passed=bool(details["passed"]), detail=detail))

            exportable = width > 0 and height > 0 and path.stat().st_size > 0
            checks.append(CheckItem(code="exportable", label="Файл готов к экспорту", passed=exportable))
    except Exception as exc:
        checks.append(CheckItem(code="open", label="Файл открывается без ошибки", passed=False, detail=str(exc)))
    return checks



CRITICAL_CHECK_CODES = {
    "file_exists", "sha256", "lineage", "dimensions", "exportable", "safe_svg",
    "vector_content", "vector_complexity", "print_coverage", "print_garment_gate",
    "print_border_purity", "background_subject_coverage", "background_border_purity",
    "halftone_parameter_consistency", "ai_visual_preflight", "physical_ppi_range",
    "physical_size_match", "pilot_min_dimensions",
}


def evaluate_asset_record(asset: AssetRecord) -> dict[str, Any]:
    checks = [*asset.checks, *_asset_checks(asset)]
    requested_ppi = None
    if isinstance(asset.parameters, dict) and _provided(asset.parameters.get("ppi")):
        try:
            requested_ppi = float(asset.parameters.get("ppi"))
        except (TypeError, ValueError):
            requested_ppi = None
    if asset.operation in {"enhance", "reconstruct", "geometry"} and requested_ppi is not None:
        ppi_ok = 100 <= requested_ppi <= 1000 and asset.ppi_x is not None and abs(float(asset.ppi_x) - requested_ppi) <= 1.0
        checks.append(CheckItem(code="physical_ppi_range", label="PPI/DPI находится в диапазоне 100–1000", passed=ppi_ok, detail=f"запрошено {requested_ppi:g}; файл {asset.ppi_x}"))
        width_mm = asset.parameters.get("width_mm")
        height_mm = asset.parameters.get("height_mm")
        if _provided(width_mm) or _provided(height_mm):
            target_width = float(width_mm) if _provided(width_mm) else None
            target_height = float(height_mm) if _provided(height_mm) else None
            preserve = bool(asset.parameters.get("preserve_aspect", True))
            if preserve and target_width is not None and asset.width_px and asset.height_px:
                target_height = target_width * asset.height_px / asset.width_px
            width_ok = target_width is None or (asset.print_width_mm is not None and abs(float(asset.print_width_mm) - target_width) <= max(0.15, target_width * 0.002))
            height_ok = target_height is None or (asset.print_height_mm is not None and abs(float(asset.print_height_mm) - target_height) <= max(0.15, target_height * 0.002))
            checks.append(CheckItem(code="physical_size_match", label="Физический размер результата соответствует мм", passed=width_ok and height_ok, detail=f"{asset.print_width_mm} × {asset.print_height_mm} мм"))

    weighted_total = 0.0
    weighted_passed = 0.0
    defects: list[str] = []
    warnings: list[str] = []
    for check in checks:
        weight = 3.0 if check.code in CRITICAL_CHECK_CODES else 1.0
        weighted_total += weight
        if check.passed:
            weighted_passed += weight
        else:
            defects.append(check.code)
    for record in _iter_ai_records(asset.ai):
        details = record.get("details") if isinstance(record, dict) else None
        if isinstance(details, dict):
            warnings.extend(str(item) for item in details.get("warning_reasons", []) if item)
    score = round(100.0 * weighted_passed / max(1.0, weighted_total), 3)
    critical_failed = [code for code in defects if code in CRITICAL_CHECK_CODES]
    return {
        "passed": not critical_failed and score >= 85.0,
        "quality_score": score,
        "defects": defects,
        "critical_defects": critical_failed,
        "warnings": sorted(set(warnings)),
        "checks": [item.model_dump() for item in checks],
    }

def build_qa_response(project: ProjectRecord, asset: AssetRecord | None = None) -> QaResponse:
    target = asset
    if target is None and project.assets:
        target = project.assets[-1]
    checks: list[CheckItem] = []
    evaluation: dict[str, Any] | None = None
    if target is not None:
        evaluation = evaluate_asset_record(target)
        checks = [CheckItem.model_validate(item) for item in evaluation["checks"]]
    else:
        checks.append(CheckItem(code="project_empty", label="В проекте есть файлы", passed=False, detail="Проект пуст"))

    total_assets = len(project.assets)
    generated = sum(1 for item in project.assets if item.source_asset_id)
    operations = Counter((item.operation or "upload") for item in project.assets)
    overall = bool(checks) and (bool(evaluation["passed"]) if evaluation is not None else all(item.passed for item in checks))
    return QaResponse(
        project_id=project.id,
        asset_id=target.id if target else None,
        overall_passed=overall,
        checks=checks,
        summary={
            "assets_total": total_assets,
            "generated_total": generated,
            "operations": dict(operations),
            "ai_model_count": len(list(_iter_ai_records(target.ai))) if target else 0,
            "quality_score": evaluation["quality_score"] if evaluation is not None else 0.0,
            "defects": evaluation["defects"] if evaluation is not None else ["project_empty"],
        },
    )


def build_project_report(project: ProjectRecord, asset: AssetRecord | None = None) -> ProjectReportResponse:
    formats = Counter(item.format for item in project.assets)
    operations = Counter((item.operation or "upload") for item in project.assets)
    qa = build_qa_response(project, asset)
    ai_records = [record for item in project.assets for record in _iter_ai_records(item.ai)]
    model_versions = Counter(f"{record['model_id']}@{record['model_version']}" for record in ai_records)
    confidences = [float(record.get("confidence", 0.0)) for record in ai_records if isinstance(record.get("confidence"), (int, float))]
    ai_summary = {
        "runtime": get_ai_engine().health(),
        "inference_records_in_project": len(ai_records),
        "model_versions": dict(model_versions),
        "mean_confidence": round(sum(confidences) / len(confidences), 6) if confidences else None,
        "audit_scope": "project_asset_evidence_only",
        "claim_boundary": "Synthetic/model/runtime evidence only; real-world quality requires L5 user-path validation.",
    }
    return ProjectReportResponse(
        project_id=project.id,
        title=project.title,
        assets_total=len(project.assets),
        generated_total=sum(1 for item in project.assets if item.source_asset_id),
        formats=dict(formats),
        operations=dict(operations),
        latest_asset_id=project.assets[-1].id if project.assets else None,
        qa=qa,
        ai_summary=ai_summary,
    )
