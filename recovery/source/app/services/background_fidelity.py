from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import AssetRecord
from app.services import image_processing as legacy


def _border_model(image: Image.Image) -> tuple[np.ndarray, dict[str, Any]] | None:
    """Reconstruct only high-confidence studio backgrounds from untouched frame pixels."""
    rgba = legacy._rgba_array(image)
    if float(np.mean(rgba[:, :, 3] > 250)) < 0.995:
        return None
    rgb = rgba[:, :, :3]
    h, w = rgb.shape[:2]
    if min(h, w) < 24:
        return None
    frame = max(2, min(6, min(h, w) // 24))
    samples = np.concatenate((
        rgb[:frame].reshape(-1, 3), rgb[-frame:].reshape(-1, 3),
        rgb[:, :frame].reshape(-1, 3), rgb[:, -frame:].reshape(-1, 3),
    ))
    colors, counts = np.unique(samples, axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]
    colors = colors[order]
    counts = counts[order]

    # Uniform studio sweep.
    if len(colors) == 1 or (len(colors) <= 4 and counts[0] / counts.sum() > 0.985):
        bg = np.empty_like(rgb)
        bg[:] = colors[0]
        residual = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
        if float(np.mean(residual[:frame] <= 1.5)) < 0.98:
            return None
        return bg, {"model": "uniform", "frame_px": frame, "background_colors": [colors[0].tolist()]}

    # Regular two-colour checker. The top and left frame fully determine the parity grid.
    if len(colors) == 2 and min(counts) / counts.sum() > 0.20:
        palette = colors.astype(np.int16)
        top = rgb[0].astype(np.int16)
        left = rgb[:, 0].astype(np.int16)
        top_label = np.argmin(np.sum((top[:, None, :] - palette[None, :, :]) ** 2, axis=2), axis=1)
        left_label = np.argmin(np.sum((left[:, None, :] - palette[None, :, :]) ** 2, axis=2), axis=1)
        top_err = np.min(np.sum((top[:, None, :] - palette[None, :, :]) ** 2, axis=2), axis=1)
        left_err = np.min(np.sum((left[:, None, :] - palette[None, :, :]) ** 2, axis=2), axis=1)
        if int(top_err.max()) == 0 and int(left_err.max()) == 0:
            corner = int(top_label[0])
            labels = np.bitwise_xor(np.bitwise_xor(left_label[:, None], top_label[None, :]), corner)
            bg = colors[labels]
            # Verify all four borders, not just the generating edges.
            border_ok = np.concatenate((
                np.all(bg[:frame] == rgb[:frame], axis=2).ravel(),
                np.all(bg[-frame:] == rgb[-frame:], axis=2).ravel(),
                np.all(bg[:, :frame] == rgb[:, :frame], axis=2).ravel(),
                np.all(bg[:, -frame:] == rgb[:, -frame:], axis=2).ravel(),
            ))
            if float(border_ok.mean()) > 0.995:
                return bg.astype(np.uint8), {"model": "checker_two_colour", "frame_px": frame, "background_colors": colors.tolist()}

    # Tightly coherent horizontal sweep: each row has one border colour across the frame.
    row_samples = np.concatenate((rgb[:, :frame], rgb[:, -frame:]), axis=1).astype(np.float32)
    row_bg = np.median(row_samples, axis=1)
    row_dev = np.max(np.abs(row_samples - row_bg[:, None, :]), axis=(1, 2))
    if float(np.quantile(row_dev, 0.95)) <= 1.0:
        steps = np.diff(row_bg, axis=0)
        if float(np.quantile(np.abs(steps), 0.99)) <= 3.0:
            bg = np.repeat(np.rint(row_bg).astype(np.uint8)[:, None, :], w, axis=1)
            return bg, {"model": "row_gradient", "frame_px": frame, "background_colors": "per_row"}
    return None


def _foreground_colour(rgb: np.ndarray, bg: np.ndarray) -> np.ndarray | None:
    residual = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2)
    candidates = rgb[residual > 3.0]
    if len(candidates) < 16:
        return None
    colors, counts = np.unique(candidates, axis=0, return_counts=True)
    idx = int(np.argmax(counts))
    colour = colors[idx].astype(np.float32)
    # A high-confidence single-foreground studio model must have an opaque colour mode.
    if int(counts[idx]) < max(12, int(len(candidates) * 0.08)):
        return None
    return colour


def _solve_studio_matte(image: Image.Image, params: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]] | None:
    modeled = _border_model(image)
    if modeled is None:
        return None
    bg, diagnostics = modeled
    rgba = legacy._rgba_array(image)
    rgb = rgba[:, :, :3].astype(np.float32)
    bgf = bg.astype(np.float32)
    fg = _foreground_colour(rgba[:, :, :3], bg)
    if fg is None:
        return None

    direction = fg[None, None, :] - bgf
    denom = np.sum(direction * direction, axis=2)
    numer = np.sum((rgb - bgf) * direction, axis=2)
    alpha = np.zeros(denom.shape, dtype=np.float32)
    valid = denom > 6.0
    alpha[valid] = numer[valid] / denom[valid]
    alpha = np.clip(alpha, 0.0, 1.0)

    # Suppress model noise while retaining hair/semitransparent support.
    residual = np.linalg.norm(rgb - bgf, axis=2)
    alpha[residual <= 1.5] = 0.0
    residual_pixels = rgba[:, :, :3][residual > 1.5]
    residual_unique = np.unique(residual_pixels, axis=0) if len(residual_pixels) else np.empty((0, 3), dtype=np.uint8)
    opaque_light_multitone = float(np.mean(fg)) > 235.0 and len(residual_unique) <= 4
    if opaque_light_multitone:
        # Near-white products often contain several legitimate opaque shades
        # (for example white fabric plus a slightly darker printed detail). Treating
        # those shades as transparency would punch holes into the product.
        alpha_u8 = np.where(residual > 1.5, 255, 0).astype(np.uint8)
    else:
        alpha_u8 = np.rint(alpha * 255.0).astype(np.uint8)
    alpha_u8 = np.minimum(alpha_u8, rgba[:, :, 3])
    selected = alpha_u8 > 16
    coverage = float(selected.mean())
    if coverage < 0.005 or coverage > 0.94:
        raise legacy.ProcessingError("Безопасная студийная маска фона не подтверждена")
    frame_width = max(1, int(round(min(alpha_u8.shape) * 0.02)))
    frame_mask = np.zeros(selected.shape, dtype=bool)
    frame_mask[:frame_width] = True; frame_mask[-frame_width:] = True
    frame_mask[:, :frame_width] = True; frame_mask[:, -frame_width:] = True
    border_ratio = float(np.count_nonzero(selected & frame_mask)) / max(1, int(np.count_nonzero(selected)))
    if border_ratio > 0.08:
        raise legacy.ProcessingError("Маска фона касается границы кадра небезопасным образом")

    out = np.zeros_like(rgba)
    # Bounded decontamination: use the recovered opaque subject colour for a
    # coherent soft matte. Preserve original RGB when the subject is recognized
    # as opaque multi-tone artwork/fabric.
    if opaque_light_multitone:
        out[:, :, :3][selected] = rgba[:, :, :3][selected]
    else:
        out[:, :, :3][selected] = np.clip(np.rint(fg), 0, 255).astype(np.uint8)
    out[:, :, 3] = alpha_u8
    diagnostics.update({
        "strategy": "m2b_studio_border_matte",
        "foreground_colour": [int(v) for v in np.rint(fg)],
        "coverage_ratio": round(coverage, 6),
        "border_ratio": round(border_ratio, 6),
        "decontamination": "preserve_opaque_multitone" if opaque_light_multitone else "bounded_single_foreground_colour",
        "opaque_light_multitone": opaque_light_multitone,
        "fallback": False,
    })
    return legacy._pil_from_rgba(out), diagnostics


