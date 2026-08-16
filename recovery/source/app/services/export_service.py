from __future__ import annotations

import hashlib
import io
import json
import zipfile
from typing import Any

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord, ProjectRecord
from app.services.qa_service import build_project_report
from app.services import export_f09, export_f09_io, export_f09_policy
from app.services.export_f09_policy import ExportError

_FIXED_ZIP_TIME = (2026, 7, 23, 0, 0, 0)


def export_asset(asset: AssetRecord, fmt: str, params: dict[str, Any]) -> AssetRecord:
    # Preserve the established test/runtime settings seam while keeping F09 helpers focused.
    export_f09.settings = settings
    export_f09.get_ai_engine = get_ai_engine
    export_f09_policy.settings = settings
    export_f09_io.settings = settings
    return export_f09.export_asset(asset, fmt, params)

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

