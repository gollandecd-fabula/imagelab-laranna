from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy


def _periodic_shape_score(
    width: int,
    height: int,
    *,
    cell: float,
    angle_deg: float,
    raster: str,
    shape: str,
    nominal_px: float,
) -> np.ndarray:
    """Return a deterministic periodic score field honoring raster/shape/angle controls."""
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    angle = math.radians(angle_deg)
    ca, sa = math.cos(angle), math.sin(angle)
    xr = xx * ca + yy * sa
    yr = -xx * sa + yy * ca

    # Phase in [-1, 1), centered on each raster cell.
    ux = ((xr / max(cell, 1.0) + 0.5) % 1.0 - 0.5) * 2.0
    uy = ((yr / max(cell, 1.0) + 0.5) % 1.0 - 0.5) * 2.0

    # Requested physical dot size changes the geometry preference without
    # changing the global tonal target. This keeps physical controls meaningful.
    radius_bias = float(np.clip(nominal_px / max(cell, 1.0), 0.05, 1.5))
    if shape == "square":
        dot_distance = np.maximum(np.abs(ux), np.abs(uy))
    elif shape == "diamond":
        dot_distance = (np.abs(ux) + np.abs(uy)) / math.sqrt(2.0)
    elif shape == "ellipse":
        dot_distance = np.sqrt((ux / 1.0) ** 2 + (uy / 0.62) ** 2)
    else:
        dot_distance = np.sqrt(ux * ux + uy * uy)

    dot_score = -(dot_distance / max(radius_bias, 0.05))
    line_distance = np.abs(uy)
    line_score = -(line_distance / max(radius_bias, 0.05))

    if raster == "line":
        return line_score.astype(np.float32)
    if raster == "hybrid":
        # Alternate dot/line preference per cell while retaining the exact same
        # target-tone selection rule.
        cell_x = np.floor(xr / max(cell, 1.0)).astype(np.int32)
        cell_y = np.floor(yr / max(cell, 1.0)).astype(np.int32)
        choose_line = ((cell_x + cell_y) & 1).astype(bool)
        return np.where(choose_line, line_score, dot_score).astype(np.float32)
    return dot_score.astype(np.float32)


