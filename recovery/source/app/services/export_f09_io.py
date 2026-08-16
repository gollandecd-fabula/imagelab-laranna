from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.config import settings
from app.models import AssetRecord
from app.services.file_inspector import inspect_upload
from app.services.export_f09_policy import ExportError, _apply_color_profile, _apply_logo_variant, _choice, _finite_float

def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _remove_internal_asset_files(asset: AssetRecord) -> None:
    for directory, name in ((settings.upload_dir, asset.stored_name), (settings.preview_dir, asset.preview_name)):
        try:
            path = (directory / name).resolve()
            path.relative_to(directory.resolve())
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _normalize_dtf_alpha(image: Image.Image) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    rgba[:, :, 3] = np.where(rgba[:, :, 3] >= 128, 255, 0).astype(np.uint8)
    if not np.any(rgba[:, :, 3] == 255) or not np.any(rgba[:, :, 3] == 0):
        raise ExportError("PNG (DTF) после бинаризации должен содержать и печатную область, и прозрачный фон")
    return Image.fromarray(rgba, "RGBA")


def _binary_reread(data: bytes, result: AssetRecord, normalized: str, *, transparency: str) -> dict[str, Any]:
    path = (settings.upload_dir / result.stored_name).resolve()
    try:
        path.relative_to(settings.upload_dir.resolve())
    except ValueError as exc:
        raise ExportError("Binary reread: некорректный внутренний путь") from exc
    persisted = path.read_bytes()
    digest = hashlib.sha256(persisted).hexdigest()
    checks: dict[str, bool] = {
        "byte_equal_to_created_payload": persisted == data,
        "sha256_matches_asset_record": digest == result.sha256,
        "size_matches_asset_record": len(persisted) == result.size_bytes,
    }
    details: dict[str, Any] = {"sha256": digest, "size_bytes": len(persisted)}
    if normalized != "SVG":
        try:
            with Image.open(io.BytesIO(persisted)) as opened:
                opened.load()
                details["decoded_format"] = opened.format
                details["decoded_size"] = list(opened.size)
                checks["decoded_dimensions_match"] = opened.size == (result.width_px, result.height_px)
                if normalized == "PNG_DTF":
                    alpha_values = set(np.unique(np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)).tolist())
                    checks["dtf_binary_alpha"] = alpha_values.issubset({0, 255}) and alpha_values == {0, 255}
                    details["alpha_values"] = sorted(alpha_values)
                if normalized == "JPG":
                    checks["jpg_has_no_alpha"] = "A" not in opened.getbands()
                if transparency == "flatten" and normalized in {"PNG", "WEBP"}:
                    checks["flattened_has_no_transparency"] = not bool("A" in opened.getbands() or "transparency" in opened.info)
        except Exception as exc:
            raise ExportError("Binary reread не смог повторно декодировать результат") from exc
    passed = all(checks.values())
    return {"status": "PASS" if passed else "FAIL", "passed": passed, "checks": checks, **details}


def _save_raster_bytes(image: Image.Image, normalized: str, *, ppi: float, quality: int, transparency: str, metadata_policy: str, icc_profile: bytes | None) -> tuple[bytes, str]:
    buffer = io.BytesIO()
    keep_metadata = metadata_policy == "minimal"
    common: dict[str, Any] = {}
    if keep_metadata:
        common["dpi"] = (ppi, ppi)
        if icc_profile:
            common["icc_profile"] = icc_profile
    prepared = image
    if transparency == "flatten":
        matte = Image.new("RGB", image.size, (255, 255, 255))
        matte.paste(image, mask=image.getchannel("A"))
        prepared = matte
    if normalized == "PNG":
        prepared.save(buffer, format="PNG", optimize=True, **common)
        suffix = ".png"
    elif normalized == "PNG_DTF":
        image.save(buffer, format="PNG", optimize=True, **common)
        suffix = "_dtf.png"
    elif normalized == "JPG":
        if prepared.mode != "RGB":
            matte = Image.new("RGB", image.size, (255, 255, 255))
            matte.paste(image, mask=image.getchannel("A"))
            prepared = matte
        prepared.save(buffer, format="JPEG", quality=max(60, quality), optimize=True, **common)
        suffix = ".jpg"
    elif normalized == "WEBP":
        kwargs: dict[str, Any] = {"quality": max(60, quality), "method": 6}
        if keep_metadata and icc_profile:
            kwargs["icc_profile"] = icc_profile
        if keep_metadata:
            exif = Image.Exif()
            exif[282] = float(ppi); exif[283] = float(ppi); exif[296] = 2
            kwargs["exif"] = exif.tobytes()
        prepared.save(buffer, format="WEBP", **kwargs)
        suffix = ".webp"
    else:
        raise ExportError("Неподдерживаемый растровый формат экспорта")
    return buffer.getvalue(), suffix

