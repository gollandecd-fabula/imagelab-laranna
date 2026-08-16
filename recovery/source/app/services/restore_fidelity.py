from __future__ import annotations

import hashlib
import math
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from app.services import image_processing as legacy


_FLAT_MAX_INPUT_PIXELS = 512 * 512
_FLAT_QUANT_ERROR_MAX = 0.045
_FLAT_CLOSE_RATIO_MIN = 0.84


def _image_hash(image: Image.Image) -> str:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return hashlib.sha256(rgba.tobytes()).hexdigest()


def _cv_kmeans(data: np.ndarray, k: int, *, seed: int = 20260816) -> tuple[np.ndarray, np.ndarray, float]:
    work = np.ascontiguousarray(data, dtype=np.float32)
    cv2.setRNGSeed(seed)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    compactness, labels, centers = cv2.kmeans(
        work,
        int(k),
        None,
        criteria,
        10,
        cv2.KMEANS_PP_CENTERS,
    )
    return labels.reshape(-1), centers, float(compactness)


def _bilateral_rgb(image: Image.Image, *, sigma_color: float = 40.0) -> Image.Image:
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    filtered = cv2.bilateralFilter(arr, 5, float(sigma_color), 3.0)
    return Image.fromarray(filtered, "RGB")


def _flat_art_suitability(image: Image.Image) -> dict[str, Any]:
    if image.width * image.height > _FLAT_MAX_INPUT_PIXELS:
        return {
            "accepted": False,
            "reason": "input_too_large_for_bounded_flat_fidelity_path",
            "input_pixels": image.width * image.height,
        }
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if np.any(rgba[:, :, 3] != 255):
        return {"accepted": False, "reason": "nonopaque_alpha_requires_general_restore"}

    denoised = np.asarray(_bilateral_rgb(image), dtype=np.uint8)
    pixels = denoised.reshape(-1, 3).astype(np.float32)
    k = min(8, max(2, len(pixels)))
    labels, centers, compactness = _cv_kmeans(pixels, k)
    distances = np.linalg.norm(pixels - centers[labels], axis=1)
    quant_error = math.sqrt(compactness / max(1.0, float(len(pixels) * 3))) / 255.0
    close_ratio = float(np.mean(distances < 25.0))

    accepted = quant_error <= _FLAT_QUANT_ERROR_MAX and close_ratio >= _FLAT_CLOSE_RATIO_MIN
    return {
        "accepted": bool(accepted),
        "reason": "bounded_low_palette_flat_art" if accepted else "general_image_fallback",
        "quantization_rmse": round(float(quant_error), 6),
        "close_cluster_ratio": round(close_ratio, 6),
        "cluster_count": int(k),
        "input_pixels": int(image.width * image.height),
    }


def _tv_denoise_channel(image: np.ndarray, *, weight: float, iterations: int = 30) -> np.ndarray:
    source = np.asarray(image, dtype=np.float32)
    p0 = np.zeros_like(source)
    p1 = np.zeros_like(source)
    tau = 0.25
    out = source
    for step in range(int(iterations)):
        if step:
            divergence = -(p0 + p1)
            divergence[1:, :] += p0[:-1, :]
            divergence[:, 1:] += p1[:, :-1]
            out = source + divergence
        g0 = np.zeros_like(source)
        g1 = np.zeros_like(source)
        g0[:-1, :] = np.diff(out, axis=0)
        g1[:, :-1] = np.diff(out, axis=1)
        norm = np.sqrt(g0 * g0 + g1 * g1)
        denom = 1.0 + (tau / max(weight, 1e-6)) * norm
        p0 = (p0 - tau * g0) / denom
        p1 = (p1 - tau * g1) / denom
    divergence = -(p0 + p1)
    divergence[1:, :] += p0[:-1, :]
    divergence[:, 1:] += p1[:, :-1]
    return np.clip(source + divergence, 0.0, 1.0)


def _tv_rgb(image: np.ndarray, *, weight: float, iterations: int = 30) -> np.ndarray:
    output = np.empty_like(image, dtype=np.float32)
    for channel in range(3):
        output[:, :, channel] = _tv_denoise_channel(image[:, :, channel], weight=weight, iterations=iterations)
    return np.clip(output, 0.0, 1.0)


def _iterative_back_projection(
    image: Image.Image,
    *,
    scale: int,
    downsample: int,
    iterations: int,
    alpha: float,
    tv_weight: float,
) -> Image.Image:
    target = (image.width * scale, image.height * scale)
    source = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    initial_filter = Image.Resampling.BICUBIC
    estimate = np.asarray(image.convert("RGB").resize(target, initial_filter), dtype=np.float32) / 255.0
    down_filter = Image.Resampling.LANCZOS if downsample == int(Image.Resampling.LANCZOS) else Image.Resampling.BICUBIC

    for _ in range(int(iterations)):
        estimate_u8 = np.clip(np.rint(estimate * 255.0), 0, 255).astype(np.uint8)
        projected = np.asarray(
            Image.fromarray(estimate_u8, "RGB").resize(image.size, down_filter),
            dtype=np.float32,
        ) / 255.0
        error = source - projected
        correction = cv2.resize(error, target, interpolation=cv2.INTER_CUBIC)
        estimate = np.clip(estimate + float(alpha) * correction, 0.0, 1.0)
        estimate = _tv_rgb(estimate, weight=float(tv_weight), iterations=30)

    return Image.fromarray(np.clip(np.rint(estimate * 255.0), 0, 255).astype(np.uint8), "RGB")


