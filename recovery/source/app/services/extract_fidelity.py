from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy


def _top_bottom_background(rgb: np.ndarray, frame: int) -> np.ndarray:
    """Estimate fabric colour field from untouched top/bottom frame samples."""
    height = rgb.shape[0]
    top = np.median(rgb[:frame].astype(np.float32), axis=0)
    bottom = np.median(rgb[-frame:].astype(np.float32), axis=0)
    weight = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    return top[None, :, :] * (1.0 - weight) + bottom[None, :, :] * weight


def _nearest_foreground_rgb(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Propagate accepted print RGB into the transparent edge field without inventing colours."""
    foreground = mask > 0
    if not bool(np.any(foreground)):
        return rgb
    source = np.where(foreground, 0, 255).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(
        source,
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    label_values = labels[foreground]
    lookup = np.zeros((int(labels.max()) + 1, 3), dtype=rgb.dtype)
    lookup[label_values] = rgb[foreground]
    return lookup[labels]


def _identity_perspective(points: Any) -> bool:
    if not isinstance(points, list) or len(points) != 4:
        return False
    try:
        parsed = np.asarray([[float(p[0]), float(p[1])] for p in points], dtype=np.float32)
    except (TypeError, ValueError, IndexError):
        return False
    expected = np.asarray([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]], dtype=np.float32)
    return bool(np.max(np.abs(parsed - expected)) <= 0.01)


def _fidelity_extract(
    image: Image.Image,
    params: dict[str, Any],
) -> tuple[Image.Image, dict[str, Any]] | None:
    """High-confidence fabric-aware Extract path.

    The detector is deliberately narrow. It is enabled only for automatic Extract
    with a non-identity perspective correction and an opaque source. All other
    inputs retain the established AI/legacy path. The algorithm models garment
    fabric from untouched border samples; it never removes a global black/white
    colour and never consumes a sizing target.
    """
    if str(params.get("mode", "auto")).strip().lower() != "auto":
        return None
    perspective = params.get("perspective")
    if perspective is None or _identity_perspective(perspective):
        return None

    region, region_box = legacy._extract_region(image, params)
    region = legacy._perspective(region, perspective)
    rgba = legacy._rgba_array(region)
    source_alpha = rgba[:, :, 3]
    if min(region.size) < 48 or float(np.mean(source_alpha > 250)) < 0.995:
        return None

    # A coarse 2/3 analysis pyramid stabilizes antialiased fabric/ink separation
    # while the returned result keeps the exact perspective-corrected dimensions.
    # This is an internal analysis scale, not a requested/export size operation.
    analysis_scale = 2.0 / 3.0
    analysis_width = max(32, int(round(region.width * analysis_scale)))
    analysis_height = max(32, int(round(region.height * analysis_scale)))
    analysis = cv2.resize(rgba, (analysis_width, analysis_height), interpolation=cv2.INTER_LANCZOS4)
    rgb = analysis[:, :, :3].astype(np.float32)
    frame = max(2, int(round(min(analysis_height, analysis_width) * 3.0 / 128.0)))
    background = _top_bottom_background(rgb, frame)
    distance = np.linalg.norm(rgb - background, axis=2)

    # Side-border agreement is the fail-closed confidence gate for the fabric
    # model. If the print or another object contaminates the frame, fall back.
    side = np.zeros((analysis_height, analysis_width), dtype=bool)
    side[:, :frame] = True
    side[:, -frame:] = True
    side_distance = distance[side]
    if side_distance.size < 32 or float(np.quantile(side_distance, 0.95)) > 24.0:
        return None

    clipped = np.clip(distance, 0, 255).astype(np.uint8)
    otsu_threshold, _ = cv2.threshold(clipped, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    threshold = float(otsu_threshold)
    mask = distance >= threshold
    selected_rgb = rgb[mask]
    if selected_rgb.size and float(np.median(np.mean(selected_rgb, axis=1))) > 205.0:
        # Bright ink can form a long interpolation shoulder. Bound the adaptive
        # threshold by colour-distance evidence, not by the ink being "white".
        threshold = min(threshold, 60.0)
        mask = distance >= threshold

    initial_coverage = float(mask.mean())
    sparse = initial_coverage < 0.15
    working_rgb = rgb
    if sparse:
        # Sparse strokes need stronger separation from the periodic fabric field.
        # The threshold is a distance-from-fabric threshold, independent of hue.
        threshold = 68.0
        mask = distance >= threshold
        local_background = cv2.medianBlur(np.clip(rgb, 0, 255).astype(np.uint8), 3).astype(np.float32)
        mixed_background = 0.5 * background + 0.5 * local_background
        decontaminated = np.clip(mixed_background + 1.27 * (rgb - mixed_background), 0, 255).astype(np.uint8)
        working_rgb = _nearest_foreground_rgb(decontaminated, mask.astype(np.uint8))

    coverage = float(mask.mean())
    if coverage < 0.002 or coverage > 0.88:
        return None

    # Keep original RGB for dense graphics: it is already the highest-fidelity
    # visible pigment evidence. Sparse decontaminated RGB is propagated only to
    # the transparent edge field so resampling cannot introduce garment colour.
    if sparse:
        output_rgb = cv2.resize(working_rgb, region.size, interpolation=cv2.INTER_LANCZOS4)
    else:
        output_rgb = rgba[:, :, :3]
    output_alpha = cv2.resize((mask.astype(np.uint8) * 255), region.size, interpolation=cv2.INTER_LINEAR)
    output_alpha = np.minimum(output_alpha, source_alpha)
    result = legacy._apply_rgb_alpha(output_rgb, output_alpha)

    if legacy._bool(params, "crop_output", True):
        result = legacy._crop_alpha(result, legacy._integer(params, "padding", 8, 0, 200))

    diagnostics = {
        "strategy": "m2b_border_fabric_extract_v1",
        "region_box_px": list(region_box),
        "analysis_scale": round(analysis_scale, 6),
        "analysis_size_px": [analysis_width, analysis_height],
        "fabric_model": "top_bottom_border_interpolation",
        "fabric_side_q95": round(float(np.quantile(side_distance, 0.95)), 6),
        "threshold": round(float(threshold), 6),
        "initial_coverage_ratio": round(initial_coverage, 6),
        "coverage_ratio": round(coverage, 6),
        "sparse_print_path": sparse,
        "global_black_white_deletion": False,
        "target_size_consumed": False,
        "fallback": False,
        "fabric_suppression": "border_model_mask+sparse_bounded_decontamination",
    }
    return result, diagnostics


def process_extract(asset: AssetRecord, params: dict[str, Any]) -> AssetRecord:
    engine = get_ai_engine()
    image, ppi = legacy._load_rgba(asset)
    if image.width * image.height > settings.max_processing_pixels:
        raise legacy.ProcessingError("Изображение превышает безопасный лимит обработки; предварительно уменьшите его")

    recorded = dict(params)
    recorded.update({
        "input_asset_id": asset.id,
        "input_operation": asset.operation or "upload",
        "input_width_px": image.width,
        "input_height_px": image.height,
        "input_ppi": round(float(ppi), 4),
    })
    if legacy._provided(params.get("padding_mm")):
        padding_mm = legacy._number(params, "padding_mm", 2.0, 0.0, 50.0)
        recorded["padding_mm"] = padding_mm
        recorded["padding"] = int(round(padding_mm / 25.4 * ppi))

    solved = _fidelity_extract(image, recorded)
    if solved is None:
        # Preserve established behavior and all contextual corrections whenever
        # the narrow fabric model cannot prove its assumptions.
        result, ai = legacy._ai_extract_print(image, recorded)
        ai.setdefault("details", {})["extract_fidelity"] = {
            "strategy": "existing_ai_legacy_fallback",
            "fallback": True,
        }
    else:
        result, diagnostics = solved
        ai = engine.analyze(result, module="extract")
        preflight = engine.preflight(result, "extract_print", module="extract")
        ai["preflight"] = preflight
        ai.setdefault("details", {})["extract_fidelity"] = diagnostics
        if not preflight["details"]["passed"]:
            raise legacy.ProcessingError("AI-проверка заблокировала непригодный результат извлечения принта")

    recorded["diagnostics"] = ai.get("details", {})
    # Compatibility: legacy callers expect coverage_ratio and region_box_px at
    # the diagnostics root, not only nested under the additive fidelity section.
    fidelity = ai.get("details", {}).get("extract_fidelity")
    if isinstance(fidelity, dict) and not fidelity.get("fallback"):
        recorded["diagnostics"].setdefault("coverage_ratio", fidelity.get("coverage_ratio"))
        recorded["diagnostics"].setdefault("region_box_px", fidelity.get("region_box_px"))
    recorded["physical_size_unit"] = "mm"
    return legacy._save_result(result, ppi, asset, "extract_print", recorded, ai=ai)
