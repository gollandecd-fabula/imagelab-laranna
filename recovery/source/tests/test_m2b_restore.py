from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.services import restore_fidelity


ROOT = Path(__file__).resolve().parents[1]


def _reference() -> Image.Image:
    image = Image.new("RGB", (192, 192), (242, 241, 237))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 174, 174), radius=22, fill=(38, 39, 42), outline=(10, 10, 12), width=4)
    draw.rectangle((33, 48, 159, 86), fill=(215, 52, 72))
    draw.ellipse((48, 104, 94, 150), fill=(28, 134, 182))
    draw.polygon(((112, 149), (137, 103), (163, 149)), fill=(239, 174, 49))
    draw.line((35, 162, 157, 162), fill=(235, 235, 230), width=4)
    return image


def _psnr(a: Image.Image, b: Image.Image) -> float:
    left = np.asarray(a.convert("RGB"), dtype=np.float32)
    right = np.asarray(b.convert("RGB"), dtype=np.float32)
    mse = float(np.mean((left - right) ** 2))
    if mse <= 0:
        return float("inf")
    return 10.0 * np.log10((255.0 * 255.0) / mse)


def _digest(image: Image.Image) -> str:
    return hashlib.sha256(np.asarray(image.convert("RGBA"), dtype=np.uint8).tobytes()).hexdigest()


class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def restore(self, image: Image.Image, *, scale: int, strength, module: str):
        self.calls.append({"scale": scale, "strength": strength, "module": module})
        result = image.convert("RGBA").resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
        return result, {"task": "fake-general-restore", "details": {}}


def test_profile_selection_uses_declared_controls_not_case_identity() -> None:
    assert restore_fidelity._profile_from_controls({"detail": 45, "denoise": 10, "preserve_text_logo": True}) == "lowres"
    assert restore_fidelity._profile_from_controls({"detail": 50, "denoise": 20, "preserve_text_logo": True}) == "jpeg"
    assert restore_fidelity._profile_from_controls({"detail": 60, "denoise": 5, "preserve_text_logo": True}) == "blur"
    assert restore_fidelity._profile_from_controls({"detail": 40, "denoise": 55, "preserve_text_logo": True}) == "noise"
    assert restore_fidelity._profile_from_controls({"detail": 50, "denoise": 10, "preserve_text_logo": True}) == "text_logo"


def test_flat_restore_is_conservative_deterministic_and_improves_lowres() -> None:
    reference = _reference()
    source = reference.resize((96, 96), Image.Resampling.BICUBIC)
    baseline = source.resize(reference.size, Image.Resampling.BICUBIC)
    params = {"scale": 2, "detail": 45, "denoise": 10, "preserve_text_logo": True}
    engine = _FakeEngine()

    first, ai_first = restore_fidelity.restore_with_diagnostics(source, params, engine)
    second, ai_second = restore_fidelity.restore_with_diagnostics(source, params, engine)

    assert first.size == reference.size
    assert engine.calls == []
    assert _digest(first) == _digest(second)
    assert _psnr(first, reference) >= 25.0
    assert _psnr(first, reference) > _psnr(baseline, reference)
    for ai in (ai_first, ai_second):
        details = ai["details"]
        assert details["strategy"] == "bounded_flat_art_inverse_restoration"
        assert details["preserve_text_logo_enforced"] is True
        assert details["exact_recovery_claimed"] is False
        assert details["result_status"] == "REVIEW"
        assert details["suitability"]["accepted"] is True


def test_kmeans_profiles_are_repeatable_without_reference_data() -> None:
    reference = _reference()
    source = reference.resize((96, 96), Image.Resampling.BICUBIC)
    engine = _FakeEngine()
    profiles = (
        {"scale": 2, "detail": 60, "denoise": 5, "preserve_text_logo": True},
        {"scale": 2, "detail": 50, "denoise": 20, "preserve_text_logo": True},
    )
    for params in profiles:
        first, _ = restore_fidelity.restore_with_diagnostics(source, params, engine)
        second, _ = restore_fidelity.restore_with_diagnostics(source, params, engine)
        assert _digest(first) == _digest(second)
    assert engine.calls == []


def test_general_or_non_scale2_inputs_fail_over_to_existing_engine() -> None:
    rng = np.random.default_rng(20260816)
    photo_like = Image.fromarray(rng.integers(0, 256, (96, 96, 3), dtype=np.uint8), "RGB")
    engine = _FakeEngine()
    result, ai = restore_fidelity.restore_with_diagnostics(
        photo_like,
        {"scale": 2, "detail": 45, "denoise": 10, "preserve_text_logo": True},
        engine,
    )
    assert result.size == (192, 192)
    assert len(engine.calls) == 1
    details = ai["details"]["restore_fidelity"]
    assert details["strategy"] == "existing_general_restore_fallback"
    assert details["exact_recovery_claimed"] is False
    assert details["result_status"] == "REVIEW"

    flat = _reference().resize((64, 64), Image.Resampling.BICUBIC)
    result, _ = restore_fidelity.restore_with_diagnostics(
        flat,
        {"scale": 3, "detail": 45, "denoise": 10, "preserve_text_logo": True},
        engine,
    )
    assert result.size == (192, 192)
    assert len(engine.calls) == 2


def test_restore_source_contains_no_frozen_case_or_ground_truth_binding() -> None:
    source = (ROOT / "app/services/restore_fidelity.py").read_text("utf-8")
    lowered = source.lower()
    forbidden = (
        "rs-",
        "ground_truth",
        "reference.png",
        "imagelab-m2b-benchmark",
        "benchmark/v5",
        "case_id",
    )
    assert not any(marker in lowered for marker in forbidden)
