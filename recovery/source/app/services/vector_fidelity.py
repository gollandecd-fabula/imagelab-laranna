from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy


def _vector_suitability_check(image: Image.Image, params: dict[str, Any]) -> dict[str, Any]:
    """Fail-close obvious photo-like inputs before expensive SVG construction."""
    rgba = legacy._rgba_array(image)
    alpha = rgba[:, :, 3]
    visible = alpha > 16
    if int(visible.sum()) < 3:
        raise legacy.ProcessingError("В изображении нет видимой области для векторизации")

    rgb = rgba[:, :, :3]
    samples = rgb[visible]
    if samples.shape[0] > 100_000:
        step = max(1, samples.shape[0] // 100_000)
        samples = samples[::step][:100_000]
    sampled_colors = int(len(np.unique(samples, axis=0)))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    edge_density = float(np.count_nonzero((magnitude > 32.0) & visible)) / float(max(1, np.count_nonzero(visible)))
    complexity = legacy._integer(params, "complexity", 70, 1, 100)
    palette_limit = 256 + complexity * 16
    coverage_ratio = float(np.count_nonzero(visible)) / float(visible.size)
    photo_like = coverage_ratio > 0.98 and sampled_colors > palette_limit and edge_density > 0.12
    diagnostics = {
        "sampled_color_count": sampled_colors,
        "edge_density": round(edge_density, 6),
        "coverage_ratio": round(coverage_ratio, 6),
        "complexity": complexity,
        "palette_limit": palette_limit,
        "photo_like_blocked": photo_like,
    }
    if photo_like:
        raise legacy.ProcessingError(
            "Векторизация заблокирована suitability check: изображение похоже на сложный "
            "фоторастр. Упростите изображение/палитру или используйте растровый workflow."
        )
    return diagnostics


def _flat_art_lossless_svg(image: Image.Image, params: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Encode bounded low-colour, hard-alpha artwork as true SVG path geometry."""
    rgba = legacy._rgba_array(image)
    alpha = rgba[:, :, 3]
    visible = alpha > 16
    if int(visible.sum()) < 3:
        return None

    alpha_values = np.unique(alpha)
    if len(alpha_values) > 2 or any(int(value) not in {0, 255} for value in alpha_values):
        return None
    source_colors = np.unique(rgba[:, :, :3][visible], axis=0)
    if len(source_colors) > 64:
        return None

    complexity = legacy._integer(params, "complexity", 70, 1, 100)
    max_runs = 2500 + complexity * 250
    max_paths = 8000
    max_svg_bytes = min(25 * 1024 * 1024, (2 + complexity) * 256 * 1024)
    run_count = 0
    path_count = 0
    path_parts: list[str] = []
    current_bytes = 0

    rgb = rgba[:, :, :3]
    for color_arr in source_colors:
        color = tuple(int(value) for value in color_arr)
        fill = legacy._rgb_to_hex(color)
        mask = visible & np.all(rgb == color_arr, axis=2)
        commands: list[str] = []
        command_runs = 0
        for y in range(mask.shape[0]):
            padded = np.pad(mask[y].astype(np.int8), (1, 1), constant_values=0)
            changes = np.diff(padded)
            starts = np.flatnonzero(changes == 1)
            ends = np.flatnonzero(changes == -1)
            for x0, x1 in zip(starts, ends, strict=True):
                run_count += 1
                if run_count > max_runs:
                    return None
                x_right = max(float(x0), float(x1) - 0.001)
                y_bottom = float(y) + 0.999
                commands.append(f"M {int(x0)} {y} H {x_right:.3f} V {y_bottom:.3f} H {int(x0)} Z")
                command_runs += 1
                if command_runs == 256:
                    part = f'<path d="{" ".join(commands)}" fill="{fill}" fill-rule="evenodd"/>'
                    path_parts.append(part)
                    current_bytes += len(part.encode("utf-8"))
                    path_count += 1
                    if path_count > max_paths or current_bytes > max_svg_bytes:
                        return None
                    commands = []
                    command_runs = 0
        if commands:
            part = f'<path d="{" ".join(commands)}" fill="{fill}" fill-rule="evenodd"/>'
            path_parts.append(part)
            current_bytes += len(part.encode("utf-8"))
            path_count += 1
            if path_count > max_paths or current_bytes > max_svg_bytes:
                return None

    if not path_parts:
        return None
    width, height = image.size
    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}px" height="{height}px" viewBox="0 0 {width} {height}">'
        + "".join(path_parts)
        + "</svg>"
    )
    encoded_size = len(svg.encode("utf-8"))
    if encoded_size > max_svg_bytes:
        return None
    requested_mode = str(params.get("mode", "color")).lower()
    diagnostics = {
        "strategy": "lossless_flat_art_runs",
        "input_policy": "exact_selected_asset_no_auto_segmentation",
        "original_size_px": [width, height],
        "working_size_px": [width, height],
        "auto_downscaled": False,
        "requested_mode": requested_mode,
        "source_color_count": int(len(source_colors)),
        "source_alpha_levels": [int(value) for value in alpha_values],
        "run_count": run_count,
        "path_count": path_count,
        "coverage_ratio": 1.0,
        "normalized_mae": 0.0,
        "minimum_cluster_iou": 1.0,
        "quality_score": 1.0,
        "svg_size_bytes": encoded_size,
        "fidelity_fallback_recorded": requested_mode == "mono" and len(source_colors) > 1,
        "effective_palette": "source_preserving",
    }
    return svg, diagnostics


def vectorize_with_diagnostics(image: Image.Image, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    suitability = _vector_suitability_check(image, params)
    if image.width * image.height <= min(settings.max_vector_pixels, 1_500_000):
        flat = _flat_art_lossless_svg(image, params)
        if flat is not None:
            svg, diagnostics = flat
            diagnostics["suitability"] = suitability
            return svg, diagnostics
    svg, diagnostics = legacy._vectorize_with_diagnostics(image, params)
    diagnostics["suitability"] = suitability
    return svg, diagnostics


def process_vector(asset: AssetRecord, params: dict[str, Any]) -> AssetRecord:
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

    if legacy._provided(params.get("simplify_mm")):
        simplify_mm = legacy._number(params, "simplify_mm", 0.20, 0.01, 20.0)
        recorded["simplify_mm"] = simplify_mm
        recorded["simplify"] = simplify_mm / 25.4 * ppi
    if legacy._provided(params.get("min_area_mm2")):
        min_area_mm2 = legacy._number(params, "min_area_mm2", 0.50, 0.01, 10000.0)
        recorded["min_area_mm2"] = min_area_mm2
        recorded["min_area"] = min_area_mm2 * (ppi / 25.4) ** 2
    recorded["physical_size_unit"] = "mm"

    ai = engine.recommend_vector(image, module="vector")
    if legacy._bool(params, "ai_auto", True):
        if not legacy._provided(params.get("colors")):
            recorded["colors"] = ai["details"]["colors"]
        if not legacy._provided(params.get("simplify_mm")) and not legacy._provided(params.get("simplify")):
            recorded["simplify"] = ai["details"]["simplify"]
    recorded["vector_input_policy"] = "exact_selected_asset_no_auto_segmentation"
    recorded["vector_input_size_px"] = [image.width, image.height]
    ai.setdefault("details", {})["input_policy"] = recorded["vector_input_policy"]
    try:
        svg, diagnostics = vectorize_with_diagnostics(image, recorded)
        recorded["vector_diagnostics"] = diagnostics
        ai["details"]["fidelity"] = diagnostics
        return legacy._save_svg_result(svg, asset, "vectorize", recorded, ppi=ppi, ai=ai)
    except legacy.UploadValidationError as exc:
        raise legacy.ProcessingError(str(exc)) from exc