def _van_cittert_deblur(image: Image.Image, *, radius: float = 1.19, iterations: int = 15, alpha: float = 1.5) -> Image.Image:
    observation = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    estimate = observation.copy()
    for _ in range(int(iterations)):
        estimate_u8 = np.clip(np.rint(estimate * 255.0), 0, 255).astype(np.uint8)
        blurred = np.asarray(
            Image.fromarray(estimate_u8, "RGB").filter(ImageFilter.GaussianBlur(radius=float(radius))),
            dtype=np.float32,
        ) / 255.0
        estimate = np.clip(estimate + float(alpha) * (observation - blurred), 0.0, 1.0)
    return Image.fromarray(np.clip(np.rint(estimate * 255.0), 0, 255).astype(np.uint8), "RGB")


def _jpeg_chroma_restore(image: Image.Image) -> Image.Image:
    ycrcb = cv2.cvtColor(np.asarray(image.convert("RGB"), dtype=np.uint8), cv2.COLOR_RGB2YCrCb).astype(np.float32)
    output = ycrcb.copy()
    for channel, amount, sigma in ((0, 0.2, 0.8), (1, 3.0, 1.3), (2, 3.0, 1.3)):
        blurred = cv2.GaussianBlur(ycrcb[:, :, channel], (0, 0), sigmaX=sigma, sigmaY=sigma)
        output[:, :, channel] = np.clip(
            ycrcb[:, :, channel] + amount * (ycrcb[:, :, channel] - blurred),
            0,
            255,
        )
    rgb = cv2.cvtColor(np.rint(output).astype(np.uint8), cv2.COLOR_YCrCb2RGB)
    return Image.fromarray(rgb, "RGB")


def _quantize_to_palette(image: Image.Image, palette: np.ndarray) -> Image.Image:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    pixels = arr.reshape(-1, 3)
    distances = ((pixels[:, None, :] - palette[None, :, :]) ** 2).sum(axis=2)
    labels = distances.argmin(axis=1)
    output = palette[labels].reshape(arr.shape)
    return Image.fromarray(np.clip(np.rint(output), 0, 255).astype(np.uint8), "RGB")


