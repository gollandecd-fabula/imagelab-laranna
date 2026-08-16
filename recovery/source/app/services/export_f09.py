from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services.file_inspector import inspect_upload
from app.services.qa_contract import evaluate_asset_record
from app.services.export_f09_policy import (
    EXPORT_FORMATS, ExportError, _asset_source_path, _choice, _export_preflight, _finite_float,
    _apply_color_profile, _apply_logo_variant, _load_image, _pre_create_source_gate, _qa_summary, _safe_export_folder, _safe_export_stem, _target_paths,
)
from app.services.export_f09_io import _atomic_write, _binary_reread, _normalize_dtf_alpha, _remove_internal_asset_files, _save_raster_bytes

def export_asset(asset: AssetRecord, fmt: str, params: dict[str, Any]) -> AssetRecord:
    normalized = str(fmt or "PNG").strip().upper()
    if normalized not in EXPORT_FORMATS:
        raise ExportError("Неподдерживаемый формат экспорта")

    source_stem = _safe_export_stem(params.get("filename"), Path(asset.original_name).stem or "image")
    folder = _safe_export_folder(params.get("folder", ""))
    ppi = _finite_float(params.get("ppi", asset.ppi_x or settings.workspace_ppi), "Разрешение экспорта", 100, 1000)
    quality = int(round(_finite_float(params.get("quality", 92), "Качество", 1, 100)))
    transparency = _choice(params.get("transparency", "preserve" if params.get("keep_alpha", True) else "flatten"), label="Политика прозрачности", allowed={"preserve", "flatten"}, default="preserve")
    color_profile_policy = _choice(params.get("color_profile", "preserve"), label="Политика цветового профиля", allowed={"preserve", "srgb", "strip"}, default="preserve")
    metadata_policy = _choice(params.get("metadata_policy", "minimal" if not params.get("strip_metadata", False) else "strip"), label="Политика метаданных", allowed={"minimal", "strip"}, default="minimal")
    logo_variant = _choice(params.get("logo_variant", "original"), label="Вариант Logo", allowed={"original", "black", "gray"}, default="original")

    source_qa = evaluate_asset_record(asset)
    source_gate = _pre_create_source_gate(source_qa)
    if not source_gate["passed"]:
        raise ExportError("Экспорт заблокирован независимым QA исходного файла")

    engine = get_ai_engine()
    recommendation: dict[str, Any] = {"task": "vector_export_passthrough", "model_id": "none", "model_version": "not_applicable", "provider": "deterministic"}
    advisory: dict[str, Any] = {"details": {"passed": True}, "model_id": "none", "model_version": "not_applicable", "provider": "deterministic"}
    source_icc: bytes | None = None
    if normalized == "SVG":
        if asset.format != "SVG":
            raise ExportError("SVG доступен только для векторных результатов")
        if logo_variant != "original":
            raise ExportError("Для SVG Logo Black/Gray сначала создайте соответствующий logo-result")
        source_path = _asset_source_path(asset)
        data = source_path.read_bytes()
        export_preflight = {"status": "PASS", "passed": True, "checks": {"safe_vector_source": True}, "oracle": "deterministic_export_preflight"}
        filename = f"{source_stem}.svg"
    else:
        image, source_icc = _load_image(asset)
        recommendation = engine.recommend_export(image, module="export")
        if bool(params.get("ai_auto", False)):
            normalized = str(recommendation.get("details", {}).get("format", normalized)).upper()
            if normalized == "SVG":
                normalized = "PNG_DTF"
        image = _apply_logo_variant(image, logo_variant)
        image, output_icc, profile_status = _apply_color_profile(image, source_icc, color_profile_policy)
        export_preflight = _export_preflight(image, normalized, transparency=transparency, logo_variant=logo_variant)
        if not export_preflight["passed"]:
            if normalized == "PNG_DTF" and not export_preflight["checks"].get("dtf_transparent_background", False):
                raise ExportError("PNG (DTF) требует прозрачного фона; сначала извлеките принт или удалите фон")
            if normalized == "PNG_DTF" and not export_preflight["checks"].get("dtf_visible_print_area", False):
                raise ExportError("PNG (DTF) не содержит видимой печатной области")
            raise ExportError("Экспорт заблокирован детерминированным production preflight")
        if normalized == "PNG_DTF":
            image = _normalize_dtf_alpha(image)
        advisory = engine.preflight(image, "export", module="export")
        data, suffix = _save_raster_bytes(image, normalized, ppi=ppi, quality=quality, transparency=transparency, metadata_policy=metadata_policy, icc_profile=output_icc)
        filename = f"{source_stem}{suffix}"
        export_preflight["color_profile_status"] = profile_status

    result: AssetRecord | None = None
    output_path: Path | None = None
    manifest_path: Path | None = None
    try:
        result = inspect_upload(data, filename)
        result.source_asset_id = asset.id
        result.operation = "export"
        output_path, manifest_path, output_rel, manifest_rel = _target_paths(folder, filename)
        canonical_params = {
            "input_asset_id": asset.id,
            "format": normalized,
            "filename": source_stem,
            "folder": folder.as_posix() if folder.parts else "",
            "ppi": ppi,
            "quality": quality,
            "transparency": transparency,
            "color_profile": color_profile_policy,
            "metadata_policy": metadata_policy,
            "logo_variant": logo_variant,
            "export_target": output_rel,
            "export_manifest": manifest_rel,
        }
        result.parameters = canonical_params
        result.ai = {"recommendation": recommendation, "preflight": advisory}
        reread = _binary_reread(data, result, normalized, transparency=transparency)
        if not reread["passed"]:
            raise ExportError("Binary reread результата экспорта завершился FAIL")
        output_qa = evaluate_asset_record(result)
        output_gate = _pre_create_source_gate(output_qa)
        if not output_gate["passed"]:
            raise ExportError("Экспорт заблокирован независимым QA результата")

        _atomic_write(output_path, data)
        final_bytes = output_path.read_bytes()
        if hashlib.sha256(final_bytes).hexdigest() != result.sha256 or final_bytes != data:
            raise ExportError("Финальный файл экспорта не прошёл byte-equal reread")

        manifest = {
            "schema": 1,
            "source_sha256": asset.sha256,
            "result_sha256": result.sha256,
            "operation": "export",
            "engine": {
                "model_id": recommendation.get("model_id") or type(engine).__name__,
                "model_version": recommendation.get("model_version") or "unversioned",
                "provider": recommendation.get("provider") or type(engine).__module__,
            },
            "parameters": canonical_params,
            "qa": {
                "pre_create_source": {"raw": _qa_summary(source_qa), "effective_gate": source_gate},
                "export_production_preflight": export_preflight,
                "binary_reread": reread,
                "post_create_result": {"raw": _qa_summary(output_qa), "effective_gate": output_gate},
            },
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        _atomic_write(manifest_path, manifest_bytes)
        manifest_reread = manifest_path.read_bytes()
        if manifest_reread != manifest_bytes:
            raise ExportError("Export manifest не прошёл byte-equal reread")
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        result.parameters["manifest_sha256"] = manifest_sha
        result.ai["export_contract"] = {
            "source_qa": {"raw": _qa_summary(source_qa), "effective_gate": source_gate},
            "production_preflight": export_preflight,
            "binary_reread": reread,
            "result_qa": {"raw": _qa_summary(output_qa), "effective_gate": output_gate},
            "manifest_sha256": manifest_sha,
            "final_output_sha256": result.sha256,
        }
        return result
    except Exception:
        if result is not None:
            _remove_internal_asset_files(result)
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        if manifest_path is not None:
            manifest_path.unlink(missing_ok=True)
        raise

