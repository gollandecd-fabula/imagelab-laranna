from __future__ import annotations

import io
import math
from pathlib import Path
from typing import Any

import cv2

# OpenCV parallel workers can deadlock across repeated FastAPI thread-pool calls
# on some Windows/Linux builds. ImageLab serializes heavy operations at the API
# level, so a single OpenCV worker is the safer deterministic configuration.
cv2.setNumThreads(1)
try:
    cv2.ocl.setUseOpenCL(False)
except AttributeError:
    pass
import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps

from app.ai.registry import AIModelError
from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord, CheckItem
from app.services.file_inspector import UploadValidationError, inspect_upload


class ProcessingError(ValueError):
    pass


def _provided(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and value == "")


def _number(params: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    raw = params.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ProcessingError(f"Параметр {key} должен быть числом") from exc
    if not low <= value <= high:
        raise ProcessingError(f"Параметр {key} должен быть от {low} до {high}")
    return value


def _integer(params: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    return int(round(_number(params, key, default, low, high)))


def _bool(params: dict[str, Any], key: str, default: bool = False) -> bool:
    raw = params.get(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", "да"}
    return bool(raw)


def _hex_rgb(value: Any, default: str = "#ffffff") -> tuple[int, int, int]:
    text = str(value or default).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ProcessingError("Цвет должен быть указан в формате #RRGGBB")
    try:
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ProcessingError("Цвет должен быть указан в формате #RRGGBB") from exc


def _check_output_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ProcessingError("Итоговый размер изображения некорректен")
    if width * height > settings.max_image_pixels or width > 24000 or height > 24000:
        raise ProcessingError("Итоговый размер превышает безопасный лимит")




def _physical_target_size(image: Image.Image, params: dict[str, Any], ppi: float) -> tuple[int, int, float] | None:
    width_raw = params.get("width_mm")
    height_raw = params.get("height_mm")
    width_present = _provided(width_raw)
    height_present = _provided(height_raw)
    if not width_present and not height_present:
        return None
    target_ppi = _number(params, "ppi", ppi, 100, 1000)
    width_mm = _number({"value": width_raw}, "value", 1, 0.1, 2000) if width_present else None
    height_mm = _number({"value": height_raw}, "value", 1, 0.1, 2000) if height_present else None
    preserve = _bool(params, "preserve_aspect", True)
    if preserve:
        if width_mm is None and height_mm is not None:
            width_mm = height_mm * image.width / image.height
        elif height_mm is None and width_mm is not None:
            height_mm = width_mm * image.height / image.width
        elif width_mm is not None and height_mm is not None:
            height_mm = width_mm * image.height / image.width
    if width_mm is None or height_mm is None:
        raise ProcessingError("Укажите ширину или высоту результата в мм")
    width_px = max(1, int(round(width_mm / 25.4 * target_ppi)))
    height_px = max(1, int(round(height_mm / 25.4 * target_ppi)))
    _check_output_size(width_px, height_px)
    return width_px, height_px, target_ppi


def _apply_physical_target(image: Image.Image, params: dict[str, Any], ppi: float) -> tuple[Image.Image, float]:
    target = _physical_target_size(image, params, ppi)
    if target is None:
        # Even without a physical resize, an explicitly supplied PPI must obey the locked range.
        if _provided(params.get("ppi")):
            ppi = _number(params, "ppi", ppi, 100, 1000)
        return image, ppi
    width_px, height_px, target_ppi = target
    if image.size != (width_px, height_px):
        image = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
    return image, target_ppi

def _load_rgba(asset: AssetRecord) -> tuple[Image.Image, float]:
    if asset.format == "SVG":
        raise ProcessingError("Операции над растром недоступны для SVG. Используйте экспорт SVG или выберите растровый файл.")
    path = settings.upload_dir / asset.stored_name
    if not path.exists():
        raise ProcessingError("Исходный файл не найден")
    try:
        with Image.open(path) as source:
            ppi = float(asset.ppi_x or settings.workspace_ppi)
            image = ImageOps.exif_transpose(source)
            icc = source.info.get("icc_profile")
            if icc:
                try:
                    source_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    target_profile = ImageCms.createProfile("sRGB")
                    image = ImageCms.profileToProfile(image.convert("RGB"), source_profile, target_profile, outputMode="RGB")
                except Exception:
                    image = image.convert("RGBA")
            return image.convert("RGBA"), ppi
    except (OSError, ValueError) as exc:
        raise ProcessingError("Не удалось прочитать исходное изображение") from exc


def _rgba_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def _pil_from_rgba(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), "RGBA")


def _apply_rgb_alpha(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
    rgba = np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), np.clip(alpha, 0, 255).astype(np.uint8)))
    return Image.fromarray(rgba, "RGBA")


def _save_result(image: Image.Image, ppi: float, source: AssetRecord, operation: str, params: dict[str, Any], filename_suffix: str = "png", ai: dict[str, Any] | None = None) -> AssetRecord:
    _check_output_size(*image.size)
    if not math.isfinite(float(ppi)) or not 100 <= float(ppi) <= 1000:
        raise ProcessingError("PPI/DPI результата должен быть от 100 до 1000")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True, dpi=(float(ppi), float(ppi)))
    payload = buffer.getvalue()
    try:
        with Image.open(io.BytesIO(payload)) as persisted:
            persisted_size = persisted.size
            persisted_dpi = persisted.info.get("dpi")
            persisted_ppi_x = float(persisted_dpi[0]) if isinstance(persisted_dpi, tuple) and len(persisted_dpi) >= 2 else None
            persisted_ppi_y = float(persisted_dpi[1]) if isinstance(persisted_dpi, tuple) and len(persisted_dpi) >= 2 else None
    except (OSError, ValueError, TypeError) as exc:
        raise ProcessingError("Не удалось повторно проверить сохранённый PNG") from exc
    stem = Path(source.original_name).stem[:80] or "image"
    asset = inspect_upload(payload, f"{stem}_{operation}.{filename_suffix}")
    # PNG stores resolution through pHYs and may round it to pixels per metre.
    # Keep the requested production value as the canonical project metadata while
    # the file itself still contains the embedded pHYs value written above.
    canonical_ppi = round(float(ppi), 4)
    asset.ppi_x = canonical_ppi
    asset.ppi_y = canonical_ppi
    asset.ppi_origin = "generated_embedded"
    asset.print_width_mm = round(image.width / canonical_ppi * 25.4, 4)
    asset.print_height_mm = round(image.height / canonical_ppi * 25.4, 4)
    file_dimensions_ok = persisted_size == image.size and asset.width_px == image.width and asset.height_px == image.height
    file_ppi_ok = persisted_ppi_x is not None and persisted_ppi_y is not None and abs(persisted_ppi_x - canonical_ppi) <= 1.0 and abs(persisted_ppi_y - canonical_ppi) <= 1.0
    input_ppi = float(source.ppi_x or settings.workspace_ppi)
    evidence = {
        "input_width_px": source.width_px,
        "input_height_px": source.height_px,
        "input_ppi": round(input_ppi, 4),
        "result_width_px": image.width,
        "result_height_px": image.height,
        "result_ppi": canonical_ppi,
        "embedded_ppi_x": None if persisted_ppi_x is None else round(persisted_ppi_x, 4),
        "embedded_ppi_y": None if persisted_ppi_y is None else round(persisted_ppi_y, 4),
        "pixel_dimensions_changed": (source.width_px, source.height_px) != image.size,
        "ppi_changed": abs(input_ppi - canonical_ppi) > 0.01,
    }
    asset.checks.extend([
        CheckItem(code="generated_dimensions", label="Размер результата записан в файл", passed=file_dimensions_ok, detail=f"{persisted_size[0]} × {persisted_size[1]} px"),
        CheckItem(code="generated_ppi", label="PPI/DPI записан в файл", passed=file_ppi_ok, detail=f"{persisted_ppi_x if persisted_ppi_x is not None else 'нет'} × {persisted_ppi_y if persisted_ppi_y is not None else 'нет'} PPI"),
    ])
    if not file_dimensions_ok or not file_ppi_ok:
        raise ProcessingError("Проверка сохранённого размера или PPI не пройдена")
    asset.source_asset_id = source.id
    asset.operation = operation
    asset.parameters = {**params, **evidence}
    asset.ai = ai or {}
    asset.download_url = f"/api/assets/{asset.id}/file"
    return asset


def _save_svg_result(svg_text: str, source: AssetRecord, operation: str, params: dict[str, Any], *, ppi: float, ai: dict[str, Any] | None = None) -> AssetRecord:
    stem = Path(source.original_name).stem[:80] or "image"
    asset = inspect_upload(svg_text.encode("utf-8"), f"{stem}_{operation}.svg")
    canonical_ppi = round(float(ppi), 4)
    asset.ppi_x = canonical_ppi
    asset.ppi_y = canonical_ppi
    asset.ppi_origin = "vector_source"
    if asset.width_px and asset.height_px:
        asset.print_width_mm = round(asset.width_px / canonical_ppi * 25.4, 4)
        asset.print_height_mm = round(asset.height_px / canonical_ppi * 25.4, 4)
    asset.source_asset_id = source.id
    asset.operation = operation
    asset.parameters = {**params, "result_ppi": canonical_ppi}
    asset.ai = ai or {}
    asset.download_url = f"/api/assets/{asset.id}/file"
    return asset