def process_background(asset: AssetRecord, params: dict[str, Any]) -> AssetRecord:
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
    action = str(params.get("action", "remove")).strip().lower()
    if action != "remove":
        # Preserve existing public behavior for replace/remove_color and other supported modes.
        return legacy.process_image(asset, "background", params)

    studio = _solve_studio_matte(image, recorded)
    if studio is None:
        result, ai = legacy._ai_subject_result(image, recorded, module="cleanup")
        fallback_diagnostics = {"strategy": "existing_ai_fallback", "fallback": True}
        recorded["background_diagnostics"] = fallback_diagnostics
        recorded["diagnostics"] = ai.get("details", {})
    else:
        result, diagnostics = studio
        ai = engine.analyze(result, module="cleanup")
        preflight = engine.preflight(result, "background", module="cleanup")
        ai["preflight"] = preflight
        ai.setdefault("details", {})["background_fidelity"] = diagnostics
        recorded["background_diagnostics"] = diagnostics
        # Preserve the long-standing public compatibility contract consumed by
        # release/lineage regression checks; F04 diagnostics are additive.
        recorded["diagnostics"] = ai.get("details", {})
        if not preflight["details"]["passed"]:
            raise legacy.ProcessingError("AI-QA заблокировал непригодную маску фона")
    return legacy._save_result(result, ppi, asset, "background", recorded, ai=ai)
