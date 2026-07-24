from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from app.ai.runtime import _bounded_adjacent_support, get_ai_engine


def _scene() -> Image.Image:
    image = Image.new("RGBA", (180, 160), (230, 232, 235, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((22, 12, 158, 150), radius=18, fill=(55, 65, 80, 255))
    draw.ellipse((62, 48, 118, 106), fill=(225, 60, 35, 255))
    return image


def test_feedback_cannot_move_subject_or_print_geometry(monkeypatch) -> None:
    engine = get_ai_engine()
    image = _scene()
    monkeypatch.setattr(engine.feedback, "adaptive_factor", lambda *_args, **_kwargs: 0.2)
    subject_low, subject_low_ai = engine.segment_subject(image, threshold=0.50, feather=0, module="governance")
    print_low, print_low_ai = engine.segment_print(image, threshold=0.48, feather=0, module="governance")
    monkeypatch.setattr(engine.feedback, "adaptive_factor", lambda *_args, **_kwargs: 5.0)
    subject_high, subject_high_ai = engine.segment_subject(image, threshold=0.50, feather=0, module="governance")
    print_high, print_high_ai = engine.segment_print(image, threshold=0.48, feather=0, module="governance")
    assert np.array_equal(subject_low, subject_high)
    assert np.array_equal(print_low, print_high)
    assert subject_low_ai["details"]["threshold"] == subject_high_ai["details"]["threshold"] == 0.50
    assert print_low_ai["details"]["effective_threshold"] == print_high_ai["details"]["effective_threshold"]


def test_support_is_adjacent_and_hard_capped_to_fifteen_percent() -> None:
    base = np.zeros((30, 30), dtype=np.uint8)
    base[10:20, 10:20] = 255  # 100 authoritative pixels
    score = np.ones((30, 30), dtype=np.float32)
    subject = np.ones((30, 30), dtype=bool)
    result, added, cap = _bounded_adjacent_support(base, score, subject, threshold=0.5, cap_ratio=0.15)
    assert cap == 15
    assert added == 15
    actual_added = (result > 16) & ~(base > 16)
    adjacent = __import__("cv2").dilate((base > 16).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    assert np.all(actual_added <= adjacent)