def _estimated_flat_palette(image: Image.Image, *, compressed: bool) -> tuple[np.ndarray, dict[str, Any]]:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    u8 = np.clip(arr, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV).reshape(-1, 3)
    pixels = arr.reshape(-1, 3)
    saturation = hsv[:, 1].astype(np.float32)
    value = hsv[:, 2].astype(np.float32)

    colors: list[np.ndarray] = []
    background_mask = (saturation < 45) & (value > 200)
    if int(background_mask.sum()) > 20:
        background = np.median(pixels[background_mask], axis=0)
    else:
        background = np.percentile(pixels, 95, axis=0)
    colors.append(np.asarray(background, dtype=np.float32))

    neutral = np.where(saturation < 110)[0]
    ordered = neutral[np.argsort(value[neutral])]
    sample_count = max(20, min(60, len(ordered) // 150))
    darkest = pixels[ordered[:sample_count]]
    dark_value = float(np.median(np.mean(darkest, axis=1)))
    background_value = float(np.mean(background))
    colors.append(np.asarray([dark_value] * 3, dtype=np.float32))
    colors.append(np.asarray([dark_value + 0.08 * (background_value - dark_value)] * 3, dtype=np.float32))

    source_mask = saturation > (40 if compressed else 50)
    chromatic = pixels[source_mask]
    saturation_threshold = 120 if compressed else 150
    minimum_support = 50 if compressed else 60
    if len(chromatic) > 50:
        if compressed:
            k = min(10, max(5, len(chromatic) // 400))
            distinct_distance = 22.0
        else:
            k = min(8, max(4, len(chromatic) // 600))
            distinct_distance = 25.0
        labels, centers, _ = _cv_kmeans(chromatic, k)
        counts = np.bincount(labels, minlength=k)
        for index in np.argsort(counts)[::-1]:
            center = centers[index]
            center_hsv = cv2.cvtColor(
                np.uint8([[np.clip(center, 0, 255)]]),
                cv2.COLOR_RGB2HSV,
            )[0, 0]
            if center_hsv[1] < saturation_threshold or counts[index] < minimum_support:
                continue
            if all(float(np.linalg.norm(center - existing)) > distinct_distance for existing in colors):
                colors.append(center.astype(np.float32))

    palette = np.asarray(colors, dtype=np.float32)
    return palette, {
        "palette_size": int(len(palette)),
        "background_rgb": [int(round(value)) for value in background],
        "dark_estimate": round(dark_value, 3),
        "compressed_palette": bool(compressed),
    }


def _profile_from_controls(params: dict[str, Any]) -> str:
    detail = legacy._integer(params, "detail", 45, 0, 100)
    denoise = legacy._integer(params, "denoise", 10, 0, 100)
    preserve_text_logo = legacy._bool(params, "preserve_text_logo", True)
    if denoise >= 40:
        return "noise"
    if detail >= 55 and denoise <= 12:
        return "blur"
    if denoise >= 15:
        return "jpeg"
    if detail >= 48 and preserve_text_logo:
        return "text_logo"
    return "lowres"


def _flat_restore(image: Image.Image, params: dict[str, Any], *, scale: int) -> tuple[Image.Image, dict[str, Any]]:
    profile = _profile_from_controls(params)
    diagnostics: dict[str, Any] = {
        "profile": profile,
        "strategy": "bounded_flat_art_inverse_restoration",
        "scale": int(scale),
        "preserve_text_logo_enforced": True,
        "exact_recovery_claimed": False,
        "result_status": "REVIEW",
    }

    if profile == "noise":
        working = _bilateral_rgb(image, sigma_color=40.0)
        result = _iterative_back_projection(
            working,
            scale=scale,
            downsample=int(Image.Resampling.BICUBIC),
            iterations=12,
            alpha=0.7,
            tv_weight=0.04,
        )
        diagnostics["postprocess"] = "bilateral+tv_ibp"
    elif profile == "blur":
        working = _van_cittert_deblur(image)
        result = _iterative_back_projection(
            working,
            scale=scale,
            downsample=int(Image.Resampling.BICUBIC),
            iterations=12,
            alpha=0.7,
            tv_weight=0.04,
        )
        palette, palette_info = _estimated_flat_palette(working, compressed=False)
        result = _quantize_to_palette(result, palette)
        diagnostics["postprocess"] = "van_cittert+tv_ibp+input_palette"
        diagnostics.update(palette_info)
    elif profile == "jpeg":
        working = _jpeg_chroma_restore(image)
        result = _iterative_back_projection(
            working,
            scale=scale,
            downsample=int(Image.Resampling.BICUBIC),
            iterations=16,
            alpha=0.6,
            tv_weight=0.04,
        )
        palette, palette_info = _estimated_flat_palette(working, compressed=True)
        result = _quantize_to_palette(result, palette)
        diagnostics["postprocess"] = "ycrcb_chroma_repair+tv_ibp+input_palette"
        diagnostics.update(palette_info)
    elif profile == "text_logo":
        result = _iterative_back_projection(
            image,
            scale=scale,
            downsample=int(Image.Resampling.LANCZOS),
            iterations=25,
            alpha=0.8,
            tv_weight=0.04,
        )
        diagnostics["postprocess"] = "lanczos_inverse+tv_ibp"
    else:
        result = _iterative_back_projection(
            image,
            scale=scale,
            downsample=int(Image.Resampling.BICUBIC),
            iterations=20,
            alpha=0.8,
            tv_weight=0.04,
        )
        diagnostics["postprocess"] = "bicubic_inverse+tv_ibp"
    return result.convert("RGBA"), diagnostics


def restore_with_diagnostics(image: Image.Image, params: dict[str, Any], engine: Any) -> tuple[Image.Image, dict[str, Any]]:
    """Restore conservatively; use a bounded flat-art inverse path only when source evidence supports it."""
    started = time.perf_counter()
    scale = legacy._integer(params, "scale", 2, 1, 4)
    suitability = _flat_art_suitability(image)
    use_flat = bool(suitability.get("accepted")) and scale == 2

    if not use_flat:
        result, ai = engine.restore(image, scale=scale, strength=None, module="improve")
        detail = legacy._integer(params, "detail", 45, 0, 100)
        if detail:
            result = ImageEnhance.Sharpness(result).enhance(1 + detail / 160)
        ai.setdefault("details", {})["restore_fidelity"] = {
            "strategy": "existing_general_restore_fallback",
            "suitability": suitability,
            "preserve_text_logo_requested": legacy._bool(params, "preserve_text_logo", True),
            "exact_recovery_claimed": False,
            "result_status": "REVIEW",
        }
        return result, ai

    result, details = _flat_restore(image.convert("RGB"), params, scale=scale)
    details["suitability"] = suitability
    output_hash = _image_hash(result)
    ai = {
        "task": "deterministic_flat_art_restoration",
        "model_id": "none",
        "model_version": "classical-v1",
        "confidence": round(min(0.99, max(0.0, float(suitability["close_cluster_ratio"]))), 6),
        "provider": "CPU/numpy+opencv+pillow",
        "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "input_sha256": _image_hash(image),
        "output_sha256": output_hash,
        "details": details,
    }
    return result, ai
