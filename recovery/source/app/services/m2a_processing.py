from __future__ import annotations

from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy
from app.services import vector_fidelity

_legacy_process_image = legacy.process_image
_CANVAS_ANCHORS = {
    "top-left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top-right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom-right": (1.0, 1.0),
}


def _optional_mm(payload: dict[str, Any], key: str, *, maximum: float = 4000) -> float | None:
    value = payload.get(key)
    if value is None or value == "":
        return None
    return legacy._number({"value": value}, "value", 1, 0.1, maximum)


def geometry_m2a(image: Image.Image, ppi: float, params: dict[str, Any]) -> tuple[Image.Image, float]:
    out = image
    crop = params.get("crop")
    if isinstance(crop, dict):
        x = legacy._number(crop, "x", 0, 0, 100)
        y = legacy._number(crop, "y", 0, 0, 100)
        width = legacy._number(crop, "width", 100, 0.1, 100)
        height = legacy._number(crop, "height", 100, 0.1, 100)
        box = (
            int(round(out.width * x / 100)),
            int(round(out.height * y / 100)),
            int(round(out.width * min(100, x + width) / 100)),
            int(round(out.height * min(100, y + height) / 100)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise legacy.ProcessingError("Область кадрирования имеет нулевой размер")
        out = out.crop(box)
    if params.get("perspective") is not None:
        out = legacy._perspective(out, params.get("perspective"))
    angle = legacy._number(params, "rotate", 0, -360, 360)
    if abs(angle) > 1e-6:
        out = out.rotate(
            -angle,
            resample=Image.Resampling.BICUBIC,
            expand=legacy._bool(params, "expand", True),
            fillcolor=(0, 0, 0, 0),
        )
    if legacy._bool(params, "flip_horizontal", False):
        out = ImageOps.mirror(out)
    if legacy._bool(params, "flip_vertical", False):
        out = ImageOps.flip(out)

    target_ppi = legacy._number(params, "ppi", ppi, 100, 1000)
    width_mm = params.get("width_mm")
    height_mm = params.get("height_mm")
    width_present = width_mm is not None and width_mm != ""
    height_present = height_mm is not None and height_mm != ""
    resample_content = legacy._bool(params, "resample", True)
    leading_side = str(params.get("leading_side", "auto")).strip().lower()
    if leading_side not in {"auto", "width", "height"}:
        raise legacy.ProcessingError("Ведущий размер должен быть auto, width или height")

    if width_present or height_present:
        preserve = legacy._bool(params, "preserve_aspect", True)
        width_value = legacy._number({"value": width_mm}, "value", 1, 0.1, 2000) if width_present else None
        height_value = legacy._number({"value": height_mm}, "value", 1, 0.1, 2000) if height_present else None
        aspect = out.width / max(1, out.height)
        if preserve:
            if width_value is None and height_value is not None:
                width_value = height_value * aspect
            elif height_value is None and width_value is not None:
                height_value = width_value / aspect
            elif width_value is not None and height_value is not None:
                if leading_side == "height":
                    width_value = height_value * aspect
                else:
                    height_value = width_value / aspect
        if width_value is None or height_value is None:
            raise legacy.ProcessingError("Укажите ширину или высоту печати")
        params["resolved_width_mm"] = round(width_value, 4)
        params["resolved_height_mm"] = round(height_value, 4)
        params["leading_side"] = leading_side
        params["resample"] = resample_content
        if resample_content:
            target_width = max(1, int(round(width_value / 25.4 * target_ppi)))
            target_height = max(1, int(round(height_value / 25.4 * target_ppi)))
            legacy._check_output_size(target_width, target_height)
            if out.size != (target_width, target_height):
                out = out.resize((target_width, target_height), Image.Resampling.LANCZOS)
            params["content_resampled"] = True
        else:
            ppi_from_width = out.width / max(width_value / 25.4, 1e-9)
            ppi_from_height = out.height / max(height_value / 25.4, 1e-9)
            if abs(ppi_from_width - ppi_from_height) / max(ppi_from_width, ppi_from_height, 1.0) > 0.01:
                raise legacy.ProcessingError("Печатные размеры без Resample не соответствуют пропорциям изображения")
            target_ppi = (ppi_from_width + ppi_from_height) / 2.0
            if not 100 <= target_ppi <= 1000:
                raise legacy.ProcessingError("Печатный размер без Resample создаёт PPI вне диапазона 100–1000")
            params["content_resampled"] = False
            params["ppi_derived_from_print_size"] = round(target_ppi, 4)
    else:
        params["resample"] = resample_content
        params["content_resampled"] = False

    canvas = params.get("canvas")
    if isinstance(canvas, dict):
        top_mm = legacy._number(canvas, "top_mm", 0, 0, 500)
        bottom_mm = legacy._number(canvas, "bottom_mm", 0, 0, 500)
        left_mm = legacy._number(canvas, "left_mm", 0, 0, 500)
        right_mm = legacy._number(canvas, "right_mm", 0, 0, 500)
        canvas_width_mm = _optional_mm(canvas, "width_mm")
        canvas_height_mm = _optional_mm(canvas, "height_mm")
        if (canvas_width_mm is None) != (canvas_height_mm is None):
            raise legacy.ProcessingError("Ширина и высота холста должны быть указаны вместе")
        anchor = str(canvas.get("anchor", "center")).strip().lower()
        if anchor not in _CANVAS_ANCHORS:
            raise legacy.ProcessingError("Неизвестная точка привязки холста")

        # Convert each axis as one physical span first, then distribute the
        # discrete pixels between the two sides. Rounding each side independently
        # can add or lose one pixel (for example 2 mm + 2 mm at 300 PPI), making
        # the binary canvas read-back disagree with the requested total size.
        px_per_mm = target_ppi / 25.4
        horizontal_total = int(round((left_mm + right_mm) * px_per_mm))
        vertical_total = int(round((top_mm + bottom_mm) * px_per_mm))
        left_px = int(round(left_mm * px_per_mm))
        top_px = int(round(top_mm * px_per_mm))
        pads = {
            "top": top_px,
            "bottom": vertical_total - top_px,
            "left": left_px,
            "right": horizontal_total - left_px,
        }
        minimum_width = out.width + horizontal_total
        minimum_height = out.height + vertical_total
        target_width = minimum_width
        target_height = minimum_height
        if canvas_width_mm is not None and canvas_height_mm is not None:
            target_width = max(1, int(round(canvas_width_mm / 25.4 * target_ppi)))
            target_height = max(1, int(round(canvas_height_mm / 25.4 * target_ppi)))
            if target_width < minimum_width or target_height < minimum_height:
                raise legacy.ProcessingError("Размер холста меньше изображения с заданными отступами")

        legacy._check_output_size(target_width, target_height)
        extra_width = target_width - minimum_width
        extra_height = target_height - minimum_height
        x_factor, y_factor = _CANVAS_ANCHORS[anchor]
        offset_x = pads["left"] + int(round(extra_width * x_factor))
        offset_y = pads["top"] + int(round(extra_height * y_factor))

        if target_width != out.width or target_height != out.height or offset_x or offset_y:
            expanded = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
            expanded.paste(out, (offset_x, offset_y), out)
            out = expanded
            params["canvas_applied"] = True
        else:
            params["canvas_applied"] = False

        params["canvas_pixels"] = pads
        params["canvas_anchor"] = anchor
        params["canvas_target_pixels"] = {"width": target_width, "height": target_height}
        params["canvas_placement_pixels"] = {"x": offset_x, "y": offset_y}
        params["resolved_canvas_width_mm"] = round(target_width / target_ppi * 25.4, 4)
        params["resolved_canvas_height_mm"] = round(target_height / target_ppi * 25.4, 4)
    return out, target_ppi


def process_image(asset: AssetRecord, operation: str, params: dict[str, Any]) -> AssetRecord:
    """M2A adapter: preserve the stable engine while enforcing the shared size contract."""
    normalized = operation.strip().lower()
    if normalized == "vectorize":
        return vector_fidelity.process_vector(asset, params)
    if normalized not in {"geometry", "enhance", "reconstruct"}:
        return _legacy_process_image(asset, operation, params)

    engine = get_ai_engine()
    image, ppi = legacy._load_rgba(asset)
    if image.width * image.height > settings.max_processing_pixels:
        raise legacy.ProcessingError("Изображение превышает безопасный лимит обработки; предварительно уменьшите его")
    recorded = dict(params)
    recorded["input_asset_id"] = asset.id
    recorded["input_operation"] = asset.operation or "upload"
    recorded["input_width_px"] = image.width
    recorded["input_height_px"] = image.height
    recorded["input_ppi"] = round(float(ppi), 4)

    if normalized == "enhance":
        restored, ai = engine.restore(image, scale=1, strength=None, module="improve")
        result = legacy._enhance(restored, params)
        result, result_ppi = geometry_m2a(result, ppi, recorded)
        recorded["physical_size_unit"] = "mm"
        recorded["ppi_range"] = [100, 1000]
        ai["deterministic_postprocess"] = "brightness/contrast/saturation/sharpness"
        return legacy._save_result(result, result_ppi, asset, normalized, recorded, ai=ai)

    if normalized == "reconstruct":
        scale = legacy._integer(params, "scale", 2, 1, 4)
        result, ai = engine.restore(image, scale=scale, strength=None, module="improve")
        detail = legacy._integer(params, "detail", 45, 0, 100)
        if detail:
            result = ImageEnhance.Sharpness(result).enhance(1 + detail / 160)
        result, result_ppi = geometry_m2a(result, ppi, recorded)
        recorded["physical_size_unit"] = "mm"
        recorded["ppi_range"] = [100, 1000]
        return legacy._save_result(result, result_ppi, asset, normalized, recorded, ai=ai)

    ai = engine.recommend_size(image, module="geometry")
    if legacy._bool(params, "ai_auto_crop", False):
        margins = ai["details"]["safe_margins"]
        recorded["crop"] = {
            "x": margins["left"] * 100,
            "y": margins["top"] * 100,
            "width": (1.0 - margins["left"] - margins["right"]) * 100,
            "height": (1.0 - margins["top"] - margins["bottom"]) * 100,
        }
    result, result_ppi = geometry_m2a(image, ppi, recorded)
    return legacy._save_result(result, result_ppi, asset, normalized, recorded, ai=ai)
