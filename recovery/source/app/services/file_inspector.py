from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import uuid
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from app.config import settings
from app.models import AssetRecord, CheckItem


ALLOWED_RASTER_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "BMP"}
FORMAT_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "TIFF": ".tiff", "BMP": ".bmp", "SVG": ".svg"}
FORMAT_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "BMP": "image/bmp",
    "SVG": "image/svg+xml",
}
SVG_FORBIDDEN_TAGS = {
    "script", "foreignObject", "iframe", "object", "embed", "image",
    "audio", "video", "canvas", "style", "animate", "animateMotion", "animateTransform", "set",
}
SVG_LENGTH_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(px|mm|cm|in|pt)?\s*$", re.I)
MAX_SVG_BYTES = 10 * 1024 * 1024
MAX_SVG_ELEMENTS = 50_000
MAX_SVG_TOTAL_TEXT = 2 * 1024 * 1024


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SvgInfo:
    width_px: int | None
    height_px: int | None
    width_mm: float | None
    height_mm: float | None
    sanitized: bytes


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _physical_size_mm(px: int | None, ppi: float | None) -> float | None:
    if px is None or not ppi or ppi <= 0:
        return None
    return px / ppi * 25.4


def _alpha_present(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA", "PA"}:
        return True
    return "transparency" in image.info


def _profile_name(image: Image.Image) -> str:
    icc = image.info.get("icc_profile")
    if not icc:
        return "Не встроен"
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return ImageCms.getProfileName(profile).strip() or "ICC встроен"
    except Exception:
        return "ICC встроен (не удалось прочитать имя)"


def _extract_ppi(image: Image.Image) -> tuple[float, float, str]:
    dpi = image.info.get("dpi")
    if isinstance(dpi, tuple) and len(dpi) >= 2:
        try:
            x, y = float(dpi[0]), float(dpi[1])
            if 1 <= x <= 100_000 and 1 <= y <= 100_000:
                return x, y, "embedded"
        except (TypeError, ValueError):
            pass
    return settings.workspace_ppi, settings.workspace_ppi, "workspace_default"


def _svg_length(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    match = SVG_LENGTH_RE.match(value)
    if not match:
        return None, None
    number = float(match.group(1))
    if not 0 < number <= 1_000_000:
        return None, None
    return number, (match.group(2) or "px").lower()


def _length_to_px_mm(value: float | None, unit: str | None) -> tuple[float | None, float | None]:
    if value is None or unit is None:
        return None, None
    if unit == "mm":
        return value / 25.4 * 96.0, value
    if unit == "cm":
        return value / 2.54 * 96.0, value * 10.0
    if unit == "in":
        return value * 96.0, value * 25.4
    if unit == "pt":
        return value / 72.0 * 96.0, value / 72.0 * 25.4
    return value, value / settings.workspace_ppi * 25.4


def _dangerous_css(value: str) -> bool:
    compact = value.replace("\x00", "").strip().lower()
    return any(token in compact for token in ("javascript:", "expression(", "@import", "url(", "-moz-binding"))


def inspect_and_sanitize_svg(data: bytes) -> SvgInfo:
    if not data or len(data) > MAX_SVG_BYTES:
        raise UploadValidationError("SVG пустой или превышает лимит 10 МБ")
    lowered = data[:8192].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise UploadValidationError("Небезопасный SVG: DTD и сущности запрещены")
    try:
        text = data.decode("utf-8-sig")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise UploadValidationError("Повреждённый или некорректный SVG") from exc

    root_name = root.tag.split("}")[-1]
    if root_name != "svg":
        raise UploadValidationError("Файл не является SVG")

    count = 0
    total_text = 0
    for element in root.iter():
        count += 1
        if count > MAX_SVG_ELEMENTS:
            raise UploadValidationError("SVG содержит слишком много элементов")
        local_name = element.tag.split("}")[-1]
        if local_name in SVG_FORBIDDEN_TAGS:
            raise UploadValidationError(f"Небезопасный SVG: запрещён элемент {local_name}")
        if len(element.attrib) > 100:
            raise UploadValidationError("SVG-элемент содержит слишком много атрибутов")
        total_text += len(element.text or "") + len(element.tail or "")
        if total_text > MAX_SVG_TOTAL_TEXT:
            raise UploadValidationError("SVG содержит чрезмерный объём текста")
        for attr, value in list(element.attrib.items()):
            attr_name = attr.split("}")[-1].lower()
            value_text = str(value).strip()
            value_lower = value_text.lower()
            if attr_name.startswith("on"):
                raise UploadValidationError("Небезопасный SVG: обработчики событий запрещены")
            if attr_name in {"href", "src"} and value_text and not value_text.startswith("#"):
                raise UploadValidationError("Небезопасный SVG: разрешены только внутренние ссылки #id")
            if attr_name in {"style", "fill", "stroke", "filter", "clip-path", "mask"} and _dangerous_css(value_lower):
                raise UploadValidationError("Небезопасный SVG: внешние CSS/URL-ссылки запрещены")

    width_value, width_unit = _svg_length(root.attrib.get("width"))
    height_value, height_unit = _svg_length(root.attrib.get("height"))
    width_px, width_mm = _length_to_px_mm(width_value, width_unit)
    height_px, height_mm = _length_to_px_mm(height_value, height_unit)

    view_box = root.attrib.get("viewBox")
    if (width_px is None or height_px is None) and view_box:
        try:
            parts = [float(part) for part in view_box.replace(",", " ").split()]
            if len(parts) != 4 or not all(abs(value) <= 1_000_000 for value in parts):
                raise ValueError
            _, _, vb_w, vb_h = parts
            if vb_w <= 0 or vb_h <= 0:
                raise ValueError
            width_px = width_px or vb_w
            height_px = height_px or vb_h
            width_mm = width_mm or _physical_size_mm(int(round(vb_w)), settings.workspace_ppi)
            height_mm = height_mm or _physical_size_mm(int(round(vb_h)), settings.workspace_ppi)
        except (ValueError, TypeError):
            raise UploadValidationError("Некорректный viewBox SVG")

    sanitized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if len(sanitized) > MAX_SVG_BYTES:
        raise UploadValidationError("SVG после очистки превышает лимит")
    return SvgInfo(
        width_px=int(round(width_px)) if width_px else None,
        height_px=int(round(height_px)) if height_px else None,
        width_mm=_round(width_mm),
        height_mm=_round(height_mm),
        sanitized=sanitized,
    )


def _make_preview(image: Image.Image, path: Path) -> None:
    preview = ImageOps.exif_transpose(image).copy()
    preview.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    if preview.mode not in {"RGB", "RGBA"}:
        preview = preview.convert("RGBA" if _alpha_present(preview) else "RGB")
    preview.save(path, format="PNG", optimize=True)


def _atomic_write(directory: Path, final_name: str, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=final_name + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, directory / final_name)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _supported_raster_magic(data: bytes) -> bool:
    # Reject all parser families outside the explicit product contract before
    # Pillow selects a decoder. This blocks EPS/PDF/FITS/JPEG2000 polyglots even
    # when they are renamed with a supported extension.
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        or data.startswith((b"II*\x00", b"MM\x00*"))
        or data.startswith(b"BM")
    )


def inspect_upload(data: bytes, original_name: str) -> AssetRecord:
    if not data:
        raise UploadValidationError("Пустой файл")
    if len(data) > settings.max_upload_bytes:
        raise UploadValidationError("Файл превышает лимит 50 МБ")

    asset_id = uuid.uuid4().hex
    sha256 = hashlib.sha256(data).hexdigest()
    safe_name = Path(original_name or "image").name[:255]
    now = datetime.now(timezone.utc).isoformat()

    sniff = data[:4096].lstrip().lower()
    is_svg = sniff.startswith(b"<") and (b"<svg" in sniff or b":svg" in sniff)
    if is_svg:
        info = inspect_and_sanitize_svg(data)
        stored_name = f"{asset_id}.svg"
        preview_name = stored_name
        record = AssetRecord(
            id=asset_id,
            original_name=safe_name,
            stored_name=stored_name,
            preview_name=preview_name,
            size_bytes=len(info.sanitized),
            sha256=hashlib.sha256(info.sanitized).hexdigest(),
            mime_type=FORMAT_MIME["SVG"],
            format="SVG",
            width_px=info.width_px,
            height_px=info.height_px,
            ppi_x=settings.workspace_ppi,
            ppi_y=settings.workspace_ppi,
            ppi_origin="workspace_default",
            print_width_mm=info.width_mm,
            print_height_mm=info.height_mm,
            color_mode="Vector",
            color_profile="Не применимо",
            has_alpha=True,
            created_at=now,
            preview_url=f"/api/assets/{asset_id}/preview",
            download_url=f"/api/assets/{asset_id}/file",
            checks=[
                CheckItem(code="integrity", label="Файл не повреждён", passed=True),
                CheckItem(code="format", label="Формат поддерживается", passed=True),
                CheckItem(code="safe_svg", label="SVG безопасен", passed=True),
                CheckItem(code="dimensions", label="Размер определён", passed=bool(info.width_px and info.height_px)),
            ],
        )
        _atomic_write(settings.upload_dir, stored_name, info.sanitized)
        return record

    if not _supported_raster_magic(data):
        raise UploadValidationError("Сигнатура файла не соответствует PNG, JPG, WEBP, TIFF или BMP")

    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    preview_buffer = io.BytesIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            opened = Image.open(io.BytesIO(data))
            opened.verify()
        with Image.open(io.BytesIO(data)) as image:
            detected_format = (image.format or "").upper()
            if detected_format not in ALLOWED_RASTER_FORMATS:
                raise UploadValidationError("Поддерживаются PNG, JPG, WEBP, TIFF, BMP и SVG")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                raise UploadValidationError("Некорректный или чрезмерный размер изображения")
            ppi_x, ppi_y, ppi_origin = _extract_ppi(image)
            color_mode = image.mode
            has_alpha = _alpha_present(image)
            profile = _profile_name(image)
            suffix = FORMAT_SUFFIX[detected_format]
            stored_name = f"{asset_id}{suffix}"
            preview_name = f"{asset_id}.preview.png"
            preview = ImageOps.exif_transpose(image).copy()
            preview.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
            if preview.mode not in {"RGB", "RGBA"}:
                preview = preview.convert("RGBA" if _alpha_present(preview) else "RGB")
            preview.save(preview_buffer, format="PNG", optimize=True)
    except UploadValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UploadValidationError("Повреждённый файл или неподдерживаемый формат") from exc
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UploadValidationError("Изображение превышает безопасный лимит пикселей") from exc

    record = AssetRecord(
        id=asset_id,
        original_name=safe_name,
        stored_name=stored_name,
        preview_name=preview_name,
        size_bytes=len(data),
        sha256=sha256,
        mime_type=FORMAT_MIME[detected_format],
        format=detected_format,
        width_px=width,
        height_px=height,
        ppi_x=_round(ppi_x),
        ppi_y=_round(ppi_y),
        ppi_origin=ppi_origin,
        print_width_mm=_round(_physical_size_mm(width, ppi_x)),
        print_height_mm=_round(_physical_size_mm(height, ppi_y)),
        color_mode=color_mode,
        color_profile=profile,
        has_alpha=has_alpha,
        created_at=now,
        preview_url=f"/api/assets/{asset_id}/preview",
        download_url=f"/api/assets/{asset_id}/file",
        checks=[
            CheckItem(code="integrity", label="Файл не повреждён", passed=True),
            CheckItem(code="format", label="Формат поддерживается", passed=True),
            CheckItem(code="dimensions", label="Размер определён", passed=True),
            CheckItem(code="resolution", label="Разрешение определено", passed=True, detail=f"{_round(ppi_x)} PPI"),
            CheckItem(code="transparency", label="Прозрачность проверена", passed=True, detail="Есть" if has_alpha else "Нет"),
            CheckItem(code="profile", label="Цветовой профиль проверен", passed=True, detail=profile),
        ],
    )
    _atomic_write(settings.upload_dir, stored_name, data)
    try:
        _atomic_write(settings.preview_dir, preview_name, preview_buffer.getvalue())
    except Exception:
        try:
            (settings.upload_dir / stored_name).unlink()
        except FileNotFoundError:
            pass
        raise
    return record
