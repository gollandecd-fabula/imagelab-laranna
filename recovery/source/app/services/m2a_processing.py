from __future__ import annotations

from typing import Any

from PIL import Image, ImageOps

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy

_legacy_process_image = legacy.process_image


def geometry_m2a(image: Image.Image, ppi: float, params: dict[str, Any]) -> tuple[Image.Image, float]:
    out = image
    crop = params.get("crop")
    if isinstance(crop, dict):
        x = legacy._number(crop, "x", 0, 0, 100)
        y = legacy._number(crop, "y", 0, 0, 100)
        width = legacy._number(crop, "width", 100, 0.1, 100)
        height = legacy._number(crop, "height", 100, 0.1, 100)
        box = (
            int(round(out.width * x / 100)), int(round(out.height * y / 100)),
            int(round(out.width * min(100, x + width) / 100)), int(round(out.height * min(100, y + height) / 100)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise legacy.ProcessingError("Область кадрирования имеет нулевой размер")
        out = out.crop(box)
    if params.get("perspective") is not None:
        out = legacy._perspective(out, params.get("perspective"))
    angle = legacy._number(params, "rotate", 0, -360, 360)
    if abs(angle) > 1e-6:
        out = out.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=legacy._bool(params, "expand", True), fillcolor=(0, 0, 0, 0))
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
        pads = {
            "top": int(round(top_mm / 25.4 * target_ppi)),
            "bottom": int(round(bottom_mm / 25.4 * target_ppi)),
            "left": int(round(left_mm / 25.4 * target_ppi)),
            "right": int(round(right_mm / 25.4 * target_ppi)),
        }
        target_width = out.width + pads["left"] + pads["right"]
        target_height = out.height + pads["top"] + pads["bottom"]
        legacy._check_output_size(target_width, target_height)
        if any(pads.values()):
            expanded = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
            expanded.paste(out, (pads["left"], pads["top"]), out)
            out = expanded
            params["canvas_applied"] = True
        else:
            params["canvas_applied"] = False
        params["canvas_pixels"] = pads
    return out, target_ppi



def process_image(asset: AssetRecord, operation: str, params: dict[str, Any]) -> AssetRecord:
    """M2A adapter: preserve the stable processing engine and extend geometry contracts."""
    normalized = operation.strip().lower()
    if normalized != "geometry":
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