def _binary_halftone(image: Image.Image, ppi: float, params: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    rgba = legacy._rgba_array(image)
    source_alpha = rgba[:, :, 3]
    rgb = rgba[:, :, :3]
    mode = str(params.get("mode", "color")).lower()
    raster = str(params.get("raster", "dot")).lower()
    shape = str(params.get("shape", "circle")).lower()
    if mode not in {"color", "mono"}:
        raise legacy.ProcessingError("Режим полутона должен быть color или mono")
    if raster not in {"dot", "line", "hybrid"}:
        raise legacy.ProcessingError("Тип растра должен быть dot, line или hybrid")
    if shape not in {"circle", "ellipse", "square", "diamond"}:
        raise legacy.ProcessingError("Форма точки должна быть circle, ellipse, square или diamond")

    nominal_mm = legacy._number(params, "size_mm", 0.20, 0.01, 10.0)
    min_size_mm = legacy._number(params, "min_size_mm", 0.08, 0.01, 10.0)
    max_size_mm = legacy._number(params, "max_size_mm", max(0.40, nominal_mm), 0.01, 20.0)
    if min_size_mm > max_size_mm:
        raise legacy.ProcessingError("Минимальный размер точки не может быть больше максимального")
    nominal_mm = float(np.clip(nominal_mm, min_size_mm, max_size_mm))
    lpi = legacy._number(params, "lpi", 45.0, 5.0, 300.0)
    density = legacy._number(params, "density", 75.0, 1.0, 100.0) / 100.0
    angle = legacy._number(params, "angle", 45.0, -180.0, 180.0)
    alpha_threshold = legacy._integer(params, "alpha_threshold", 8, 0, 255)
    invert = legacy._bool(params, "invert", False)
    foreground = np.array(legacy._hex_rgb(params.get("foreground_color", "#000000")), dtype=np.uint8)

    valid = source_alpha > alpha_threshold
    valid_count = int(np.count_nonzero(valid))
    if valid_count < 3:
        raise legacy.ProcessingError("Полутон не содержит видимой печатной области")

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    darkness = (255.0 - gray) / 255.0
    if invert:
        darkness = 1.0 - darkness

    # Independent M2B tonal contract: overall printed coverage must follow source
    # darkness, while Density acts as a bounded operator around the nominal 55%
    # transfer rather than overwhelming the source tone.
    source_darkness = float(np.mean(darkness))
    density_gain = 0.96 + (density - 0.70) * 0.20  # 0.90..1.02 across allowed density
    requested_coverage = source_darkness * 0.55 * density_gain
    valid_coverage = valid_count / float(valid.size)
    target_coverage = float(np.clip(requested_coverage, 0.0005, min(0.90, valid_coverage)))
    desired = int(round(target_coverage * valid.size))
    desired = max(1, min(valid_count, desired))

    cell = max(2.0, float(ppi) / float(lpi))
    nominal_px = nominal_mm / 25.4 * float(ppi)
    pattern = _periodic_shape_score(
        image.width,
        image.height,
        cell=cell,
        angle_deg=angle,
        raster=raster,
        shape=shape,
        nominal_px=nominal_px,
    )

    # Darkness drives local selection; pattern controls break ties and gives the
    # requested raster geometry. Stable coordinate jitter prevents large equal-score
    # plateaus without using a mutable/random seed.
    yy, xx = np.mgrid[0:image.height, 0:image.width]
    jitter = (((xx * 73856093) ^ (yy * 19349663)) & 0xFFFF).astype(np.float32) / 65535.0
    score = darkness * 4.0 + pattern * 0.65 + jitter * 1e-3
    flat_valid = np.flatnonzero(valid.ravel())
    valid_scores = score.ravel()[flat_valid]
    if desired < valid_count:
        kth = valid_count - desired
        chosen_local = np.argpartition(valid_scores, kth)[kth:]
        chosen = flat_valid[chosen_local]
    else:
        chosen = flat_valid

    selected = np.zeros(valid.size, dtype=bool)
    selected[chosen] = True
    selected = selected.reshape(valid.shape)

    canvas = np.zeros_like(rgba)
    if mode == "color":
        canvas[:, :, :3][selected] = rgb[selected]
    else:
        canvas[:, :, :3][selected] = foreground
    canvas[:, :, 3][selected] = 255

    coverage = float(np.count_nonzero(selected)) / float(selected.size)
    if coverage < 0.0005:
        raise legacy.ProcessingError("Полутон не содержит достаточного количества печатных элементов")
    if coverage > 0.92:
        raise legacy.ProcessingError("Полутон превратился в почти сплошную заливку")

    diagnostics = {
        "strategy": "m2b_tonal_binary_ranked_raster",
        "source_darkness": round(source_darkness, 8),
        "density_gain": round(density_gain, 6),
        "target_coverage": round(target_coverage, 8),
        "actual_coverage": round(coverage, 8),
        "binary_alpha": True,
        "alpha_mode": "production_binary",
        "cell_px": round(cell, 6),
        "nominal_dot_px": round(nominal_px, 6),
        "mode": mode,
        "raster": raster,
        "shape": shape,
        "angle": angle,
    }
    return legacy._pil_from_rgba(canvas), diagnostics


def process_halftone(asset: AssetRecord, params: dict[str, Any]) -> AssetRecord:
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

    ai = engine.recommend_halftone(image, module="halftone")
    if legacy._bool(params, "ai_auto", True):
        if not legacy._provided(params.get("raster")):
            recorded["raster"] = ai["details"]["raster"]
        if not legacy._provided(params.get("size_mm")):
            recorded["size_mm"] = ai["details"]["size_mm"]
        if not legacy._provided(params.get("density")):
            recorded["density"] = ai["details"]["density"]

    safe_cell_mm = legacy._minimum_halftone_size_mm(image, ppi)
    max_safe_lpi = max(5.0, min(300.0, 25.4 / max(safe_cell_mm, 1e-6)))
    requested_lpi = legacy._number(recorded, "lpi", 45.0, 5.0, 300.0)
    recorded["lpi"] = round(min(requested_lpi, max_safe_lpi), 4)
    requested_size = legacy._number(recorded, "size_mm", 0.2, 0.01, 10.0)
    minimum_size = legacy._number(recorded, "min_size_mm", 0.08, 0.01, 10.0)
    maximum_size = legacy._number(recorded, "max_size_mm", max(0.4, requested_size), 0.01, 20.0)
    if minimum_size > maximum_size:
        raise legacy.ProcessingError("Минимальный размер точки не может быть больше максимального")
    recorded["size_mm"] = round(float(np.clip(requested_size, minimum_size, maximum_size)), 4)
    recorded["min_size_mm"] = round(minimum_size, 4)
    recorded["max_size_mm"] = round(maximum_size, 4)
    recorded["validator_min_cell_mm"] = round(safe_cell_mm, 4)
    recorded["validator_min_size_mm"] = round(safe_cell_mm, 4)
    recorded["validator_max_lpi"] = round(max_safe_lpi, 4)
    recorded["physical_size_unit"] = "mm"
    recorded["alpha_mode"] = "production_binary"

    result, diagnostics = _binary_halftone(image, ppi, recorded)
    recorded["halftone_diagnostics"] = diagnostics
    ai["details"].update({
        "validator_min_cell_mm": round(safe_cell_mm, 4),
        "validator_max_lpi": round(max_safe_lpi, 4),
        "final_size_mm": recorded["size_mm"],
        "final_lpi": recorded["lpi"],
        "production_alpha": "binary_0_255",
        "tonal_fidelity": diagnostics,
    })
    preflight = engine.preflight(result, "halftone", module="halftone")
    ai["preflight"] = preflight
    if not preflight["details"]["passed"]:
        raise legacy.ProcessingError("AI-QA заблокировал сплошной или непригодный полутон")
    return legacy._save_result(result, ppi, asset, "halftone", recorded, ai=ai)
