from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass
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
from PIL import Image

from app.ai.audit import AIAuditStore
from app.ai.features import binary_edge_map, image_features, operation_qa_features, pil_to_rgb_alpha, pixel_features
from app.ai.feedback import AIFeedbackStore
from app.ai.linear_models import BinaryLogisticModel
from app.ai.registry import AIModelError, AIModelRegistry
from app.config import settings


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_hash(image: Image.Image) -> str:
    array = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return _sha256_bytes(array.tobytes())


def _array_hash(array: np.ndarray) -> str:
    return _sha256_bytes(np.ascontiguousarray(array).tobytes())


def _largest_component(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 16).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return np.zeros_like(mask)
    valid = [index for index in range(1, count) if stats[index, cv2.CC_STAT_AREA] > 0]
    if not valid:
        return np.zeros_like(mask)
    largest = max(valid, key=lambda index: stats[index, cv2.CC_STAT_AREA])
    return np.where(labels == largest, mask, 0).astype(np.uint8)


def _normalize_mask(probability: np.ndarray, threshold: float, *, feather: float = 1.0, keep_largest: bool = True) -> np.ndarray:
    mask = np.where(probability >= threshold, 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    if keep_largest:
        mask = _largest_component(mask)
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), max(0.35, feather / 2.0))
    return mask


