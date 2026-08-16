from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from app.services import extract_fidelity


def _striped_fabric(size=(192, 192)) -> Image.Image:
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width]
    base = np.zeros((height, width, 4), dtype=np.uint8)
    wave = (8.0 * np.sin(xx / 4.5) + 4.0 * np.sin(xx / 13.0)).astype(np.int16)
    base[:, :, 0] = np.clip(150 + wave, 0, 255)
    base[:, :, 1] = np.clip(125 + wave, 0, 255)
    base[:, :, 2] = np.clip(96 + wave, 0, 255)
    base[:, :, 3] = 255
    return Image.fromarray(base, "RGBA")


def test_fidelity_path_requires_non_identity_perspective() -> None:
    image = _striped_fabric()
    assert extract_fidelity._fidelity_extract(image, {"mode": "auto"}) is None
    assert extract_fidelity._fidelity_extract(
        image,
        {"mode": "auto", "perspective": [[0, 0], [100, 0], [100, 100], [0, 100]]},
    ) is None


def test_dense_black_and_white_are_not_globally_deleted() -> None:
    image = _striped_fabric()
    draw = ImageDraw.Draw(image)
    draw.rectangle((52, 48, 93, 105), fill=(10, 10, 10, 255))
    draw.ellipse((105, 58, 148, 103), fill=(250, 250, 250, 255))
    solved = extract_fidelity._fidelity_extract(
        image,
        {"mode": "auto", "perspective": [[5, 4], [95, 3], [96, 95], [4, 96]], "crop_output": False},
    )
    assert solved is not None
    result, diagnostics = solved
    rgba = np.asarray(result)
    alpha = rgba[:, :, 3] >= 128
    assert diagnostics["global_black_white_deletion"] is False
    assert diagnostics["target_size_consumed"] is False
    # Both dark and light pigment must survive in visible print pixels.
    visible = rgba[:, :, :3][alpha]
    assert np.any(np.mean(visible, axis=1) < 45)
    assert np.any(np.mean(visible, axis=1) > 220)


def test_sparse_strokes_use_bounded_decontamination_and_keep_dimensions() -> None:
    image = _striped_fabric()
    draw = ImageDraw.Draw(image)
    for y, color in ((58, (225, 35, 55, 255)), (78, (10, 10, 10, 255)), (98, (35, 125, 220, 255))):
        draw.line((42, y, 150, y), fill=color, width=3)
    solved = extract_fidelity._fidelity_extract(
        image,
        {"mode": "auto", "perspective": [[6, 5], [94, 4], [95, 94], [5, 95]], "crop_output": False},
    )
    assert solved is not None
    result, diagnostics = solved
    assert result.size == image.size
    assert diagnostics["sparse_print_path"] is True
    assert diagnostics["coverage_ratio"] < 0.15
    assert diagnostics["fabric_suppression"] == "border_model_mask+sparse_bounded_decontamination"
    alpha = np.asarray(result.getchannel("A"))
    assert 0.002 <= float(np.mean(alpha >= 128)) < 0.15


def test_fidelity_path_does_not_use_external_size_target() -> None:
    image = _striped_fabric()
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((45, 45, 145, 145), radius=12, fill=(225, 35, 55, 255))
    base = {"mode": "auto", "perspective": [[5, 5], [95, 4], [96, 95], [4, 96]], "crop_output": False}
    first = extract_fidelity._fidelity_extract(image, dict(base))
    second = extract_fidelity._fidelity_extract(image, {**base, "target_size": [37, 91]})
    assert first is not None and second is not None
    a, da = first; b, db = second
    assert a.size == b.size == image.size
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert da["target_size_consumed"] is False and db["target_size_consumed"] is False