def _enhance(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    preset = str(params.get("preset", "standard"))
    brightness = _number(params, "brightness", 1.0, 0.2, 2.5)
    contrast = _number(params, "contrast", 1.0, 0.2, 2.5)
    saturation = _number(params, "saturation", 1.0, 0.0, 3.0)
    sharpness = _number(params, "sharpness", 1.0, 0.0, 4.0)
    denoise = _integer(params, "denoise", 0, 0, 100)
    if preset == "soft":
        brightness, contrast, saturation, sharpness = 1.02, 1.04, 1.02, 1.1
    elif preset == "detail":
        contrast, saturation, sharpness = 1.08, 1.04, 1.35
    rgba = _rgba_array(image)
    alpha = rgba[:, :, 3]
    rgb = Image.fromarray(rgba[:, :, :3], "RGB")
    if denoise:
        rgb = rgb.filter(ImageFilter.GaussianBlur(radius=max(0.1, denoise / 40)))
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Color(rgb).enhance(saturation)
    rgb = ImageEnhance.Sharpness(rgb).enhance(sharpness)
    return _apply_rgb_alpha(np.asarray(rgb, dtype=np.uint8), alpha)


def _reconstruct(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    scale = _integer(params, "scale", 2, 1, 4)
    detail = _integer(params, "detail", 45, 0, 100)
    denoise = _integer(params, "denoise", 20, 0, 100)
    target = (max(1, image.width * scale), max(1, image.height * scale))
    result = image.resize(target, Image.Resampling.LANCZOS)
    if denoise:
        result = result.filter(ImageFilter.MedianFilter(size=3 if denoise < 60 else 5))
    if detail:
        result = ImageEnhance.Sharpness(result).enhance(1 + detail / 80)
        result = ImageEnhance.Contrast(result).enhance(1 + detail / 300)
    return result


def _auto_object_mask(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    if np.any(alpha < 250):
        return alpha
    rgb = rgba[:, :, :3]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, 8)
    if count <= 1:
        return np.full(alpha.shape, 255, dtype=np.uint8)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = np.where(labels == largest, 255, 0).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def _color_mask(rgb: np.ndarray, target: tuple[int, int, int], tolerance: float, invert: bool = False) -> np.ndarray:
    work = rgb.astype(np.float32)
    delta = np.linalg.norm(work - np.asarray(target, dtype=np.float32), axis=2)
    threshold = max(2.0, tolerance / 100.0 * 441.67)
    mask = np.where(delta <= threshold, 255, 0).astype(np.uint8)
    return 255 - mask if invert else mask


def _rect_mask(shape: tuple[int, int], params: dict[str, Any]) -> np.ndarray:
    height, width = shape
    x = _number(params, "x", 10, 0, 100)
    y = _number(params, "y", 10, 0, 100)
    box_w = _number(params, "width", 80, 0.1, 100)
    box_h = _number(params, "height", 80, 0.1, 100)
    x0 = int(round(width * x / 100))
    y0 = int(round(height * y / 100))
    x1 = int(round(width * min(100, x + box_w) / 100))
    y1 = int(round(height * min(100, y + box_h) / 100))
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 255
    return mask


def _refine_mask(mask: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    grow = _number(params, "grow", 0, -20, 20)
    feather = _number(params, "feather", 0, 0, 40)
    if abs(grow) > 1e-6:
        size = max(1, int(round(abs(grow))))
        kernel = np.ones((size * 2 + 1, size * 2 + 1), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1) if grow > 0 else cv2.erode(mask, kernel, iterations=1)
    if feather:
        sigma = max(0.5, feather / 2)
        mask = cv2.GaussianBlur(mask, (0, 0), sigma)
    return mask


def _build_mask(rgba: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    mode = str(params.get("mode", "object"))
    if mode in {"object", "print", "element"}:
        if mode == "print" and params.get("target_color"):
            mask = _color_mask(rgba[:, :, :3], _hex_rgb(params.get("target_color")), _number(params, "tolerance", 22, 0, 100))
        elif mode == "element" and any(key in params for key in ("x", "y", "width", "height")):
            mask = _rect_mask(rgba.shape[:2], params)
        else:
            mask = _auto_object_mask(rgba)
    elif mode == "color":
        mask = _color_mask(rgba[:, :, :3], _hex_rgb(params.get("target_color", "#ffffff")), _number(params, "tolerance", 20, 0, 100), _bool(params, "invert", False))
    elif mode == "rect":
        mask = _rect_mask(rgba.shape[:2], params)
    else:
        raise ProcessingError("Неизвестный режим выделения")
    mask = np.minimum(mask, rgba[:, :, 3])
    return _refine_mask(mask, params)



def _extract_region(image: Image.Image, params: dict[str, Any]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    mode = str(params.get("mode", "auto")).lower()
    if mode not in {"auto", "region"}:
        raise ProcessingError("Режим извлечения принта должен быть auto или region")
    if mode == "auto":
        # Automatic extraction must inspect the entire product image. A fixed
        # central crop silently loses sleeve, leg, side and off-centre prints.
        return image.copy(), (0, 0, image.width, image.height)
    x = _number(params, "x", 10, 0, 99)
    y = _number(params, "y", 10, 0, 99)
    width = _number(params, "width", 80, 1, 100)
    height = _number(params, "height", 80, 1, 100)
    x0 = int(round(image.width * x / 100))
    y0 = int(round(image.height * y / 100))
    x1 = int(round(image.width * min(100, x + width) / 100))
    y1 = int(round(image.height * min(100, y + height) / 100))
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise ProcessingError("Область принта слишком мала")
    return image.crop((x0, y0, x1, y1)), (x0, y0, x1, y1)


def _estimate_garment_lab(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    height, width = alpha.shape
    border = max(2, int(round(min(height, width) * 0.08)))
    border_mask = np.zeros_like(alpha, dtype=bool)
    border_mask[:border, :] = True
    border_mask[-border:, :] = True
    border_mask[:, :border] = True
    border_mask[:, -border:] = True
    border_mask &= alpha > 16
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    samples = lab[border_mask]
    if samples.shape[0] < 20:
        samples = lab[alpha > 16]
    if samples.shape[0] < 20:
        raise ProcessingError("Не удалось определить цвет изделия")
    return np.median(samples, axis=0)



def _graphic_support_mask(region: Image.Image, params: dict[str, Any]) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Find one coherent printed graphic without treating the whole photograph as print.

    This support mask is deliberately conservative. It is used to constrain the AI
    pixel mask on product photographs with a visually distinct, connected graphic.
    If no reliable component is found, callers continue with the normal AI/fallback
    path instead of fabricating a result.
    """
    rgba = _rgba_array(region)
    rgb = rgba[:, :, :3]
    source_alpha = rgba[:, :, 3]
    height, width = source_alpha.shape
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    # Product graphics are usually inside the main product area. Keep a generous
    # central search field, but do not allow metallic/photo background at the frame
    # edges to become part of the print merely because it is colourful or bright.
    margin_x = int(round(width * _number(params, "auto_margin_x", 0.18, 0.0, 0.40)))
    margin_top = int(round(height * _number(params, "auto_margin_top", 0.08, 0.0, 0.35)))
    margin_bottom = int(round(height * _number(params, "auto_margin_bottom", 0.18, 0.0, 0.45)))
    search = np.zeros((height, width), dtype=np.uint8)
    search[margin_top:max(margin_top + 1, height - margin_bottom), margin_x:max(margin_x + 1, width - margin_x)] = 255

    # Seed from pigment-like colour and bright ink. Black ink cannot be separated
    # from black fabric directly; it is recovered later by filling the coherent
    # outer graphic contour defined by the coloured/bright ink.
    chroma_seed = (saturation >= _integer(params, "graphic_min_saturation", 50, 10, 220)) & (value >= 55)
    bright_seed = value >= _integer(params, "graphic_bright_value", 175, 100, 250)
    seed = np.where((chroma_seed | bright_seed) & (search > 0) & (source_alpha > 16), 255, 0).astype(np.uint8)
    seed = cv2.morphologyEx(seed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    join = max(3, int(round(min(height, width) * 0.008)))
    if join % 2 == 0:
        join += 1
    seed = cv2.dilate(seed, np.ones((join, join), np.uint8), iterations=2)
    close = max(5, int(round(min(height, width) * 0.018)))
    if close % 2 == 0:
        close += 1
    seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8), iterations=2)

    count, labels, stats, centroids = cv2.connectedComponentsWithStats((seed > 0).astype(np.uint8), 8)
    if count <= 1:
        return None, {"reason": "no_graphic_component"}

    image_area = float(height * width)
    centre = np.asarray([width / 2.0, height * 0.43], dtype=np.float32)
    candidates: list[tuple[float, int]] = []
    for label in range(1, count):
        x, y, comp_w, comp_h, area = [int(value) for value in stats[label]]
        ratio = area / image_area
        if ratio < 0.003 or ratio > 0.55:
            continue
        distance = float(np.linalg.norm((centroids[label] - centre) / np.asarray([max(1, width), max(1, height)])))
        compactness = area / float(max(1, comp_w * comp_h))
        score = ratio * 4.0 + compactness * 0.7 - distance * 0.9
        candidates.append((score, label))
    if not candidates:
        return None, {"reason": "no_reliable_graphic_component"}

    _, selected = max(candidates)
    component = np.where(labels == selected, 255, 0).astype(np.uint8)
    shrink = max(1, int(round(join * 0.35)))
    component = cv2.erode(component, np.ones((shrink * 2 + 1, shrink * 2 + 1), np.uint8), iterations=1)
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, {"reason": "component_without_contour"}
    support = np.zeros_like(component)
    cv2.drawContours(support, contours, -1, 255, thickness=-1)
    support = np.minimum(support, source_alpha)

    ys, xs = np.where(support > 16)
    if len(xs) == 0:
        return None, {"reason": "empty_support"}
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    coverage = float((support > 16).mean())
    touches_frame = bbox[0] <= 1 or bbox[1] <= 1 or bbox[2] >= width - 1 or bbox[3] >= height - 1
    if coverage < 0.004 or coverage > 0.60 or touches_frame:
        return None, {"reason": "unsafe_support", "coverage_ratio": round(coverage, 6), "bbox_px": bbox}
    return support, {"reason": "ok", "coverage_ratio": round(coverage, 6), "bbox_px": bbox}


def _extract_print(image: Image.Image, params: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    region, region_box = _extract_region(image, params)
    if params.get("perspective") is not None:
        region = _perspective(region, params.get("perspective"))

    rgba = _rgba_array(region)
    rgb = rgba[:, :, :3]
    source_alpha = rgba[:, :, 3]
    garment_lab = _estimate_garment_lab(rgb, source_alpha)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)

    # Fabric shadows mainly change lightness. Print pigment normally changes chroma,
    # lightness, or both. Weight chroma more heavily to suppress folds and lighting.
    delta_l = np.abs(lab[:, :, 0] - garment_lab[0])
    delta_ab = np.linalg.norm(lab[:, :, 1:3] - garment_lab[1:3], axis=2)
    score = delta_ab * 1.35 + delta_l * 0.48

    sensitivity = _number(params, "sensitivity", 58, 0, 100)
    threshold = max(7.0, 42.0 - sensitivity * 0.30)
    mask = np.where(score >= threshold, 255, 0).astype(np.uint8)
    mask = np.minimum(mask, source_alpha)

    # Remove isolated fabric noise, join pigment regions, and preserve small details.
    min_side = max(3, min(mask.shape))
    open_size = 3 if min_side >= 24 else 1
    close_size = 5 if min_side >= 40 else 3
    if open_size > 1:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((open_size, open_size), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((close_size, close_size), np.uint8), iterations=1)

    min_area_ratio = _number(params, "min_area_ratio", 0.0008, 0.0, 0.05)
    min_area = max(2, int(round(mask.shape[0] * mask.shape[1] * min_area_ratio)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 8).astype(np.uint8), 8)
    filtered = np.zeros_like(mask)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= min_area:
            filtered[labels == label] = mask[labels == label]
    mask = filtered

    feather = _number(params, "feather", 1.0, 0, 20)
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), max(0.4, feather / 2))

    coverage = float(np.count_nonzero(mask > 16)) / float(mask.size)
    if coverage < 0.002:
        raise ProcessingError("Принт не обнаружен. Укажите область принта или увеличьте чувствительность")
    if coverage > 0.88:
        raise ProcessingError("Извлечение захватило почти всё изделие. Уменьшите чувствительность или укажите область")

    if _bool(params, "reduce_fabric_texture", True):
        smoothed = cv2.bilateralFilter(rgb, 7, 24, 24)
        strength = _number(params, "texture_reduction", 35, 0, 100) / 100.0
        weight = (mask.astype(np.float32) / 255.0 * strength)[:, :, None]
        rgb = np.clip(rgb.astype(np.float32) * (1.0 - weight) + smoothed.astype(np.float32) * weight, 0, 255).astype(np.uint8)

    result = _apply_rgb_alpha(rgb, mask)
    if _bool(params, "crop_output", True):
        bbox = _bbox_from_alpha(mask)
        if bbox:
            x0, y0, x1, y1 = bbox
            padding = _integer(params, "padding", 8, 0, 200)
            x0 = max(0, x0 - padding)
            y0 = max(0, y0 - padding)
            x1 = min(result.width, x1 + padding)
            y1 = min(result.height, y1 + padding)
            result = result.crop((x0, y0, x1, y1))

    diagnostics = {
        "region_box_px": list(region_box),
        "coverage_ratio": round(coverage, 6),
        "threshold": round(threshold, 3),
        "garment_lab": [round(float(value), 3) for value in garment_lab],
    }
    return result, diagnostics


def _selection(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(image)
    mask = _build_mask(rgba, params)
    rgba[:, :, 3] = mask
    return _pil_from_rgba(rgba)




def _manual_mask_edits(mask: np.ndarray, params: dict[str, Any], *, ppi: float, source_alpha: np.ndarray) -> np.ndarray:
    edits = params.get("manual_edits")
    if not isinstance(edits, list) or not edits:
        return mask
    if len(edits) > 500:
        raise ProcessingError("Слишком много ручных правок выделения")
    height, width = mask.shape
    brush_mm = _number(params, "brush_mm", 5.0, 0.1, 100.0)
    brush_px = max(1, int(round(brush_mm / 25.4 * ppi)))
    output = mask.copy()

    def point(raw: Any) -> tuple[int, int]:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ProcessingError("Некорректная точка ручного выделения")
        x = float(raw[0]); y = float(raw[1])
        if not (math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ProcessingError("Координаты ручного выделения должны быть от 0 до 1")
        return int(round(x * max(1, width - 1))), int(round(y * max(1, height - 1)))

    for edit in edits:
        if not isinstance(edit, dict):
            raise ProcessingError("Некорректная ручная правка выделения")
        tool = str(edit.get("tool", "brush")).lower()
        points_raw = edit.get("points")
        if not isinstance(points_raw, list) or not points_raw or len(points_raw) > 5000:
            raise ProcessingError("Некорректный путь ручного выделения")
        points = [point(item) for item in points_raw]
        value = 0 if tool == "erase" else 255
        if tool in {"brush", "erase"}:
            if len(points) == 1:
                cv2.circle(output, points[0], max(1, brush_px // 2), value, -1, lineType=cv2.LINE_AA)
            else:
                cv2.polylines(output, [np.asarray(points, dtype=np.int32)], False, value, thickness=brush_px, lineType=cv2.LINE_AA)
                for item in (points[0], points[-1]):
                    cv2.circle(output, item, max(1, brush_px // 2), value, -1, lineType=cv2.LINE_AA)
        elif tool == "rectangle":
            if len(points) < 2:
                raise ProcessingError("Для прямоугольника нужны две точки")
            cv2.rectangle(output, points[0], points[-1], value, -1)
        elif tool == "lasso":
            if len(points) < 3:
                raise ProcessingError("Для лассо нужны минимум три точки")
            cv2.fillPoly(output, [np.asarray(points, dtype=np.int32)], value)
        else:
            raise ProcessingError("Неизвестный инструмент ручного выделения")
    output = np.minimum(output, source_alpha)
    feather = _number(params, "feather", 0, 0, 40)
    if feather > 0:
        output = cv2.GaussianBlur(output, (0, 0), max(0.5, feather / 2.0))
        output = np.minimum(output, source_alpha)
    return output

def _background(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(image)
    action = str(params.get("action", "remove"))
    if action == "remove_color":
        target_mask = _color_mask(rgba[:, :, :3], _hex_rgb(params.get("target_color", "#ffffff")), _number(params, "tolerance", 20, 0, 100))
        mask = _refine_mask(255 - target_mask, params)
    else:
        mask = _build_mask(rgba, params)
    mask = np.minimum(mask, rgba[:, :, 3])
    if action in {"remove", "remove_color"}:
        rgba[:, :, 3] = mask
        return _pil_from_rgba(rgba)
    if action == "replace":
        background = np.empty_like(rgba[:, :, :3])
        background[:, :] = _hex_rgb(params.get("background_color", "#ffffff"))
        weight = (mask.astype(np.float32) / 255.0)[:, :, None]
        rgb = rgba[:, :, :3].astype(np.float32) * weight + background.astype(np.float32) * (1 - weight)
        return _apply_rgb_alpha(rgb, np.full(mask.shape, 255, dtype=np.uint8))
    raise ProcessingError("Неизвестная операция с фоном")


def _remove_small_alpha_islands(alpha: np.ndarray, min_area: int) -> np.ndarray:
    binary = (alpha > 8).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    result = alpha.copy()
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < min_area:
            result[labels == label] = 0
    return result


def _decontaminate_edges(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    edge = (alpha > 0) & (alpha < 245)
    if not np.any(edge):
        return rgba
    mask = np.where(edge, 255, 0).astype(np.uint8)
    inpainted = cv2.inpaint(rgba[:, :, :3], mask, 3, cv2.INPAINT_TELEA)
    rgba[edge, :3] = inpainted[edge]
    return rgba


def _cleanup(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(image)
    if _bool(params, "remove_color", False):
        selected = _color_mask(rgba[:, :, :3], _hex_rgb(params.get("target_color", "#ffffff")), _number(params, "tolerance", 18, 0, 100))
        rgba[:, :, 3] = np.where(selected > 0, 0, rgba[:, :, 3]).astype(np.uint8)
    if _bool(params, "remove_halo", True):
        rgba = _decontaminate_edges(rgba)
    defect = _integer(params, "defect_cleanup", 0, 0, 100)
    if defect:
        kernel = 3 if defect < 70 else 5
        rgba[:, :, :3] = cv2.medianBlur(rgba[:, :, :3], kernel)
        min_area = max(2, int(round(defect * rgba.shape[0] * rgba.shape[1] / 2_000_000)))
        rgba[:, :, 3] = _remove_small_alpha_islands(rgba[:, :, 3], min_area)
    if _bool(params, "binary_alpha", False):
        threshold = _integer(params, "alpha_threshold", 128, 0, 255)
        rgba[:, :, 3] = np.where(rgba[:, :, 3] >= threshold, 255, 0).astype(np.uint8)
    return _pil_from_rgba(rgba)


def _prepare_logo(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(_cleanup(image, {
        "remove_color": _bool(params, "remove_background", True),
        "target_color": params.get("target_color", "#ffffff"),
        "tolerance": params.get("tolerance", 18),
        "remove_halo": True,
        "binary_alpha": _bool(params, "binary_alpha", False),
        "alpha_threshold": params.get("alpha_threshold", 128),
    }))
    visible = rgba[:, :, 3] > 8
    if not np.any(visible):
        raise ProcessingError("После подготовки логотип стал пустым")
    ys, xs = np.where(visible)
    padding = _integer(params, "padding_px", 2, 0, 200)
    x0, x1 = max(0, int(xs.min()) - padding), min(rgba.shape[1], int(xs.max()) + 1 + padding)
    y0, y1 = max(0, int(ys.min()) - padding), min(rgba.shape[0], int(ys.max()) + 1 + padding)
    rgba = rgba[y0:y1, x0:x1].copy()
    color_mode = str(params.get("color_mode", "original")).strip().lower()
    if color_mode not in {"original", "black", "gray"}:
        raise ProcessingError("Цвет логотипа должен быть original, black или gray")
    if color_mode != "original":
        value = 0 if color_mode == "black" else 96
        rgba[:, :, :3][rgba[:, :, 3] > 0] = value
    return _pil_from_rgba(rgba)


def _perspective(image: Image.Image, points: Any) -> Image.Image:
    if not isinstance(points, list) or len(points) != 4:
        raise ProcessingError("Для перспективы требуются четыре точки")
    parsed_percent: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ProcessingError("Каждая точка перспективы должна содержать X и Y")
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError) as exc:
            raise ProcessingError("Координаты перспективы должны быть числами") from exc
        if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 100 or not 0 <= y <= 100:
            raise ProcessingError("Координаты перспективы задаются от 0 до 100 %")
        parsed_percent.append((x, y))
    polygon = np.asarray(parsed_percent, dtype=np.float32)
    if len(np.unique(polygon, axis=0)) != 4:
        raise ProcessingError("Точки перспективы должны быть различными")
    # Required order: TL, TR, BR, BL. Reject self-intersection, concavity and
    # near-zero quadrilaterals before OpenCV can create an unstable transform.
    contour = polygon.reshape((-1, 1, 2))
    area = abs(float(cv2.contourArea(contour)))
    if area < 4.0 or not cv2.isContourConvex(contour):
        raise ProcessingError("Четырёхугольник перспективы вырожден или точки указаны в неверном порядке")
    source = np.asarray([((image.width - 1) * x / 100, (image.height - 1) * y / 100) for x, y in parsed_percent], dtype=np.float32)
    target = np.array([[0, 0], [image.width - 1, 0], [image.width - 1, image.height - 1], [0, image.height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    if not np.isfinite(matrix).all() or abs(float(np.linalg.det(matrix))) < 1e-10:
        raise ProcessingError("Не удалось построить устойчивое преобразование перспективы")
    rgba = cv2.warpPerspective(_rgba_array(image), matrix, image.size, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return _pil_from_rgba(rgba)


def _geometry(image: Image.Image, ppi: float, params: dict[str, Any]) -> tuple[Image.Image, float]:
    out = image
    crop = params.get("crop")
    if isinstance(crop, dict):
        x = _number(crop, "x", 0, 0, 100)
        y = _number(crop, "y", 0, 0, 100)
        width = _number(crop, "width", 100, 0.1, 100)
        height = _number(crop, "height", 100, 0.1, 100)
        box = (
            int(round(out.width * x / 100)), int(round(out.height * y / 100)),
            int(round(out.width * min(100, x + width) / 100)), int(round(out.height * min(100, y + height) / 100)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ProcessingError("Область кадрирования имеет нулевой размер")
        out = out.crop(box)
    if params.get("perspective") is not None:
        out = _perspective(out, params.get("perspective"))
    angle = _number(params, "rotate", 0, -360, 360)
    if abs(angle) > 1e-6:
        out = out.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=_bool(params, "expand", True), fillcolor=(0, 0, 0, 0))
    if _bool(params, "flip_horizontal", False):
        out = ImageOps.mirror(out)
    if _bool(params, "flip_vertical", False):
        out = ImageOps.flip(out)

    target_ppi = _number(params, "ppi", ppi, 100, 1000)
    width_mm = params.get("width_mm")
    height_mm = params.get("height_mm")
    width_present = width_mm is not None and width_mm != ""
    height_present = height_mm is not None and height_mm != ""
    if width_present or height_present:
        preserve = _bool(params, "preserve_aspect", True)
        width_value = _number({"value": width_mm}, "value", 1, 1, 2000) if width_present else None
        height_value = _number({"value": height_mm}, "value", 1, 1, 2000) if height_present else None
        if preserve:
            if width_value is None and height_value is not None:
                width_value = height_value * out.width / out.height
            elif height_value is None and width_value is not None:
                height_value = width_value * out.height / out.width
            elif width_value is not None and height_value is not None:
                height_value = width_value * out.height / out.width
        if width_value is None or height_value is None:
            raise ProcessingError("Укажите ширину или высоту печати")
        target_width = max(1, int(round(width_value / 25.4 * target_ppi)))
        target_height = max(1, int(round(height_value / 25.4 * target_ppi)))
        _check_output_size(target_width, target_height)
        out = out.resize((target_width, target_height), Image.Resampling.LANCZOS)
    return out, target_ppi


def _color(image: Image.Image, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(image)
    alpha = rgba[:, :, 3]
    rgb_image = Image.fromarray(rgba[:, :, :3], "RGB")
    rgb_image = ImageEnhance.Brightness(rgb_image).enhance(_number(params, "brightness", 1.0, 0.2, 2.5))
    rgb_image = ImageEnhance.Contrast(rgb_image).enhance(_number(params, "contrast", 1.0, 0.2, 2.5))
    rgb_image = ImageEnhance.Color(rgb_image).enhance(_number(params, "saturation", 1.0, 0.0, 3.0))
    rgb = np.asarray(rgb_image, dtype=np.uint8).copy()
    hue = _number(params, "hue", 0, -180, 180)
    if abs(hue) > 1e-6:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hsv[:, :, 0] = ((hsv[:, :, 0].astype(np.int16) + int(round(hue / 2))) % 180).astype(np.uint8)
        rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    temperature = _number(params, "temperature", 0, -100, 100)
    if abs(temperature) > 1e-6:
        delta = int(round(temperature * 0.55))
        work = rgb.astype(np.int16)
        work[:, :, 0] += delta
        work[:, :, 2] -= delta
        rgb = np.clip(work, 0, 255).astype(np.uint8)
    return _apply_rgb_alpha(rgb, alpha)


def _bbox_from_alpha(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(alpha > 10)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _master_clean(image: Image.Image) -> Image.Image:
    cleaned = _cleanup(image, {"remove_halo": True, "defect_cleanup": 10})
    return _background(cleaned, {"action": "remove", "mode": "object", "feather": 1})


def _master_dtf(image: Image.Image) -> Image.Image:
    out = _master_clean(image)
    rgba = _rgba_array(out)
    bbox = _bbox_from_alpha(rgba[:, :, 3])
    if bbox:
        x0, y0, x1, y1 = bbox
        out = out.crop((x0, y0, x1, y1))
        pad = max(10, int(round(max(out.size) * 0.04)))
        canvas = Image.new("RGBA", (out.width + pad * 2, out.height + pad * 2), (0, 0, 0, 0))
        canvas.paste(out, (pad, pad), out)
        out = canvas
    return out


def _master_card(image: Image.Image, params: dict[str, Any]) -> tuple[Image.Image, float]:
    width = _integer(params, "width_px", 1200, 300, 6000)
    height = _integer(params, "height_px", 1600, 300, 6000)
    background = _hex_rgb(params.get("background_color", "#ffffff"))
    canvas = Image.new("RGBA", (width, height), (*background, 255))
    work = _background(image, {"action": "remove", "mode": "object", "feather": 1})
    fit_w = int(width * 0.78)
    fit_h = int(height * 0.72)
    work.thumbnail((fit_w, fit_h), Image.Resampling.LANCZOS)
    x = (width - work.width) // 2
    y = int(height * 0.09)
    canvas.paste(work, (x, y), work)
    return canvas, settings.workspace_ppi


def _minimum_halftone_size_mm(image: Image.Image, ppi: float) -> float:
    cell = 2
    while math.ceil(image.width / cell) * math.ceil(image.height / cell) > settings.max_halftone_cells:
        cell += 1
    return cell / max(1.0, ppi) * 25.4


def _halftone(image: Image.Image, ppi: float, params: dict[str, Any]) -> Image.Image:
    rgba = _rgba_array(image)
    source_alpha = rgba[:, :, 3]
    mode = str(params.get("mode", "color")).lower()
    raster = str(params.get("raster", "dot")).lower()
    shape = str(params.get("shape", "circle")).lower()
    if mode not in {"color", "mono"}:
        raise ProcessingError("Режим полутона должен быть color или mono")
    if raster not in {"dot", "line", "hybrid"}:
        raise ProcessingError("Тип растра должен быть dot, line или hybrid")
    if shape not in {"circle", "ellipse", "square", "diamond"}:
        raise ProcessingError("Форма точки должна быть circle, ellipse, square или diamond")

    nominal_mm = _number(params, "size_mm", 0.20, 0.01, 10.0)
    lpi = _number(params, "lpi", 45.0, 5.0, 300.0)
    min_size_mm = _number(params, "min_size_mm", 0.08, 0.01, 10.0)
    max_size_mm = _number(params, "max_size_mm", max(0.40, nominal_mm), 0.01, 20.0)
    if min_size_mm > max_size_mm:
        raise ProcessingError("Минимальный размер точки не может быть больше максимального")
    density = _number(params, "density", 75, 1, 100) / 100.0
    angle = _number(params, "angle", 45.0, -180.0, 180.0)
    alpha_threshold = _integer(params, "alpha_threshold", 8, 0, 255)
    invert = _bool(params, "invert", False)
    foreground = np.array(_hex_rgb(params.get("foreground_color", "#000000")), dtype=np.uint8)

    cell_mm = 25.4 / lpi
    cell = max(2, int(round(cell_mm / 25.4 * ppi)))
    cells_x = math.ceil(image.width / cell)
    cells_y = math.ceil(image.height / cell)
    if cells_x * cells_y > settings.max_halftone_cells:
        raise ProcessingError("LPI создаёт чрезмерное количество полутоновых ячеек")

    rgb_source = rgba[:, :, :3]
    gray = cv2.cvtColor(rgb_source, cv2.COLOR_RGB2GRAY)
    if invert:
        gray = 255 - gray
    canvas = np.zeros_like(rgba)
    angle_rad = math.radians(angle)
    direction = np.array([math.cos(angle_rad), math.sin(angle_rad)], dtype=np.float64)
    normal = np.array([-direction[1], direction[0]], dtype=np.float64)

    for y in range(0, image.height, cell):
        for x in range(0, image.width, cell):
            block = gray[y:y + cell, x:x + cell]
            block_alpha = source_alpha[y:y + cell, x:x + cell]
            valid = block_alpha > alpha_threshold
            if block.size == 0 or not np.any(valid):
                continue
            weights = np.maximum(block_alpha[valid], 1)
            intensity = float(np.average(block[valid], weights=weights)) / 255.0
            strength = float(np.clip((1.0 - intensity) * density, 0.0, 1.0))
            if strength <= 0.01:
                continue
            bh, bw = block.shape
            cx, cy = x + bw // 2, y + bh // 2
            if mode == "color":
                source_block = rgb_source[y:y + bh, x:x + bw]
                color = np.average(source_block[valid], axis=0, weights=weights).astype(np.uint8)
            else:
                color = foreground
            mark = (*[int(v) for v in color], 255)

            requested_mm = nominal_mm * math.sqrt(strength)
            mark_mm = float(np.clip(requested_mm, min_size_mm, max_size_mm))
            mark_px = max(1, int(round(mark_mm / 25.4 * ppi)))
            mark_px = min(mark_px, max(1, min(bh, bw) - 1))

            if raster == "line":
                half = max(1.0, min(bh, bw) * 0.48)
                p1 = (int(round(cx - direction[0] * half)), int(round(cy - direction[1] * half)))
                p2 = (int(round(cx + direction[0] * half)), int(round(cy + direction[1] * half)))
                cv2.line(canvas, p1, p2, mark, max(1, mark_px), lineType=cv2.LINE_AA)
            elif raster == "hybrid" and ((y // cell) + (x // cell)) % 2:
                half = max(1.0, min(bh, bw) * 0.48)
                p1 = (int(round(cx - normal[0] * half)), int(round(cy - normal[1] * half)))
                p2 = (int(round(cx + normal[0] * half)), int(round(cy + normal[1] * half)))
                cv2.line(canvas, p1, p2, mark, max(1, mark_px), lineType=cv2.LINE_AA)
            elif shape == "square":
                half = max(1, mark_px // 2)
                cv2.rectangle(canvas, (cx - half, cy - half), (cx + half, cy + half), mark, -1, lineType=cv2.LINE_AA)
            elif shape == "diamond":
                half = max(1, mark_px // 2)
                points = np.array([[cx, cy-half], [cx+half, cy], [cx, cy+half], [cx-half, cy]], dtype=np.int32)
                rotation = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
                points = cv2.transform(points[None, :, :], rotation)[0].astype(np.int32)
                cv2.fillConvexPoly(canvas, points, mark, lineType=cv2.LINE_AA)
            elif shape == "ellipse":
                axes = (max(1, mark_px // 2), max(1, mark_px // 3))
                cv2.ellipse(canvas, (cx, cy), axes, angle, 0, 360, mark, -1, lineType=cv2.LINE_AA)
            else:
                cv2.circle(canvas, (cx, cy), max(1, mark_px // 2), mark, -1, lineType=cv2.LINE_AA)

    canvas[:, :, 3] = np.minimum(canvas[:, :, 3], source_alpha)
    mark_coverage = float(np.count_nonzero(canvas[:, :, 3] > alpha_threshold)) / float(canvas.shape[0] * canvas.shape[1])
    if mark_coverage < 0.0005:
        raise ProcessingError("Полутон не содержит достаточного количества печатных элементов")
    if mark_coverage > 0.92:
        raise ProcessingError("Полутон превратился в почти сплошную заливку")
    return _pil_from_rgba(canvas)


def _simplify_contour(points: np.ndarray, epsilon: float) -> np.ndarray:
    if len(points) < 3:
        return points
    return cv2.approxPolyDP(points, epsilon, True)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _vectorize_with_diagnostics(image: Image.Image, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    original_width, original_height = image.size
    vector_scale = 1.0
    vector_work_pixels = min(settings.max_vector_pixels, 1_500_000)
    if image.width * image.height > vector_work_pixels:
        vector_scale = math.sqrt(vector_work_pixels / float(image.width * image.height))
        target = (max(32, int(round(image.width * vector_scale))), max(32, int(round(image.height * vector_scale))))
        image = image.resize(target, Image.Resampling.LANCZOS)

    rgba = _rgba_array(image)
    alpha = rgba[:, :, 3]
    visible = alpha > 16
    visible_count = int(visible.sum())
    if visible_count < 3:
        raise ProcessingError("В изображении нет видимой области для векторизации")

    mode = str(params.get("mode", "color")).lower()
    if mode not in {"color", "mono"}:
        raise ProcessingError("Режим векторизации должен быть color или mono")
    colors_count = _integer(params, "colors", 6, 2, 16)
    tolerance = _number(params, "simplify", 2.0, 0.1, 20.0) * vector_scale
    min_area = _number(params, "min_area", 12, 1, 100000) * vector_scale * vector_scale
    optimize = _bool(params, "optimize", True)
    rgb = rgba[:, :, :3]
    filtered = cv2.bilateralFilter(rgb, 5, 24, 18) if optimize and min(image.size) >= 24 else rgb
    max_paths = 8000
    max_svg_bytes = 25 * 1024 * 1024

    label_map = np.full(alpha.shape, -1, dtype=np.int16)
    centers_rgb: list[np.ndarray] = []
    expected_masks: list[np.ndarray] = []

    if mode == "mono":
        gray = cv2.cvtColor(filtered, cv2.COLOR_RGB2GRAY)
        values = gray[visible]
        threshold, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        target_mask = visible & (gray <= float(threshold))
        # A transparent or isolated coloured object can contain no dark pixels.
        # In mono mode its visible silhouette is still a valid black vector target.
        if int(target_mask.sum()) < 3:
            target_mask = visible.copy()
        label_map[target_mask] = 0
        centers_rgb = [np.asarray([0, 0, 0], dtype=np.uint8)]
        expected_masks = [target_mask]
    else:
        visible_pixels_rgb = filtered[visible].astype(np.float32)
        visible_pixels_lab = cv2.cvtColor(filtered, cv2.COLOR_RGB2LAB)[visible].astype(np.float32)
        if visible_pixels_lab.shape[0] > 250_000:
            rng = np.random.default_rng(20260724)
            indices = rng.choice(visible_pixels_lab.shape[0], 250_000, replace=False)
            sample = visible_pixels_lab[indices]
        else:
            sample = visible_pixels_lab
        unique_count = len(np.unique(sample.astype(np.uint8), axis=0))
        actual_colors = min(colors_count, max(1, unique_count))
        cv2.setRNGSeed(20260724)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.35)
        _, _, centers_lab = cv2.kmeans(sample, actual_colors, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
        distances = np.linalg.norm(visible_pixels_lab[:, None, :] - centers_lab[None, :, :], axis=2)
        labels_visible = distances.argmin(axis=1)
        label_map[visible] = labels_visible
        for index in range(actual_colors):
            members = visible_pixels_rgb[labels_visible == index]
            centre = np.median(members, axis=0) if len(members) else np.asarray([0, 0, 0])
            centers_rgb.append(np.clip(centre, 0, 255).astype(np.uint8))
            expected_masks.append(label_map == index)

    cluster_order = sorted(range(len(expected_masks)), key=lambda i: int(expected_masks[i].sum()), reverse=True)
    path_parts: list[str] = []
    reconstructed = np.zeros_like(rgb)
    reconstructed_visible = np.zeros(alpha.shape, dtype=bool)
    path_count = 0
    cluster_ious: list[float] = []

    def clean_mask(mask_bool: np.ndarray) -> np.ndarray:
        mask = np.where(mask_bool, 255, 0).astype(np.uint8)
        if optimize:
            # Sparse monochrome halftones often contain legitimate 1–2 px marks.
            # A generic opening pass deletes them all, producing an empty SVG.
            if mode != "mono":
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
        cleaned = np.zeros_like(mask)
        for label in range(1, count):
            if float(stats[label, cv2.CC_STAT_AREA]) >= min_area:
                cleaned[labels == label] = 255
        return cleaned

    for cluster_index in cluster_order:
        expected = expected_masks[cluster_index]
        cleaned = clean_mask(expected)
        contours, hierarchy = cv2.findContours(cleaned, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:
            cluster_ious.append(0.0)
            continue
        rendered = np.zeros_like(cleaned)
        fill = _rgb_to_hex(tuple(int(v) for v in centers_rgb[cluster_index]))
        for index, contour in enumerate(contours):
            if hierarchy[0][index][3] != -1 or abs(cv2.contourArea(contour)) < min_area:
                continue
            components: list[np.ndarray] = []
            outer = _simplify_contour(contour, tolerance)
            if len(outer) < 3:
                outer = _simplify_contour(contour, max(0.1, tolerance * 0.25))
            if len(outer) < 3:
                continue
            components.append(outer)
            child = hierarchy[0][index][2]
            while child != -1:
                hole = _simplify_contour(contours[child], tolerance)
                if len(hole) >= 3:
                    components.append(hole)
                child = hierarchy[0][child][0]
            commands: list[str] = []
            for component in components:
                pts = component[:, 0, :]
                commands.extend([f"M {int(pts[0,0])} {int(pts[0,1])}"] + [f"L {int(x)} {int(y)}" for x, y in pts[1:]] + ["Z"])
            if not commands:
                continue
            path_parts.append(f'<path d="{" ".join(commands)}" fill="{fill}" fill-rule="evenodd"/>')
            path_count += 1
            cv2.drawContours(rendered, [components[0]], -1, 255, thickness=-1)
            for hole in components[1:]:
                cv2.drawContours(rendered, [hole], -1, 0, thickness=-1)
            if path_count > max_paths:
                raise ProcessingError("Векторизация создала слишком много контуров; увеличьте допуск контура")
        rendered_bool = rendered > 0

        # Preserve thin strokes and tiny colour islands that morphology or polygon
        # simplification can legitimately omit.  Do not lower the fidelity gate:
        # encode only the still-missing target pixels as deterministic horizontal
        # pixel runs.  Multiple runs are grouped into one SVG path so the fallback
        # remains bounded by the path and byte limits.
        missing_mask = expected & ~rendered_bool
        missing_count = int(np.count_nonzero(missing_mask))
        if missing_count:
            run_commands: list[str] = []
            run_count = 0
            chunk_runs = 256
            for y in range(missing_mask.shape[0]):
                row = missing_mask[y]
                padded = np.pad(row.astype(np.int8), (1, 1), constant_values=0)
                changes = np.diff(padded)
                starts = np.flatnonzero(changes == 1)
                ends = np.flatnonzero(changes == -1)
                for x0, x1 in zip(starts, ends, strict=True):
                    run_commands.append(
                        f"M {int(x0)} {y} H {int(x1)} V {y + 1} H {int(x0)} Z"
                    )
                    run_count += 1
                    if run_count % chunk_runs == 0:
                        path_parts.append(
                            f'<path d="{" ".join(run_commands)}" fill="{fill}"/>'
                        )
                        path_count += 1
                        run_commands = []
                        if path_count > max_paths:
                            raise ProcessingError(
                                "Векторизация создала слишком много контуров; увеличьте допуск контура"
                            )
            if run_commands:
                path_parts.append(f'<path d="{" ".join(run_commands)}" fill="{fill}"/>')
                path_count += 1
                if path_count > max_paths:
                    raise ProcessingError(
                        "Векторизация создала слишком много контуров; увеличьте допуск контура"
                    )
            rendered[missing_mask] = 255
            rendered_bool = rendered > 0

        union = int(np.count_nonzero(rendered_bool | expected))
        intersection = int(np.count_nonzero(rendered_bool & expected))
        cluster_ious.append(intersection / max(1, union))
        reconstructed[rendered_bool] = centers_rgb[cluster_index]
        reconstructed_visible |= rendered_bool

    if not path_parts:
        raise ProcessingError("Векторизация не создала пригодных контуров")

    if mode == "color":
        # Ignore very soft alpha fringe in fidelity scoring; SVG paths cannot
        # reproduce raster antialiasing pixel-for-pixel, while the opaque artwork
        # must still remain covered.
        target_visible = alpha > 64
        if int(target_visible.sum()) < 3:
            target_visible = visible
        coverage = float(np.count_nonzero(reconstructed_visible & target_visible)) / float(max(1, np.count_nonzero(target_visible)))
        source_values = rgb[target_visible].astype(np.float32)
        reconstructed_values = reconstructed[target_visible].astype(np.float32)
        missing = ~reconstructed_visible[target_visible]
        reconstructed_values[missing] = 255.0
        mae = float(np.mean(np.abs(source_values - reconstructed_values))) / 255.0
        minimum_iou = float(min(cluster_ious)) if cluster_ious else 0.0
        quality = float(np.clip(1.0 - mae * 0.72 - (1.0 - coverage) * 0.58, 0.0, 1.0))
        # Coverage and colour fidelity are evaluated together. A flat artwork can
        # legitimately lose a narrow antialiased fringe while retaining high visual
        # fidelity. Gross subject loss is still blocked.
        coverage_floor = 0.84 if quality >= 0.78 else 0.90
        if coverage < coverage_floor or quality < 0.64:
            raise ProcessingError(
                f"Векторизация заблокирована: визуальная точность недостаточна "
                f"(покрытие {coverage:.1%}, качество {quality:.1%}, "
                f"минимум покрытия {coverage_floor:.0%}). Увеличьте число цветов, "
                "уменьшите допуск или сначала очистите фон."
            )
    else:
        target_visible = expected_masks[0]
        rendered_visible = reconstructed_visible
        union = int(np.count_nonzero(target_visible | rendered_visible))
        intersection = int(np.count_nonzero(target_visible & rendered_visible))
        coverage = intersection / max(1, int(np.count_nonzero(target_visible)))
        minimum_iou = intersection / max(1, union)
        mae = 0.0
        quality = minimum_iou
        if minimum_iou < 0.72:
            raise ProcessingError(f"Монохромная векторизация заблокирована: IoU контуров {minimum_iou:.1%}")

    paths = "".join(path_parts)
    if vector_scale < 1.0:
        sx = original_width / float(image.width)
        sy = original_height / float(image.height)
        paths = f'<g transform="scale({sx:.8f} {sy:.8f})">{paths}</g>'
    svg = f'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="{original_width}px" height="{original_height}px" viewBox="0 0 {original_width} {original_height}">{paths}</svg>'
    encoded_size = len(svg.encode("utf-8"))
    if encoded_size > max_svg_bytes:
        raise ProcessingError("SVG превышает безопасный лимит размера")
    diagnostics = {
        "input_policy": "exact_selected_asset_no_auto_segmentation",
        "original_size_px": [original_width, original_height],
        "working_size_px": [image.width, image.height],
        "auto_downscaled": vector_scale < 1.0,
        "path_count": path_count,
        "coverage_ratio": round(coverage, 6),
        "normalized_mae": round(mae, 6),
        "minimum_cluster_iou": round(minimum_iou, 6),
        "quality_score": round(quality, 6),
        "svg_size_bytes": encoded_size,
    }
    return svg, diagnostics


def _vectorize(image: Image.Image, params: dict[str, Any]) -> str:
    svg, _ = _vectorize_with_diagnostics(image, params)
    return svg


def _mask_image(image: Image.Image, mask: np.ndarray) -> Image.Image:
    rgba = _rgba_array(image)
    if mask.shape != rgba.shape[:2]:
        mask = cv2.resize(mask, (rgba.shape[1], rgba.shape[0]), interpolation=cv2.INTER_LINEAR)
    rgba[:, :, 3] = np.minimum(mask.astype(np.uint8), rgba[:, :, 3])
    return _pil_from_rgba(rgba)


def _crop_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    rgba = _rgba_array(image)
    bbox = _bbox_from_alpha(rgba[:, :, 3])
    if not bbox:
        return image
    x0, y0, x1, y1 = bbox
    return image.crop((max(0, x0 - padding), max(0, y0 - padding), min(image.width, x1 + padding), min(image.height, y1 + padding)))


def _ai_extract_print(image: Image.Image, params: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    engine = get_ai_engine()
    region, region_box = _extract_region(image, params)
    if params.get("perspective") is not None:
        region = _perspective(region, params.get("perspective"))
    threshold = float(np.clip(0.70 - _number(params, "sensitivity", 58, 0, 100) * 0.004, 0.28, 0.68))
    mask, ai = engine.segment_print(region, threshold=threshold, feather=_number(params, "feather", 1, 0, 20), module="extract")
    support, support_diagnostics = _graphic_support_mask(region, params) if str(params.get("mode", "auto")) == "auto" else (None, {"reason": "manual_region"})
    if support is not None:
        ai_binary = mask > 16
        support_binary = support > 16
        overlap = float(np.count_nonzero(ai_binary & support_binary)) / float(max(1, np.count_nonzero(support_binary)))
        contamination = float(np.count_nonzero(ai_binary & ~support_binary)) / float(max(1, np.count_nonzero(ai_binary)))
        # The AI mask remains part of the evidence, while the coherent graphic
        # support prevents background structures and the whole garment from being
        # emitted as print. Recover dark ink enclosed by coloured/bright pigment.
        mask = support
        ai.setdefault("details", {})["graphic_support"] = support_diagnostics
        ai["details"]["ai_support_overlap"] = round(overlap, 6)
        ai["details"]["ai_contamination_ratio"] = round(contamination, 6)
        ai["details"]["mask_fusion"] = "subject_constrained_graphic_support"
    else:
        ai.setdefault("details", {})["graphic_support"] = support_diagnostics
    coverage = float((mask > 16).mean())
    if coverage < 0.002:
        # Region mode and non-garment graphics can be outside the pixel model's
        # training distribution. Keep AI evidence but fall back to the verified
        # deterministic fabric-distance extractor instead of returning a false stop.
        fallback_result, fallback_diagnostics = _extract_print(image, params)
        preflight = engine.preflight(fallback_result, "extract_print", module="extract")
        ai["details"]["fallback"] = "deterministic_fabric_distance"
        ai["details"]["fallback_diagnostics"] = fallback_diagnostics
        ai["preflight"] = preflight
        if not preflight["details"]["passed"]:
            raise ProcessingError("Принт не обнаружен: AI и резервный алгоритм не создали пригодный результат")
        return fallback_result, ai
    if coverage > 0.88:
        raise ProcessingError("AI-маска захватила почти всё изделие. Укажите область принта")
    rgba = _rgba_array(region)
    rgb = rgba[:, :, :3]
    if _bool(params, "reduce_fabric_texture", True):
        strength = _number(params, "texture_reduction", 35, 0, 100) / 100.0
        # Texture suppression is intentionally bounded and thread-safe. Running
        # the full restoration convolution over a multi-megapixel garment before
        # another ASGI inference could leave some OpenCV builds stalled. The AI
        # model still selects the restoration profile; a conservative Pillow
        # median pass is blended only inside the accepted print mask.
        restoration_ai = engine.recommend_restoration(region, module="extract")
        filtered = region.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
        restored_rgb = np.asarray(filtered, dtype=np.uint8)
        weight = (mask.astype(np.float32) / 255.0 * min(0.65, strength))[:, :, None]
        rgb = np.clip(rgb.astype(np.float32) * (1.0 - weight) + restored_rgb.astype(np.float32) * weight, 0, 255).astype(np.uint8)
        restoration_ai.setdefault("details", {})["applied_method"] = "masked_pillow_median3"
        restoration_ai["details"]["applied_strength"] = min(0.65, strength)
        ai["texture_restoration"] = restoration_ai
    result = _apply_rgb_alpha(rgb, mask)
    if _bool(params, "crop_output", True):
        result = _crop_alpha(result, _integer(params, "padding", 8, 0, 200))
    preflight = engine.preflight(result, "extract_print", module="extract")
    ai["preflight"] = preflight
    ai["details"]["region_box_px"] = list(region_box)
    if not preflight["details"]["passed"]:
        raise ProcessingError("AI-проверка заблокировала непригодный результат извлечения принта")
    return result, ai


def _clean_subject_mask(image: Image.Image, mask: np.ndarray, *, feather: float) -> tuple[np.ndarray, dict[str, Any]]:
    """Remove disconnected islands and background-coloured boundary contamination.

    The correction is deliberately conservative: colour decontamination is only
    enabled when the image border is sufficiently coherent to act as a background
    sample. The largest connected component is always retained.
    """
    rgba = _rgba_array(image)
    source_alpha = rgba[:, :, 3]
    binary = np.where((mask > 16) & (source_alpha > 8), 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        binary = np.where(labels == largest, 255, 0).astype(np.uint8)
    h, w = binary.shape
    frame_width = max(2, int(round(min(h, w) * 0.025)))
    frame = np.zeros((h, w), dtype=bool)
    frame[:frame_width, :] = True; frame[-frame_width:, :] = True
    frame[:, :frame_width] = True; frame[:, -frame_width:] = True
    frame &= source_alpha > 8
    lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    samples = lab[frame]
    removed = 0
    border_spread = None
    threshold = None
    if samples.shape[0] >= 40:
        centre = np.median(samples, axis=0)
        sample_distance = np.linalg.norm(samples - centre[None, :], axis=1)
        border_spread = float(np.percentile(sample_distance, 90))
        if border_spread <= 20.0:
            distance = np.linalg.norm(lab - centre[None, None, :], axis=2)
            threshold = float(np.clip(np.percentile(sample_distance, 99) + 4.0, 7.0, 24.0))
            radius = max(1, int(round(min(h, w) * 0.006)))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
            interior = cv2.erode(binary, kernel, iterations=1) > 0
            boundary = (binary > 0) & ~interior
            contaminated = boundary & (distance <= threshold)
            removed = int(np.count_nonzero(contaminated))
            binary[contaminated] = 0
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
            count, labels, stats, _ = cv2.connectedComponentsWithStats((binary > 0).astype(np.uint8), 8)
            if count > 1:
                largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                binary = np.where(labels == largest, 255, 0).astype(np.uint8)
    output = binary
    if feather > 0:
        output = cv2.GaussianBlur(output, (0, 0), max(0.35, feather / 2.0))
    output = np.minimum(output, source_alpha)
    return output, {
        "largest_component_enforced": True,
        "boundary_background_pixels_removed": removed,
        "border_color_spread": None if border_spread is None else round(border_spread, 4),
        "boundary_color_threshold": None if threshold is None else round(threshold, 4),
        "coverage_ratio_after_cleanup": round(float((output > 16).mean()), 6),
    }



def _border_connected_subject_mask(image: Image.Image) -> tuple[np.ndarray, dict[str, Any]]:
    """Estimate the foreground by removing only background-like pixels connected to the frame.

    Border colours are clustered in Lab so a textured/gradient studio background can
    use more than one representative colour. Interior pixels with similar colour are
    not removed unless they are connected to the image frame.
    """
    rgba = _rgba_array(image)
    original_h, original_w = rgba.shape[:2]
    scale = min(1.0, 1000.0 / max(original_w, original_h))
    if scale < 1.0:
        w = max(32, int(round(original_w * scale)))
        h = max(32, int(round(original_h * scale)))
        rgb = cv2.resize(rgba[:, :, :3], (w, h), interpolation=cv2.INTER_AREA)
        source_alpha = cv2.resize(rgba[:, :, 3], (w, h), interpolation=cv2.INTER_AREA)
    else:
        rgb = rgba[:, :, :3]
        source_alpha = rgba[:, :, 3]
        h, w = source_alpha.shape
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    border = max(2, int(round(min(h, w) * 0.035)))
    frame = np.zeros((h, w), dtype=bool)
    frame[:border, :] = True; frame[-border:, :] = True
    frame[:, :border] = True; frame[:, -border:] = True
    frame &= source_alpha > 8
    samples = lab[frame]
    if samples.shape[0] < 40:
        raise ProcessingError("Недостаточно пикселей рамки для определения фона")
    if samples.shape[0] > 80_000:
        rng = np.random.default_rng(20260724)
        samples = samples[rng.choice(samples.shape[0], 80_000, replace=False)]
    clusters = min(4, max(1, len(np.unique(samples.astype(np.uint8), axis=0)) // 16 + 1))
    cv2.setRNGSeed(20260724)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centers = cv2.kmeans(samples, clusters, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    distances = np.linalg.norm(lab[:, :, None, :] - centers[None, None, :, :], axis=3)
    nearest = distances.min(axis=2)
    sample_nearest = np.linalg.norm(samples - centers[labels.reshape(-1)], axis=1)
    threshold = float(np.clip(np.percentile(sample_nearest, 97.5) + 5.0, 9.0, 34.0))
    background_like = (nearest <= threshold) & (source_alpha > 8)
    # Retain only background-like connected components that touch the frame.
    count, component_labels, _, _ = cv2.connectedComponentsWithStats(background_like.astype(np.uint8), 8)
    touching = set(int(v) for v in np.unique(component_labels[frame]))
    touching.discard(0)
    background = np.isin(component_labels, list(touching)) if touching else np.zeros_like(background_like)
    subject = (~background) & (source_alpha > 8)
    raw = np.where(subject, 255, 0).astype(np.uint8)
    raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    # Remove tiny islands, retain the largest central component and meaningful nearby parts.
    count, component_labels, stats, centers_xy = cv2.connectedComponentsWithStats((raw > 0).astype(np.uint8), 8)
    if count <= 1:
        return np.zeros((original_h, original_w), dtype=np.uint8), {"method": "border_connected_lab", "coverage_ratio": 0.0}
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    largest_box = stats[largest, :4]
    lx, ly, lw, lh = [int(v) for v in largest_box]
    keep = {largest}
    minimum_part = max(16, int(h * w * 0.0015))
    margin = max(4, int(round(max(lw, lh) * 0.12)))
    for idx in range(1, count):
        if idx == largest or int(stats[idx, cv2.CC_STAT_AREA]) < minimum_part:
            continue
        cx, cy = centers_xy[idx]
        if lx - margin <= cx <= lx + lw + margin and ly - margin <= cy <= ly + lh + margin:
            keep.add(idx)
    raw = np.where(np.isin(component_labels, list(keep)), 255, 0).astype(np.uint8)
    if scale < 1.0:
        raw = cv2.resize(raw, (original_w, original_h), interpolation=cv2.INTER_LINEAR)
    raw = np.minimum(raw, rgba[:, :, 3])
    return raw, {
        "method": "border_connected_lab",
        "clusters": clusters,
        "distance_threshold": round(threshold, 4),
        "coverage_ratio": round(float((raw > 16).mean()), 6),
        "components_kept": len(keep),
        "inference_size": [w, h],
    }


def _subject_mask_quality(image: Image.Image, mask: np.ndarray) -> dict[str, float]:
    binary = mask > 16
    h, w = binary.shape
    selected = int(binary.sum())
    if selected == 0:
        return {"score": 0.0, "coverage": 0.0, "border_ratio": 1.0, "center_ratio": 0.0, "edge_alignment": 0.0}
    coverage = selected / float(h * w)
    frame_width = max(1, int(round(min(h, w) * 0.02)))
    frame = np.zeros_like(binary)
    frame[:frame_width, :] = True; frame[-frame_width:, :] = True
    frame[:, :frame_width] = True; frame[:, -frame_width:] = True
    border_ratio = float((binary & frame).sum()) / selected
    centre = np.zeros_like(binary)
    centre[int(h * 0.28):max(int(h * 0.28) + 1, int(h * 0.72)), int(w * 0.28):max(int(w * 0.28) + 1, int(w * 0.72))] = True
    center_ratio = float((binary & centre).sum()) / max(1, int(centre.sum()))
    gray = cv2.cvtColor(_rgba_array(image)[:, :, :3], cv2.COLOR_RGB2GRAY)
    gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    boundary = cv2.morphologyEx(binary.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    edge_alignment = float(np.mean(gradient[boundary]) / max(1.0, np.mean(gradient))) if np.any(boundary) else 0.0
    coverage_penalty = 0.0
    if coverage < 0.03:
        coverage_penalty = (0.03 - coverage) * 8.0
    elif coverage > 0.94:
        coverage_penalty = (coverage - 0.94) * 10.0
    score = 0.48 + min(0.26, center_ratio * 0.34) + min(0.20, edge_alignment * 0.055) - border_ratio * 2.8 - coverage_penalty
    return {
        "score": round(float(np.clip(score, 0.0, 1.0)), 6),
        "coverage": round(coverage, 6),
        "border_ratio": round(border_ratio, 6),
        "center_ratio": round(center_ratio, 6),
        "edge_alignment": round(edge_alignment, 6),
    }

def _ai_subject_result(image: Image.Image, params: dict[str, Any], *, module: str) -> tuple[Image.Image, dict[str, Any]]:
    engine = get_ai_engine()
    sensitivity = _number(params, "ai_sensitivity", 55, 0, 100)
    threshold = float(np.clip(0.72 - sensitivity * 0.004, 0.30, 0.68))
    feather = _number(params, "feather", 2, 0, 40)
    learned_mask, ai = engine.segment_subject(image, threshold=threshold, feather=0.0, module=module)
    learned_mask, learned_cleanup = _clean_subject_mask(image, learned_mask, feather=0.0)
    candidates: list[tuple[str, np.ndarray, dict[str, Any]]] = [("learned", learned_mask, {"cleanup": learned_cleanup})]
    source_alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
    if float((source_alpha > 16).mean()) > 0.98:
        try:
            border_mask, border_details = _border_connected_subject_mask(image)
            border_mask, border_cleanup = _clean_subject_mask(image, border_mask, feather=0.0)
            candidates.append(("border_connected", border_mask, {"segmentation": border_details, "cleanup": border_cleanup}))
            # Candidate unions/intersections allow the learned contour to recover
            # subject details while the border-connected mask removes obvious frame background.
            candidates.append(("union", cv2.bitwise_or(learned_mask, border_mask), {}))
            candidates.append(("intersection", cv2.bitwise_and(learned_mask, border_mask), {}))
        except (ProcessingError, cv2.error, ValueError) as exc:
            ai.setdefault("details", {})["border_connected_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    scored: list[tuple[float, str, np.ndarray, dict[str, Any], dict[str, float]]] = []
    for name, candidate, details in candidates:
        cleaned, final_cleanup = _clean_subject_mask(image, candidate, feather=0.0)
        quality = _subject_mask_quality(image, cleaned)
        details = {**details, "final_cleanup": final_cleanup}
        scored.append((quality["score"], name, cleaned, details, quality))
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_name, mask, best_details, best_quality = scored[0]
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), max(0.35, feather / 2.0))
    mask = np.minimum(mask, source_alpha)
    coverage = float((mask > 16).mean())
    if coverage < 0.005 or coverage > 0.97 or best_score < 0.38:
        raise ProcessingError("Не удалось построить безопасную маску объекта; используйте ручное выделение")
    result = _mask_image(image, mask)
    preflight = engine.preflight(result, "background", module=module)
    ai["preflight"] = preflight
    ai.setdefault("details", {})["hybrid_selection"] = {
        "selected": best_name,
        "quality": best_quality,
        "details": best_details,
        "candidates": [{"name": name, "quality": quality} for _, name, _, _, quality in scored],
    }
    if not preflight["details"]["passed"] or best_quality["border_ratio"] > 0.08:
        raise ProcessingError("Проверка заблокировала ошибочную маску фона")
    return result, ai


def process_image(asset: AssetRecord, operation: str, params: dict[str, Any]) -> AssetRecord:
    normalized = operation.strip().lower()
    engine = get_ai_engine()
    image, ppi = _load_rgba(asset)
    if image.width * image.height > settings.max_processing_pixels:
        raise ProcessingError("Изображение превышает безопасный лимит обработки; предварительно уменьшите его")
    recorded = dict(params)
    recorded["input_asset_id"] = asset.id
    recorded["input_operation"] = asset.operation or "upload"
    recorded["input_width_px"] = image.width
    recorded["input_height_px"] = image.height
    recorded["input_ppi"] = round(float(ppi), 4)

    if normalized == "enhance":
        restored, ai = engine.restore(image, scale=1, strength=None, module="improve")
        result = _enhance(restored, params)
        result, ppi = _apply_physical_target(result, recorded, ppi)
        ai["deterministic_postprocess"] = "brightness/contrast/saturation/sharpness"
        recorded["physical_size_unit"] = "mm"
        recorded["ppi_range"] = [100, 1000]
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "reconstruct":
        scale = _integer(params, "scale", 2, 1, 4)
        result, ai = engine.restore(image, scale=scale, strength=None, module="improve")
        detail = _integer(params, "detail", 45, 0, 100)
        if detail:
            result = ImageEnhance.Sharpness(result).enhance(1 + detail / 160)
        result, ppi = _apply_physical_target(result, recorded, ppi)
        recorded["physical_size_unit"] = "mm"
        recorded["ppi_range"] = [100, 1000]
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "extract_print":
        if _provided(params.get("padding_mm")):
            padding_mm = _number(params, "padding_mm", 2.0, 0.0, 50.0)
            recorded["padding_mm"] = padding_mm
            recorded["padding"] = int(round(padding_mm / 25.4 * ppi))
        result, ai = _ai_extract_print(image, recorded)
        recorded["diagnostics"] = ai.get("details", {})
        recorded["physical_size_unit"] = "mm"
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "select":
        mode = str(params.get("mode", "object"))
        if _provided(params.get("grow_mm")):
            grow_mm = _number(params, "grow_mm", 0, -50, 50)
            recorded["grow"] = grow_mm / 25.4 * ppi
            recorded["grow_mm"] = grow_mm
            recorded["grow_px_derived"] = recorded["grow"]
        source_alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
        ai_auto = _bool(params, "ai_auto", True)
        if mode == "object" and ai_auto:
            base_result, ai = _ai_subject_result(image, recorded, module="selection")
            mask = np.asarray(base_result.getchannel("A"), dtype=np.uint8)
        elif mode == "print" and ai_auto:
            mask, ai = engine.segment_print(image, threshold=0.48, feather=_number(params, "feather", 2, 0, 40), module="selection")
        elif mode in {"color", "rect"}:
            fallback = dict(recorded)
            fallback["mode"] = mode
            mask = _build_mask(_rgba_array(image), fallback)
            ai = engine.analyze(image, module="selection")
            ai.setdefault("details", {})["assistance"] = f"deterministic_{mode}_mask"
        elif mode == "element":
            if isinstance(params.get("manual_edits"), list) and params.get("manual_edits"):
                mask = np.zeros(source_alpha.shape, dtype=np.uint8)
            else:
                fallback = dict(recorded)
                fallback["mode"] = "rect"
                mask = _build_mask(_rgba_array(image), fallback)
            ai = engine.analyze(image, module="selection")
            ai.setdefault("details", {})["assistance"] = "manual_element_mask"
        else:
            mask = np.zeros(source_alpha.shape, dtype=np.uint8)
            ai = engine.analyze(image, module="selection")
            ai.setdefault("details", {})["assistance"] = "manual_mask_without_ai_seed"
        if recorded.get("grow") not in {None, 0, 0.0}:
            mask = _refine_mask(mask, {"grow": recorded["grow"], "feather": 0})
        mask = _manual_mask_edits(mask, recorded, ppi=ppi, source_alpha=source_alpha)
        coverage = float((mask > 16).mean())
        if coverage < 0.001:
            raise ProcessingError("Выделение пустое")
        if coverage > 0.985:
            raise ProcessingError("Выделение захватывает почти всё изображение")
        result = _mask_image(image, mask)
        preflight_operation = "extract_print" if mode == "print" else "background"
        preflight = engine.preflight(result, preflight_operation, module="selection")
        ai["preflight"] = preflight
        ai.setdefault("details", {})["manual_edits_count"] = len(recorded.get("manual_edits") or [])
        ai["details"]["brush_mm"] = float(recorded.get("brush_mm", 5.0))
        if not preflight["details"]["passed"]:
            raise ProcessingError("AI-QA заблокировал непригодное выделение")
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "background":
        action = str(params.get("action", "remove"))
        if action == "remove":
            result, ai = _ai_subject_result(image, params, module="cleanup")
            recorded["diagnostics"] = ai.get("details", {})
        elif action == "replace":
            transparent, ai = _ai_subject_result(image, params, module="cleanup")
            rgba = _rgba_array(transparent)
            background = np.empty_like(rgba[:, :, :3])
            background[:] = _hex_rgb(params.get("background_color", "#ffffff"))
            weight = rgba[:, :, 3:4].astype(np.float32) / 255.0
            rgb = rgba[:, :, :3].astype(np.float32) * weight + background.astype(np.float32) * (1.0 - weight)
            result = _apply_rgb_alpha(rgb, np.full(rgba.shape[:2], 255, dtype=np.uint8))
        else:
            result = _background(image, params)
            ai = engine.analyze(result, module="cleanup")
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "cleanup":
        working = image
        ai_chain: dict[str, Any] = {}
        if _bool(params, "remove_background", False):
            working, ai_chain["background"] = _ai_subject_result(working, params, module="cleanup")
        result = _cleanup(working, params)
        if _bool(params, "defect_cleanup", False) or _integer(params, "defect_cleanup", 0, 0, 100) > 0:
            result, ai_chain["restoration"] = engine.restore(result, scale=1, strength=0.35, module="cleanup")
        ai_chain["analysis"] = engine.analyze(result, module="cleanup")
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai_chain)

    if normalized == "logo":
        result = _prepare_logo(image, params)
        ai = engine.analyze(result, module="cleanup")
        recorded["workflow"] = "logo_prepare"
        recorded["color_mode"] = str(params.get("color_mode", "original")).strip().lower()
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "geometry":
        ai = engine.recommend_size(image, module="geometry")
        if _bool(params, "ai_auto_crop", False):
            margins = ai["details"]["safe_margins"]
            recorded["crop"] = {
                "x": margins["left"] * 100,
                "y": margins["top"] * 100,
                "width": (1.0 - margins["left"] - margins["right"]) * 100,
                "height": (1.0 - margins["top"] - margins["bottom"]) * 100,
            }
        result, ppi = _geometry(image, ppi, recorded)
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "color":
        result = _color(image, params)
        ai = engine.analyze(result, module="improve")
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "halftone":
        ai = engine.recommend_halftone(image, module="halftone")
        if _bool(params, "ai_auto", True):
            if not _provided(params.get("raster")):
                recorded["raster"] = ai["details"]["raster"]
            if not _provided(params.get("size_mm")):
                recorded["size_mm"] = ai["details"]["size_mm"]
            if not _provided(params.get("density")):
                recorded["density"] = ai["details"]["density"]
        safe_cell_mm = _minimum_halftone_size_mm(image, ppi)
        max_safe_lpi = max(5.0, min(300.0, 25.4 / max(safe_cell_mm, 1e-6)))
        requested_lpi = _number(recorded, "lpi", 45.0, 5.0, 300.0)
        recorded["lpi"] = round(min(requested_lpi, max_safe_lpi), 4)
        requested_size = _number(recorded, "size_mm", 0.2, 0.01, 10.0)
        minimum_size = _number(recorded, "min_size_mm", 0.08, 0.01, 10.0)
        maximum_size = _number(recorded, "max_size_mm", max(0.4, requested_size), 0.01, 20.0)
        if minimum_size > maximum_size:
            raise ProcessingError("Минимальный размер точки не может быть больше максимального")
        recorded["size_mm"] = round(float(np.clip(requested_size, minimum_size, maximum_size)), 4)
        recorded["min_size_mm"] = round(minimum_size, 4)
        recorded["max_size_mm"] = round(maximum_size, 4)
        recorded["validator_min_cell_mm"] = round(safe_cell_mm, 4)
        recorded["validator_min_size_mm"] = round(safe_cell_mm, 4)
        recorded["validator_max_lpi"] = round(max_safe_lpi, 4)
        recorded["physical_size_unit"] = "mm"
        ai["details"].update({
            "validator_min_cell_mm": round(safe_cell_mm, 4),
            "validator_max_lpi": round(max_safe_lpi, 4),
            "final_size_mm": recorded["size_mm"],
            "final_lpi": recorded["lpi"],
        })
        result = _halftone(image, ppi, recorded)
        preflight = engine.preflight(result, "halftone", module="halftone")
        ai["preflight"] = preflight
        if not preflight["details"]["passed"]:
            raise ProcessingError("AI-QA заблокировал сплошной или непригодный полутон")
        return _save_result(result, ppi, asset, normalized, recorded, ai=ai)

    if normalized == "vectorize":
        if _provided(params.get("simplify_mm")):
            simplify_mm = _number(params, "simplify_mm", 0.20, 0.01, 20.0)
            recorded["simplify_mm"] = simplify_mm
            recorded["simplify"] = simplify_mm / 25.4 * ppi
        if _provided(params.get("min_area_mm2")):
            min_area_mm2 = _number(params, "min_area_mm2", 0.50, 0.01, 10000.0)
            recorded["min_area_mm2"] = min_area_mm2
            recorded["min_area"] = min_area_mm2 * (ppi / 25.4) ** 2
        recorded["physical_size_unit"] = "mm"
        ai = engine.recommend_vector(image, module="vector")
        # Explicit user values are authoritative. AI may fill only missing values;
        # it must never silently replace the controls the user has entered.
        if _bool(params, "ai_auto", True):
            if not _provided(params.get("colors")):
                recorded["colors"] = ai["details"]["colors"]
            if not _provided(params.get("simplify_mm")) and not _provided(params.get("simplify")):
                recorded["simplify"] = ai["details"]["simplify"]
        recorded["vector_input_policy"] = "exact_selected_asset_no_auto_segmentation"
        recorded["vector_input_size_px"] = [image.width, image.height]
        ai.setdefault("details", {})["input_policy"] = recorded["vector_input_policy"]
        try:
            svg, diagnostics = _vectorize_with_diagnostics(image, recorded)
            recorded["vector_diagnostics"] = diagnostics
            ai["details"]["fidelity"] = diagnostics
            return _save_svg_result(svg, asset, normalized, recorded, ppi=ppi, ai=ai)
        except UploadValidationError as exc:
            raise ProcessingError(str(exc)) from exc

    if normalized == "master_clean":
        working, background_ai = _ai_subject_result(image, {"ai_sensitivity": 55, "feather": 1}, module="cleanup")
        restored, restoration_ai = engine.restore(working, scale=1, strength=0.3, module="improve")
        result = _cleanup(restored, {"remove_halo": True, "defect_cleanup": 10})
        return _save_result(result, ppi, asset, normalized, recorded, ai={"background": background_ai, "restoration": restoration_ai})

    if normalized == "master_card":
        clean, background_ai = _ai_subject_result(image, {"ai_sensitivity": 55, "feather": 1}, module="cleanup")
        result, ppi = _master_card(clean, params)
        layout_ai = engine.recommend_size(clean, module="geometry")
        return _save_result(result, ppi, asset, normalized, recorded, ai={"background": background_ai, "layout": layout_ai})

    if normalized == "master_dtf":
        extracted, extract_ai = _ai_extract_print(image, {"mode": "auto", "sensitivity": 58, "texture_reduction": 30, "crop_output": True})
        result = _master_dtf(extracted)
        export_ai = engine.recommend_export(result, module="export")
        return _save_result(result, ppi, asset, normalized, recorded, ai={"extract": extract_ai, "export": export_ai})

    raise ProcessingError("Неизвестная операция обработки")