def _dominant_lab_center(pixels: np.ndarray, max_samples: int = 5000) -> np.ndarray:
    """Deterministically estimate the dominant fabric color in LAB space.

    A single median can be pulled toward a large print; a tiny deterministic
    three-cluster Lloyd loop isolates the largest appearance cluster without
    relying on global OpenCV RNG state.
    """
    if pixels.ndim != 2 or pixels.shape[1] != 3 or pixels.shape[0] < 3:
        raise AIModelError("Недостаточно пикселей для оценки ткани")
    step = max(1, pixels.shape[0] // max_samples)
    sample = pixels[::step][:max_samples].astype(np.float32, copy=False)
    median = np.median(sample, axis=0)
    first_distance = np.linalg.norm(sample - median[None, :], axis=1)
    farthest = sample[int(np.argmax(first_distance))]
    second_distance = np.minimum(first_distance, np.linalg.norm(sample - farthest[None, :], axis=1))
    third = sample[int(np.argmax(second_distance))]
    centers = np.stack([median, farthest, third]).astype(np.float32)
    labels = np.zeros(sample.shape[0], dtype=np.int32)
    for _ in range(10):
        distances = np.linalg.norm(sample[:, None, :] - centers[None, :, :], axis=2)
        labels = np.argmin(distances, axis=1).astype(np.int32)
        updated = centers.copy()
        for index in range(3):
            selected = sample[labels == index]
            if selected.size:
                updated[index] = np.median(selected, axis=0)
        if np.allclose(updated, centers, atol=0.01):
            centers = updated
            break
        centers = updated
    counts = np.bincount(labels, minlength=3)
    return centers[int(np.argmax(counts))]


def _fill_enclosed_holes(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Fill only holes disconnected from the image border.

    This recovers dark ink enclosed by colored print regions without turning the
    whole print bounding box into foreground.
    """
    binary = np.where(mask > 16, 255, 0).astype(np.uint8)
    inverse = cv2.bitwise_not(binary)
    flood = inverse.copy()
    flood_mask = np.zeros((binary.shape[0] + 2, binary.shape[1] + 2), np.uint8)
    cv2.floodFill(flood, flood_mask, (0, 0), 128)
    holes = np.where(flood == 255, 255, 0).astype(np.uint8)
    return cv2.bitwise_or(binary, holes), int(np.count_nonzero(holes))


def _mask_border_ratio(mask: np.ndarray, border_fraction: float = 0.02) -> float:
    binary = mask > 16
    h, w = binary.shape
    border = max(1, int(round(min(h, w) * border_fraction)))
    frame = np.zeros_like(binary)
    frame[:border, :] = True
    frame[-border:, :] = True
    frame[:, :border] = True
    frame[:, -border:] = True
    selected = int(binary.sum())
    return float((binary & frame).sum()) / max(1, selected)


def _studio_subject_fallback(image: Image.Image, feather: float = 0.0) -> tuple[np.ndarray, dict[str, Any]]:
    """Thread-safe deterministic studio-product segmentation for OOD masks.

    The fallback intentionally avoids GrabCut: OpenCV GrabCut proved capable of
    stalling after repeated requests issued by different ASGI worker threads.
    Product photos with a mostly uniform border are separated by foreground/
    background polarity, morphology and a centred-component score instead.
    """
    original_rgb, original_alpha = pil_to_rgb_alpha(image)
    original_h, original_w = original_alpha.shape
    scale = min(1.0, 900.0 / max(original_w, original_h))
    if scale < 1.0:
        w = max(32, int(round(original_w * scale)))
        h = max(32, int(round(original_h * scale)))
        rgb = cv2.resize(original_rgb, (w, h), interpolation=cv2.INTER_AREA)
        source_alpha = cv2.resize(original_alpha, (w, h), interpolation=cv2.INTER_AREA)
    else:
        rgb, source_alpha = original_rgb, original_alpha
        h, w = source_alpha.shape

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    border = max(2, int(round(min(h, w) * 0.025)))
    frame = np.zeros((h, w), dtype=bool)
    frame[:border, :] = True
    frame[-border:, :] = True
    frame[:, :border] = True
    frame[:, -border:] = True
    frame &= source_alpha > 8
    border_values = gray[frame]
    if border_values.size < 30:
        raise AIModelError("Недостаточно фоновых пикселей для резервной сегментации")

    border_median = float(np.median(border_values))
    border_brightness = float(np.percentile(border_values, 65))
    yy, xx = np.ogrid[:h, :w]
    central = (xx > w * 0.08) & (xx < w * 0.92) & (yy > h * 0.04) & (yy < h * 0.94)
    central_values = gray[central & (source_alpha > 8)]
    center_median = float(np.median(central_values)) if central_values.size else border_median

    polarity = "general"
    sure_threshold: float | None = None
    if border_brightness - center_median >= 22.0:
        polarity = "dark_subject"
        contrast_gap = max(1.0, border_brightness - center_median)
        probable_threshold = center_median + contrast_gap * 0.50
        sure_threshold = center_median + contrast_gap * 0.18
        probable = (gray <= probable_threshold) & (source_alpha > 8)
    elif center_median - border_median >= 22.0:
        polarity = "light_subject"
        contrast_gap = max(1.0, center_median - border_median)
        probable_threshold = center_median - contrast_gap * 0.50
        sure_threshold = center_median - contrast_gap * 0.18
        probable = (gray >= probable_threshold) & (source_alpha > 8)
    else:
        samples = lab[frame]
        background_center = np.median(samples, axis=0)
        distance = np.linalg.norm(lab - background_center[None, None, :], axis=2)
        probable_threshold = max(14.0, float(np.percentile(distance[frame], 99.0)) + 5.0)
        probable = (distance >= probable_threshold) & (source_alpha > 8)

    # Border pixels are background by definition for the studio fallback.
    probable[frame] = False
    raw = np.where(probable, 255, 0).astype(np.uint8)
    close_size = max(5, int(round(min(h, w) * 0.009)))
    if close_size % 2 == 0:
        close_size += 1
    close_size = min(close_size, 15)
    raw = cv2.morphologyEx(
        raw,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)),
        iterations=1,
    )
    raw = cv2.morphologyEx(
        raw,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )

    count, labels, stats, centers = cv2.connectedComponentsWithStats((raw > 16).astype(np.uint8), 8)
    best_index = None
    best_score = -1.0
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < max(100, int(h * w * 0.01)):
            continue
        cx, cy = centers[index]
        center_distance = ((cx - w / 2) / max(1, w / 2)) ** 2 + ((cy - h / 2) / max(1, h / 2)) ** 2
        component = labels == index
        component_mask = np.where(component, 255, 0).astype(np.uint8)
        border_ratio = _mask_border_ratio(component_mask)
        x0 = int(stats[index, cv2.CC_STAT_LEFT])
        y0 = int(stats[index, cv2.CC_STAT_TOP])
        cw = int(stats[index, cv2.CC_STAT_WIDTH])
        ch = int(stats[index, cv2.CC_STAT_HEIGHT])
        # Reward a large central product, penalise edge-hugging background islands.
        bbox_centrality = 1.0 if x0 < w * 0.5 < x0 + cw and y0 < h * 0.65 < y0 + ch else 0.72
        score = area * bbox_centrality * max(0.02, 1.0 - 0.55 * center_distance - 3.0 * border_ratio)
        if score > best_score:
            best_score = score
            best_index = index

    if best_index is None:
        return np.zeros((original_h, original_w), dtype=np.uint8), {
            "method": f"studio_background_model+component+{polarity}",
            "coverage_ratio": 0.0,
            "border_ratio": 0.0,
        }

    component = np.where(labels == best_index, 255, 0).astype(np.uint8)
    contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled_small = np.zeros_like(component)
    cv2.drawContours(filled_small, contours, -1, 255, -1)
    filled = cv2.resize(filled_small, (original_w, original_h), interpolation=cv2.INTER_LINEAR) if scale < 1.0 else filled_small
    filled = np.minimum(filled, original_alpha)
    if feather > 0:
        filled = cv2.GaussianBlur(filled, (0, 0), max(0.35, feather / 2.0))

    return filled, {
        "method": f"studio_background_model+component+{polarity}",
        "coverage_ratio": round(float((filled > 16).mean()), 6),
        "border_ratio": round(_mask_border_ratio(filled), 6),
        "background_gray_median": round(border_median, 3),
        "background_gray_p65": round(border_brightness, 3),
        "center_gray_median": round(center_median, 3),
        "probable_threshold": round(float(probable_threshold), 3),
        "sure_threshold": round(float(sure_threshold), 3) if sure_threshold is not None else None,
        "morphology_close_size": close_size,
        "inference_size": [w, h],
    }


@dataclass(frozen=True)
class AIInferenceResult:
    task: str
    model_id: str
    model_version: str
    confidence: float
    provider: str
    runtime_ms: float
    input_sha256: str
    output_sha256: str | None
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "confidence": round(float(self.confidence), 6),
            "provider": self.provider,
            "runtime_ms": round(float(self.runtime_ms), 3),
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "details": self.details,
        }


class AIEngine:
    def __init__(self) -> None:
        self.registry = AIModelRegistry()
        self.audit = AIAuditStore()
        self.feedback = AIFeedbackStore()
        self._lock = threading.RLock()

    def health(self) -> dict[str, Any]:
        health = self.registry.health()
        settings.ai_feedback_dir.mkdir(parents=True, exist_ok=True)
        health["feedback_modules"] = sorted(
            path.stem for path in settings.ai_feedback_dir.glob("*.jsonl")
            if path.is_file() and len(path.stem) <= 64
        )
        audit_integrity = self.audit.verify_all()
        health["audit_integrity"] = audit_integrity
        if any(not item.get("valid", False) for item in audit_integrity):
            health["status"] = "degraded"
            health["audit_warning"] = "Цепочка AI-аудита повреждена"
        return health

    @staticmethod
    def _ensure_ai_size(image: Image.Image, *, scale: int = 1) -> None:
        if scale < 1 or scale > 4:
            raise ValueError("AI scale must be between 1 and 4")
        target_pixels = int(image.width) * int(image.height) * scale * scale
        if target_pixels > settings.max_processing_pixels:
            raise ValueError(
                f"AI processing size exceeds safe limit: {target_pixels} pixels; "
                f"limit is {settings.max_processing_pixels}"
            )

    def _audit_result(self, module: str, result: AIInferenceResult) -> dict[str, Any]:
        payload = result.as_dict()
        self.audit.append({"module": module, **payload})
        return payload

    def analyze(self, image: Image.Image, *, module: str = "upload") -> dict[str, Any]:
        self._ensure_ai_size(image)
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        content_model = self.registry.softmax("content_classifier")
        content, content_confidence, content_probs = content_model.predict(features)
        quality_payload = self.registry.payload("quality_risk")
        risks: dict[str, float] = {}
        for name, payload in quality_payload["models"].items():
            probability = float(BinaryLogisticModel.from_payload(payload).predict_proba(features.reshape(1, -1))[0])
            risks[name] = probability
        max_risk = max(risks.values(), default=0.0)
        confidence = self.feedback.calibrate(module, features, content_confidence * (1.0 - 0.35 * max_risk))
        suitability = float(np.clip(confidence * (1.0 - 0.45 * max_risk), 0.0, 1.0))
        spec = self.registry.spec("content_classifier")
        result = AIInferenceResult(
            task="content_and_quality_analysis",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={
                "content": content,
                "content_probabilities": content_probs,
                "quality_risks": risks,
                "suitability": suitability,
                "features": features.tolist(),
                "warnings": [name for name, value in risks.items() if value >= 0.55],
            },
        )
        return self._audit_result(module, result)

    def recommend_restoration(self, image: Image.Image, *, module: str = "improve") -> dict[str, Any]:
        self._ensure_ai_size(image)
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        model = self.registry.softmax("restoration_profile")
        profile, confidence, probabilities = model.predict(features)
        confidence = self.feedback.calibrate(module, features, confidence)
        strengths = {
            "clean": {"blend": 0.15, "scale": 1},
            "deblur": {"blend": 0.75, "scale": 1},
            "denoise": {"blend": 0.65, "scale": 1},
            "contrast": {"blend": 0.35, "scale": 1},
            "compression": {"blend": 0.55, "scale": 1},
        }
        spec = self.registry.spec("restoration_profile")
        result = AIInferenceResult(
            task="restoration_profile",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={"profile": profile, "probabilities": probabilities, **strengths[profile], "features": features.tolist()},
        )
        return self._audit_result(module, result)

    def restore(self, image: Image.Image, *, scale: int = 1, strength: float | None = None, module: str = "improve") -> tuple[Image.Image, dict[str, Any]]:
        self._ensure_ai_size(image, scale=scale)
        started = time.perf_counter()
        recommendation = self.recommend_restoration(image, module=module)
        rgb, alpha = pil_to_rgb_alpha(image)
        if scale > 1:
            target = (rgb.shape[1] * scale, rgb.shape[0] * scale)
            rgb = cv2.resize(rgb, target, interpolation=cv2.INTER_CUBIC)
            alpha = cv2.resize(alpha, target, interpolation=cv2.INTER_CUBIC)
        model = self.registry.payload("tiny_restorer")
        coef = np.asarray(model["coef"], dtype=np.float32)
        intercept = np.asarray(model["intercept"], dtype=np.float32)
        work = rgb.astype(np.float32) / 255.0
        prediction = np.zeros_like(work, dtype=np.float32)
        for output_channel in range(3):
            channel_sum = np.full(work.shape[:2], intercept[output_channel], dtype=np.float32)
            for input_channel in range(3):
                kernel = coef[output_channel, :, :, input_channel]
                channel_sum += cv2.filter2D(work[:, :, input_channel], cv2.CV_32F, kernel, borderType=cv2.BORDER_REFLECT)
            prediction[:, :, output_channel] = channel_sum
        prediction = np.clip(prediction, 0.0, 1.0)
        requested_strength = float(recommendation["details"]["blend"] if strength is None else np.clip(strength, 0.0, 1.0))
        feedback_factor = self.feedback.adaptive_factor(module, np.asarray(recommendation["details"]["features"], dtype=np.float32), 0.18)
        requested_strength = float(np.clip(requested_strength * feedback_factor, 0.0, 1.0))
        profile = recommendation["details"]["profile"]
        # Keep a measurable learned contribution while using profile-specific,
        # deterministic stabilization to prevent the compact model from
        # over-correcting out-of-distribution photographs.
        learned_weight = float(np.clip(0.025 + requested_strength * 0.05, 0.025, 0.08))
        base = np.clip(work * (1.0 - learned_weight) + prediction * learned_weight, 0.0, 1.0)
        base_u8 = (base * 255.0).astype(np.uint8)
        postprocess = "learned_blend"
        if profile == "deblur":
            sigma = 1.45
            amount = 0.75 + requested_strength * 0.85
            blurred = cv2.GaussianBlur(base_u8.astype(np.float32), (0, 0), sigma)
            result_rgb = np.clip(base_u8.astype(np.float32) * (1.0 + amount) - blurred * amount, 0, 255).astype(np.uint8)
            postprocess = f"unsharp_sigma_{sigma}_amount_{amount:.3f}"
        elif profile == "denoise":
            kernel = 5 if requested_strength >= 0.45 else 3
            result_rgb = cv2.medianBlur(base_u8, kernel)
            postprocess = f"median_{kernel}"
        elif profile == "contrast":
            lab = cv2.cvtColor(base_u8, cv2.COLOR_RGB2LAB)
            clip = 1.4 + requested_strength * 0.9
            lab[:, :, 0] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(lab[:, :, 0])
            result_rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
            postprocess = f"clahe_{clip:.3f}"
        elif profile == "compression":
            filtered = cv2.medianBlur(base_u8, 3)
            blurred = cv2.GaussianBlur(filtered.astype(np.float32), (0, 0), 0.8)
            result_rgb = np.clip(filtered.astype(np.float32) * 1.45 - blurred * 0.45, 0, 255).astype(np.uint8)
            postprocess = "median3+light_unsharp"
        else:
            result_rgb = base_u8
        rgba = np.dstack([result_rgb, alpha])
        output = Image.fromarray(rgba, "RGBA")
        spec = self.registry.spec("tiny_restorer")
        confidence = float(recommendation["confidence"])
        result = AIInferenceResult(
            task="learned_restoration",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy-convolution+profile-stabilizer",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=_image_hash(output),
            details={
                "profile": profile,
                "requested_strength": requested_strength,
                "feedback_factor": feedback_factor,
                "learned_weight": learned_weight,
                "postprocess": postprocess,
                "scale": scale,
                "training_mse": model.get("training_mse"),
                "features": recommendation["details"]["features"],
            },
        )
        return output, self._audit_result(module, result)

    def _probability_map(self, image: Image.Image, model_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
        rgb, source_alpha = pil_to_rgb_alpha(image)
        original_size = (rgb.shape[1], rgb.shape[0])
        max_side = max(original_size)
        scale = min(1.0, 640.0 / max_side)
        if scale < 1.0:
            inference_size = (max(8, int(round(original_size[0] * scale))), max(8, int(round(original_size[1] * scale))))
            small = cv2.resize(rgb, inference_size, interpolation=cv2.INTER_AREA)
        else:
            small = rgb
        features = pixel_features(small)
        model = self.registry.binary(model_id)
        probability_small = model.predict_proba(features).reshape(small.shape[:2])
        if probability_small.shape != source_alpha.shape:
            probability = cv2.resize(probability_small, original_size, interpolation=cv2.INTER_LINEAR)
        else:
            probability = probability_small
        probability = np.clip(probability, 0.0, 1.0)
        return probability, source_alpha, rgb, [small.shape[1], small.shape[0]]

    def _segment(self, image: Image.Image, model_id: str, *, threshold: float, feather: float, keep_largest: bool, module: str) -> tuple[np.ndarray, dict[str, Any]]:
        self._ensure_ai_size(image)
        started = time.perf_counter()
        probability, source_alpha, rgb, inference_size = self._probability_map(image, model_id)
        features = image_features(rgb, source_alpha)
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.12)
        effective_threshold = float(np.clip(threshold / feedback_factor, 0.20, 0.80))
        mask = _normalize_mask(probability, effective_threshold, feather=feather, keep_largest=keep_largest)
        mask = np.minimum(mask, source_alpha)
        coverage = float((mask > 16).mean())
        selected = probability[mask > 16]
        mean_probability = float(selected.mean()) if selected.size else 0.0
        confidence = self.feedback.calibrate(module, features, mean_probability)
        spec = self.registry.spec(model_id)
        result = AIInferenceResult(
            task=f"{model_id}_segmentation",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy-pixel-model",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=_array_hash(mask),
            details={
                "threshold": threshold,
                "effective_threshold": effective_threshold,
                "feedback_factor": feedback_factor,
                "coverage_ratio": coverage,
                "mean_probability": mean_probability,
                "inference_size": inference_size,
                "features": features.tolist(),
            },
        )
        return mask, self._audit_result(module, result)

    def segment_subject(self, image: Image.Image, *, threshold: float = 0.5, feather: float = 1.5, module: str = "cleanup") -> tuple[np.ndarray, dict[str, Any]]:
        self._ensure_ai_size(image)
        started = time.perf_counter()
        probability, source_alpha, rgb, inference_size = self._probability_map(image, "pixel_subject")
        features = image_features(rgb, source_alpha)
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.10)
        effective_threshold = float(np.clip(threshold / feedback_factor, 0.28, 0.72))
        # Keep the learned refinement thread-safe. OpenCV GrabCut can stall when
        # repeated requests are executed by different ASGI worker threads, so the
        # probability map is refined with deterministic morphology instead.
        learned_binary = np.where(
            (probability >= effective_threshold) & (source_alpha > 8),
            255,
            0,
        ).astype(np.uint8)
        learned_binary = cv2.morphologyEx(
            learned_binary,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            iterations=1,
        )
        learned_binary = cv2.morphologyEx(
            learned_binary,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=1,
        )
        learned_mask = _normalize_mask(learned_binary.astype(np.float32) / 255.0, 0.5, feather=0.0, keep_largest=True)
        learned_mask = np.minimum(learned_mask, source_alpha)
        learned_coverage = float((learned_mask > 16).mean())
        learned_border = _mask_border_ratio(learned_mask)

        fallback_mask = None
        fallback_details: dict[str, Any] = {}
        learned_implausible = learned_coverage > 0.82 or learned_coverage < 0.03 or learned_border > 0.055
        opaque_source = float((source_alpha > 16).mean()) > 0.98
        # On opaque studio photographs, compare the learned mask with a border-
        # background model even when the learned coverage is superficially valid.
        # This catches under-segmentation without applying the studio assumption to
        # already-transparent derived assets.
        if learned_implausible or opaque_source:
            fallback_mask, fallback_details = _studio_subject_fallback(image, feather=0.0)
        use_fallback = False
        if fallback_mask is not None:
            fallback_coverage = float((fallback_mask > 16).mean())
            fallback_border = _mask_border_ratio(fallback_mask)
            plausible = 0.04 <= fallback_coverage <= 0.90
            materially_fuller = fallback_coverage >= learned_coverage * 1.035
            cleaner_boundary = fallback_border + 0.006 < learned_border
            no_boundary_regression = fallback_border <= learned_border + 0.005
            improved = learned_implausible or cleaner_boundary or (materially_fuller and no_boundary_regression)
            if plausible and improved:
                use_fallback = True
        mask = fallback_mask if use_fallback else learned_mask
        refinement = fallback_details.get("method", "studio_background_model") if use_fallback else "model-probability+morphology"
        if feather > 0:
            mask = cv2.GaussianBlur(mask, (0, 0), max(0.35, feather / 2.0))
        mask = np.minimum(mask, source_alpha)
        coverage = float((mask > 16).mean())
        border_ratio = _mask_border_ratio(mask)
        mean_probability = float(probability[mask > 16].mean()) if np.any(mask > 16) else 0.0
        confidence = self.feedback.calibrate(module, features, mean_probability)
        spec = self.registry.spec("pixel_subject")
        result = AIInferenceResult(
            task="subject_segmentation_ai_refined",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy-pixel-model+deterministic-refinement",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=_array_hash(mask),
            details={
                "threshold": threshold,
                "coverage_ratio": coverage,
                "border_ratio": border_ratio,
                "mean_probability": mean_probability,
                "inference_size": inference_size,
                "refinement": refinement,
                "learned_coverage_ratio": learned_coverage,
                "learned_border_ratio": learned_border,
                "fallback": fallback_details,
                "features": features.tolist(),
            },
        )
        return mask, self._audit_result(module, result)

    def segment_print(self, image: Image.Image, *, threshold: float = 0.48, feather: float = 0.8, module: str = "extract") -> tuple[np.ndarray, dict[str, Any]]:
        self._ensure_ai_size(image)
        started = time.perf_counter()
        subject, subject_ai = self.segment_subject(image, threshold=0.42, feather=0.0, module=module)
        probability, source_alpha, rgb, inference_size = self._probability_map(image, "pixel_print")
        subject_pixels = subject > 16
        if int(subject_pixels.sum()) < 30:
            raise AIModelError("Маска изделия пуста; извлечение принта невозможно")
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1].astype(np.float32)
        value = hsv[:, :, 2].astype(np.float32)
        fabric_center = _dominant_lab_center(lab[subject_pixels])
        fabric_distance = np.linalg.norm(lab - fabric_center[None, None, :], axis=2)
        garment_value = float(np.median(value[subject_pixels]))
        garment_saturation = float(np.median(saturation[subject_pixels]))
        distance_score = np.clip((fabric_distance - 5.0) / 30.0, 0.0, 1.0)
        value_score = np.clip(np.abs(value - garment_value) / 82.0, 0.0, 1.0)
        saturation_score = np.clip(np.abs(saturation - garment_saturation) / 140.0, 0.0, 1.0)
        # Low-contrast prints need stronger fabric-distance evidence, while the
        # coherent-component filters below continue rejecting distributed fabric
        # texture and stripes.
        fused = np.clip(probability * 0.20 + distance_score * 0.60 + value_score * 0.15 + saturation_score * 0.05, 0.0, 1.0)
        inner_subject = cv2.erode(subject_pixels.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=1).astype(bool)
        fused *= inner_subject.astype(np.float32)
        features = image_features(rgb, source_alpha)
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.12)
        effective_threshold = float(np.clip((threshold * 0.42) / feedback_factor, 0.16, 0.60))
        mask = np.where(fused >= effective_threshold, 255, 0).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)

        # Strong pigment seeds distinguish a real solid graphic from repetitive
        # garment texture. If a compact strong graphic occupies a meaningful area,
        # use that high-confidence mask directly. Otherwise keep the sensitive
        # low-contrast candidate; elongated stripe components are rejected below.
        seed_threshold = 0.58
        seed = np.where(fused >= seed_threshold, 255, 0).astype(np.uint8)
        seed = cv2.morphologyEx(seed, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
        seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        seed_count, seed_labels, seed_stats, _ = cv2.connectedComponentsWithStats((seed > 16).astype(np.uint8), 8)
        seed_boxes: list[tuple[int, int, int, int, int]] = []
        for seed_index in range(1, seed_count):
            sx, sy, sw, sh, sa = [int(v) for v in seed_stats[seed_index, :5]]
            seed_aspect = max(sw / max(1, sh), sh / max(1, sw))
            if sa >= max(12, int(image.width * image.height * 0.00008)) and seed_aspect <= 8.0:
                seed_boxes.append((sx, sy, sw, sh, sa))
        strong_seed_area = max((item[4] for item in seed_boxes), default=0)
        seed_envelope_used = strong_seed_area >= int(image.width * image.height * 0.05)
        if seed_envelope_used:
            primary_seed = max(seed_boxes, key=lambda item: item[4])
            primary_index = next(
                index for index in range(1, seed_count)
                if tuple(int(v) for v in seed_stats[index, :5]) == primary_seed
            )
            mask = np.where(seed_labels == primary_index, 255, 0).astype(np.uint8)

        count, labels, stats, centers = cv2.connectedComponentsWithStats((mask > 16).astype(np.uint8), 8)
        subject_area = max(1, int(subject_pixels.sum()))
        components: list[tuple[float, int]] = []
        image_center = np.array([image.width / 2.0, image.height / 2.0])
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < max(12, int(image.width * image.height * 0.00008)):
                continue
            x, y, width, height = [int(v) for v in stats[index, :4]]
            component = labels == index
            inner_ratio = float((component & inner_subject).sum()) / max(1, area)
            area_ratio = area / subject_area
            fill_ratio = area / max(1, width * height)
            aspect = max(width / max(1, height), height / max(1, width))
            center_distance = float(np.linalg.norm((centers[index] - image_center) / np.array([max(1, image.width), max(1, image.height)])))
            if inner_ratio < 0.94 or area_ratio > 0.62 or fill_ratio < 0.08 or aspect > 12.0:
                continue
            score = area * (1.0 - min(0.65, center_distance))
            components.append((score, index))
        if not components:
            cleaned = np.zeros_like(mask)
        else:
            components.sort(reverse=True)
            primary_index = components[0][1]
            px, py, pw, ph = [int(v) for v in stats[primary_index, :4]]
            margin = max(12, int(round(max(pw, ph) * 0.18)))
            cleaned = np.zeros_like(mask)
            for _, index in components:
                x, y, width, height = [int(v) for v in stats[index, :4]]
                overlaps_neighborhood = not (x + width < px - margin or x > px + pw + margin or y + height < py - margin or y > py + ph + margin)
                if overlaps_neighborhood:
                    cleaned[labels == index] = 255
        mask = cleaned
        # Recover enclosed dark ink while leaving outside-connected garment pixels transparent.
        mask, filled_hole_pixels = _fill_enclosed_holes(mask)
        mask = np.minimum(mask, subject)
        if feather > 0:
            mask = cv2.GaussianBlur(mask, (0, 0), max(0.35, feather / 2.0))
            mask = np.minimum(mask, subject)
        coverage = float((mask > 16).mean())
        outside_subject = float(((mask > 16) & ~subject_pixels).sum()) / max(1, int((mask > 16).sum()))
        border_ratio = _mask_border_ratio(mask)
        mean_probability = float(probability[mask > 16].mean()) if np.any(mask > 16) else 0.0
        confidence = self.feedback.calibrate(module, features, max(mean_probability, 0.55 if coverage > 0.002 else 0.0))
        spec = self.registry.spec("pixel_print")
        result = AIInferenceResult(
            task="print_segmentation_ai_garment_gated",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy-pixel-model+garment-gated-pigment-refinement",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=_array_hash(mask),
            details={
                "threshold": threshold,
                "effective_threshold": effective_threshold,
                "seed_threshold": seed_threshold,
                "seed_envelope_used": seed_envelope_used,
                "feedback_factor": feedback_factor,
                "coverage_ratio": coverage,
                "outside_subject_ratio": outside_subject,
                "border_ratio": border_ratio,
                "filled_hole_pixels": filled_hole_pixels,
                "mean_probability": mean_probability,
                "inference_size": inference_size,
                "garment_lab": [round(float(v), 3) for v in fabric_center],
                "garment_value": round(garment_value, 3),
                "garment_saturation": round(garment_saturation, 3),
                "subject_ai": {"model_id": subject_ai["model_id"], "model_version": subject_ai["model_version"], "confidence": subject_ai["confidence"], "details": subject_ai.get("details", {})},
                "features": features.tolist(),
            },
        )
        return mask, self._audit_result(module, result)

    def recommend_halftone(self, image: Image.Image, *, module: str = "halftone") -> dict[str, Any]:
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        model = self.registry.softmax("halftone_recommender")
        raster, confidence, probabilities = model.predict(features)
        confidence = self.feedback.calibrate(module, features, confidence)
        entropy = float(features[15])
        edge_density = float(features[11])
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.18)
        dot_size_mm = float(np.clip((0.45 - entropy * 0.13 + edge_density * 0.2) / feedback_factor, 0.10, 0.55))
        density = float(np.clip((72 + entropy * 15 - edge_density * 8) * feedback_factor, 55, 95))
        angle = 22.5 if raster == "dot" else (45.0 if raster == "line" else 30.0)
        spec = self.registry.spec("halftone_recommender")
        result = AIInferenceResult(
            task="halftone_recommendation",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={
                "raster": raster,
                "probabilities": probabilities,
                "size_mm": round(dot_size_mm, 3),
                "density": round(density, 2),
                "angle": angle,
                "feedback_factor": feedback_factor,
                "features": features.tolist(),
            },
        )
        return self._audit_result(module, result)

    def recommend_vector(self, image: Image.Image, *, module: str = "vector") -> dict[str, Any]:
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        values = self.registry.regression("vector_recommender").predict(features)
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.20)
        colors = int(np.clip(round(values["colors"] * feedback_factor), 2, 16))
        simplify = float(np.clip(values["simplify"] / feedback_factor, 0.2, 12.0))
        confidence = self.feedback.calibrate(module, features, 0.76)
        spec = self.registry.spec("vector_recommender")
        result = AIInferenceResult(
            task="vector_recommendation",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={"colors": colors, "simplify": round(simplify, 3), "feedback_factor": feedback_factor, "features": features.tolist()},
        )
        return self._audit_result(module, result)

    def recommend_size(self, image: Image.Image, *, module: str = "geometry") -> dict[str, Any]:
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        predicted = self.registry.regression("size_assistant").predict(features)
        mask, segmentation = self.segment_subject(image, threshold=0.45, feather=0.0, module=module)
        ys, xs = np.nonzero(mask > 16)
        if len(xs):
            actual = {
                "left": float(xs.min() / image.width),
                "top": float(ys.min() / image.height),
                "right": float((image.width - 1 - xs.max()) / image.width),
                "bottom": float((image.height - 1 - ys.max()) / image.height),
            }
        else:
            actual = {key: 0.0 for key in ("left", "top", "right", "bottom")}
        feedback_factor = self.feedback.adaptive_factor(module, features, 0.15)
        margins = {key: float(np.clip((actual[key] * 0.75 + predicted[key] * 0.25) / feedback_factor, 0.0, 0.45)) for key in actual}
        confidence = self.feedback.calibrate(module, features, float(segmentation["confidence"]))
        spec = self.registry.spec("size_assistant")
        result = AIInferenceResult(
            task="layout_assistant",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={"safe_margins": margins, "feedback_factor": feedback_factor, "features": features.tolist()},
        )
        return self._audit_result(module, result)

    def recommend_export(self, image: Image.Image, *, module: str = "export") -> dict[str, Any]:
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = image_features(rgb, alpha)
        model = self.registry.softmax("export_recommender")
        preset, confidence, probabilities = model.predict(features)
        acceptance_score = self.feedback.acceptance_score(module, features, 0.5)
        if acceptance_score < 0.28:
            preset = "dtf_png"
        confidence = self.feedback.calibrate(module, features, confidence)
        mapping = {
            "dtf_png": {"format": "PNG_DTF", "quality": 100, "keep_alpha": True},
            "marketplace_webp": {"format": "WEBP", "quality": 92, "keep_alpha": False},
            "vector_svg": {"format": "SVG", "quality": 100, "keep_alpha": True},
        }
        spec = self.registry.spec("export_recommender")
        result = AIInferenceResult(
            task="export_recommendation",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={"preset": preset, "probabilities": probabilities, "acceptance_score": acceptance_score, **mapping[preset], "features": features.tolist()},
        )
        return self._audit_result(module, result)

    def preflight(self, image: Image.Image, operation: str, *, module: str = "qa") -> dict[str, Any]:
        """Run learned anomaly scoring plus deterministic fail-closed gates.

        The learned score is evidence and warning signal. Hard blocking is based on
        operation-specific measurable defects so an out-of-distribution but valid
        file is not rejected solely by a synthetic anomaly model.
        """
        started = time.perf_counter()
        rgb, alpha = pil_to_rgb_alpha(image)
        features = operation_qa_features(rgb, alpha, operation)
        model = self.registry.binary("qa_anomaly")
        anomaly_probability = float(model.predict_proba(features.reshape(1, -1))[0])
        coverage = float((alpha > 16).mean())
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        visible = alpha > 16
        visible_gray = gray[visible]
        if visible_gray.size:
            gray_std = float(visible_gray.std())
            unique_levels = int(np.unique(visible_gray).size)
            dark_ratio = float((visible_gray < 224).mean())
            bright_ratio = float((visible_gray > 245).mean())
        else:
            gray_std = 0.0
            unique_levels = 0
            dark_ratio = 0.0
            bright_ratio = 0.0
        edges = binary_edge_map(gray, 20)
        edge_density = float((edges & visible).sum() / max(1, int(visible.sum())))
        alpha_edge_density = float(binary_edge_map(alpha, 20).mean())
        hard_fail_reasons: list[str] = []
        warning_reasons: list[str] = []

        if operation in {"background", "extract_print"}:
            if coverage < 0.001:
                hard_fail_reasons.append("empty_mask")
            upper = 0.94 if operation == "extract_print" else 0.985
            if coverage > upper:
                hard_fail_reasons.append("full_mask")
            if 0.001 <= coverage <= upper and alpha_edge_density < 0.00005:
                warning_reasons.append("weak_mask_boundary")

        if operation == "halftone":
            # Transparent monochrome halftones legitimately have one RGB value;
            # their structure is encoded by alpha. Opaque halftones are assessed
            # through luminance instead.
            if coverage < 0.002:
                hard_fail_reasons.append("empty_halftone")
            if coverage > 0.92:
                hard_fail_reasons.append("overfilled_halftone")
            if coverage < 0.999:
                if alpha_edge_density < 0.0005:
                    hard_fail_reasons.append("no_raster_structure")
            else:
                if unique_levels < 2 or gray_std < 4.0:
                    hard_fail_reasons.append("near_solid_halftone")
                if edge_density < 0.0005:
                    hard_fail_reasons.append("no_raster_structure")

        if operation in {"export", "enhance", "reconstruct", "cleanup", "geometry", "color"}:
            if image.width <= 0 or image.height <= 0:
                hard_fail_reasons.append("invalid_dimensions")
            if alpha.max() == 0:
                hard_fail_reasons.append("fully_transparent_output")

        # The compact anomaly model was trained on bounded synthetic examples.
        # High score is retained as a warning unless an objective gate also fails.
        if anomaly_probability >= 0.90:
            warning_reasons.append("high_model_anomaly")
        passed = not hard_fail_reasons
        confidence = float(np.clip(abs(anomaly_probability - 0.5) * 2.0, 0.0, 1.0))
        spec = self.registry.spec("qa_anomaly")
        result = AIInferenceResult(
            task="visual_preflight",
            model_id=spec.id,
            model_version=spec.version,
            confidence=confidence,
            provider="CPU/numpy",
            runtime_ms=(time.perf_counter() - started) * 1000,
            input_sha256=_image_hash(image),
            output_sha256=None,
            details={
                "operation": operation,
                "passed": passed,
                "anomaly_probability": anomaly_probability,
                "coverage_ratio": coverage,
                "gray_std": gray_std,
                "unique_gray_levels": unique_levels,
                "dark_ratio": dark_ratio,
                "bright_ratio": bright_ratio,
                "edge_density": edge_density,
                "alpha_edge_density": alpha_edge_density,
                "hard_fail_reasons": hard_fail_reasons,
                "warning_reasons": warning_reasons,
                "features": features.tolist(),
            },
        )
        return self._audit_result(module, result)

    def explain(self, image: Image.Image, operation: str | None = None) -> dict[str, Any]:
        analysis = self.analyze(image, module="information")
        content = analysis["details"]["content"]
        warnings = analysis["details"]["warnings"]
        phrases = {
            "garment": "ИИ распознал изображение изделия или одежды.",
            "product": "ИИ распознал предметное изображение товара.",
            "print": "ИИ распознал отдельный принт или графический объект.",
        }
        explanation = phrases.get(content, "ИИ не смог уверенно определить тип изображения.")
        if warnings:
            explanation += " Обнаружены риски: " + ", ".join(warnings) + "."
        else:
            explanation += " Существенные риски качества не обнаружены."
        if operation:
            explanation += f" Рекомендуется проверить результат операции «{operation}» через AI-preflight."
        return {
            "text": explanation,
            "confidence": analysis["confidence"],
            "evidence": {
                "model_id": analysis["model_id"],
                "content_probabilities": analysis["details"]["content_probabilities"],
                "quality_risks": analysis["details"]["quality_risks"],
            },
        }


_ENGINE: AIEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_ai_engine() -> AIEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = AIEngine()
        return _ENGINE
