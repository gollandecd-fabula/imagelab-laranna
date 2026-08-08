from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord, ProjectRecord
from app.services.file_inspector import inspect_upload
from app.services.qa_service import build_project_report


class ExportError(ValueError):
    pass


EXPORT_FORMATS = {"PNG", "PNG_DTF", "JPG", "WEBP", "SVG"}
_FIXED_ZIP_TIME = (2026, 7, 23, 0, 0, 0)


def _safe_export_stem(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    raw = Path(raw).stem
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "_", raw).strip("._-")
    return safe[:100] or fallback


def _load_image(asset: AssetRecord) -> Image.Image:
    path = (settings.upload_dir / asset.stored_name).resolve()
    try:
        path.relative_to(settings.upload_dir.resolve())
    except ValueError as exc:
        raise ExportError("Некорректный путь исходного файла") from exc
    if not path.exists():
        raise ExportError("Исходный файл не найден")
    if asset.format == "SVG":
        raise ExportError("Для растрового экспорта выберите растровый файл или сначала выполните векторизацию")
    try:
        with Image.open(path) as source:
            source.load()
            return source.convert("RGBA")
    except OSError as exc:
        raise ExportError("Исходный файл повреждён") from exc


def _finite_float(value: Any, label: str, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ExportError(f"{label} должно быть числом") from exc
    if not math.isfinite(parsed) or not low <= parsed <= high:
        raise ExportError(f"{label} должно быть от {low:g} до {high:g}")
    return parsed


def export_asset(asset: AssetRecord, fmt: str, params: dict[str, Any]) -> AssetRecord:
    normalized = str(fmt or "PNG").strip().upper()
    if normalized not in EXPORT_FORMATS:
        raise ExportError("Неподдерживаемый формат экспорта")

    source_stem = _safe_export_stem(params.get("filename"), Path(asset.original_name).stem or "image")
    engine = get_ai_engine()
    if normalized == "SVG":
        if asset.format != "SVG":
            raise ExportError("SVG доступен только для векторных результатов")
        source_path = settings.upload_dir / asset.stored_name
        data = source_path.read_bytes()
        result = inspect_upload(data, f"{source_stem}.svg")
        result.source_asset_id = asset.id
        result.operation = "export"
        result.parameters = {"format": "SVG", **params}
        result.ai = {
            "source_vector_ai": asset.ai,
            "export_validation": {"status": "vector_source_verified", "model_evidence_present": bool(asset.ai)},
        }
        return result

    image = _load_image(asset)
    recommendation = engine.recommend_export(image, module="export")
    if bool(params.get("ai_auto", False)):
        normalized = recommendation["details"]["format"]
        if normalized == "SVG":
            normalized = "PNG_DTF"
    ppi = _finite_float(params.get("ppi", asset.ppi_x or settings.workspace_ppi), "Разрешение экспорта", 100, 1000)
    quality = int(round(_finite_float(params.get("quality", 92), "Качество", 1, 100)))
    keep_alpha = bool(params.get("keep_alpha", True))
    strip_metadata = bool(params.get("strip_metadata", False))

    if normalized == "PNG_DTF":
        alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
        coverage = float((alpha > 16).mean())
        if alpha.min() == 255 or coverage > 0.985:
            raise ExportError("PNG (DTF) требует прозрачного фона; сначала извлеките принт или удалите фон")
        if coverage < 0.001:
            raise ExportError("PNG (DTF) не содержит видимой печатной области")

    preflight = engine.preflight(image, "export", module="export")
    if not preflight["details"]["passed"] and not bool(params.get("allow_ai_warning", False)):
        raise ExportError("AI-preflight обнаружил непригодный результат. Исправьте файл или подтвердите экспорт с предупреждением")

    buffer = io.BytesIO()
    dpi_args = {} if strip_metadata else {"dpi": (ppi, ppi)}
    if normalized == "PNG":
        image.save(buffer, format="PNG", optimize=True, **dpi_args)
        filename = f"{source_stem}.png"
    elif normalized == "PNG_DTF":
        image.save(buffer, format="PNG", optimize=True, **dpi_args)
        filename = f"{source_stem}_dtf.png"
    elif normalized == "JPG":
        matte = Image.new("RGB", image.size, (255, 255, 255))
        matte.paste(image, mask=image.getchannel("A"))
        matte.save(buffer, format="JPEG", quality=max(60, quality), optimize=True, **dpi_args)
        filename = f"{source_stem}.jpg"
    elif normalized == "WEBP":
        webp_args: dict[str, Any] = {"quality": max(60, quality), "method": 6}
        if not strip_metadata:
            exif = Image.Exif()
            exif[282] = float(ppi)  # XResolution
            exif[283] = float(ppi)  # YResolution
            exif[296] = 2  # inches
            webp_args["exif"] = exif.tobytes()
        if keep_alpha:
            image.save(buffer, format="WEBP", **webp_args)
        else:
            matte = Image.new("RGB", image.size, (255, 255, 255))
            matte.paste(image, mask=image.getchannel("A"))
            matte.save(buffer, format="WEBP", **webp_args)
        filename = f"{source_stem}.webp"
    else:
        raise ExportError("Неподдерживаемый формат экспорта")

    result = inspect_upload(buffer.getvalue(), filename)
    result.source_asset_id = asset.id
    result.operation = "export"
    result.parameters = {
        "format": normalized,
        "quality": quality,
        "keep_alpha": keep_alpha,
        "strip_metadata": strip_metadata,
        "ppi": None if strip_metadata else ppi,
    }
    result.ai = {"recommendation": recommendation, "preflight": preflight}
    return result


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def build_project_bundle(project: ProjectRecord) -> tuple[bytes, str]:
    report = build_project_report(project)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        _zip_write(archive, "project.json", json.dumps(project.model_dump(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8"))
        _zip_write(archive, "report.json", json.dumps(report.model_dump(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8"))
        for asset in sorted(project.assets, key=lambda item: item.id):
            source_path = settings.upload_dir / asset.stored_name
            if source_path.exists():
                _zip_write(archive, f"assets/{asset.stored_name}", source_path.read_bytes())
            if asset.format != "SVG":
                preview_path = settings.preview_dir / asset.preview_name
                if preview_path.exists():
                    _zip_write(archive, f"previews/{asset.preview_name}", preview_path.read_bytes())
    return buffer.getvalue(), f"{project.id}_bundle.zip"


def _lineage_for_asset(project: ProjectRecord, asset: AssetRecord) -> list[dict[str, Any]]:
    by_id = {item.id: item for item in project.assets}
    lineage: list[dict[str, Any]] = []
    current = asset
    visited: set[str] = set()
    while True:
        if current.id in visited:
            raise ExportError("Lineage выбранного файла содержит цикл")
        visited.add(current.id)
        lineage.append({
            "asset_id": current.id,
            "source_asset_id": current.source_asset_id,
            "operation": current.operation,
            "sha256": current.sha256,
            "stored_name": current.stored_name,
        })
        if current.source_asset_id is None:
            break
        parent = by_id.get(current.source_asset_id)
        if parent is None:
            raise ExportError("Lineage выбранного файла повреждён")
        current = parent
    return lineage


def build_cardlab_package(project: ProjectRecord, asset: AssetRecord) -> tuple[bytes, str]:
    """Build a deterministic selected-asset handoff with explicit evidence boundary."""
    if asset.id not in {item.id for item in project.assets}:
        raise ExportError("Выбранный файл отсутствует в проекте")
    source_path = (settings.upload_dir / asset.stored_name).resolve()
    try:
        source_path.relative_to(settings.upload_dir.resolve())
    except ValueError as exc:
        raise ExportError("Некорректный путь выбранного файла") from exc
    if not source_path.is_file():
        raise ExportError("Выбранный файл отсутствует на диске")
    files: dict[str, bytes] = {f"print/{asset.stored_name}": source_path.read_bytes()}
    preview_path = (settings.preview_dir / asset.preview_name).resolve()
    try:
        preview_path.relative_to(settings.preview_dir.resolve())
    except ValueError as exc:
        raise ExportError("Некорректный путь предпросмотра") from exc
    if preview_path.is_file():
        files[f"preview/{asset.preview_name}"] = preview_path.read_bytes()

    lineage = _lineage_for_asset(project, asset)
    lineage_bytes = json.dumps(lineage, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    qa_boundary = {
        "status": "IMAGE_LAB_HANDOFF_ONLY",
        "selected_asset_id": asset.id,
        "verified": ["selected file SHA-256", "project lineage", "deterministic package integrity"],
        "not_verified": ["CardLab receiving-side layout", "marketplace card rendering", "installed Windows L4/L5"],
    }
    qa_bytes = json.dumps(qa_boundary, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    files["lineage.json"] = lineage_bytes
    files["qa-boundary.json"] = qa_bytes
    manifest = {
        "schema": 1,
        "package_type": "ImageLab-CardLab-selected-asset",
        "project_id": project.id,
        "asset_id": asset.id,
        "asset_sha256": asset.sha256,
        "files": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}
            for name, payload in sorted(files.items())
        },
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(files.items()):
            _zip_write(archive, name, payload)
    return buffer.getvalue(), f"{project.id}_{asset.id}_cardlab.zip"
