from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services.image_processing import ProcessingError
from app.services.vector_fidelity import vectorize_with_diagnostics


_TOKEN_RE = re.compile(r"([MLHVZmlhvz]|-?\d+(?:\.\d+)?)")


def _independent_rasterize(svg: str, size: tuple[int, int]) -> Image.Image:
    """Independent strict rasterizer for the small SVG subset emitted by ImageLab."""
    low = svg.lower()
    assert "<script" not in low
    assert "javascript:" not in low
    assert "xlink:href" not in low
    assert "<image" not in low
    assert "base64" not in low
    root = ET.fromstring(svg)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for element in root.iter():
        if element.tag.split("}")[-1] != "path":
            continue
        fill = element.attrib.get("fill", "#000000").lstrip("#")
        color = tuple(int(fill[index : index + 2], 16) for index in (0, 2, 4)) + (255,)
        tokens = _TOKEN_RE.findall(element.attrib.get("d", ""))
        index = 0
        current = (0.0, 0.0)
        polygon: list[tuple[float, float]] = []

        def flush() -> None:
            nonlocal polygon
            if len(polygon) >= 3:
                draw.polygon(polygon, fill=color)
            polygon = []

        while index < len(tokens):
            token = tokens[index]
            index += 1
            command = token.upper()
            if command == "M":
                flush()
                current = (float(tokens[index]), float(tokens[index + 1]))
                index += 2
                polygon = [current]
            elif command == "L":
                current = (float(tokens[index]), float(tokens[index + 1]))
                index += 2
                polygon.append(current)
            elif command == "H":
                current = (float(tokens[index]), current[1])
                index += 1
                polygon.append(current)
            elif command == "V":
                current = (current[0], float(tokens[index]))
                index += 1
                polygon.append(current)
            elif command == "Z":
                flush()
            else:  # pragma: no cover - generated subset never reaches this
                raise AssertionError(f"unsupported path command: {token}")
        flush()
    return image


def _flat_art() -> Image.Image:
    image = Image.new("RGBA", (48, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 35, 31), fill=(45, 180, 95, 255))
    draw.rectangle((12, 10, 27, 25), fill=(0, 0, 0, 0))
    draw.line((2, 36, 44, 36), fill=(220, 40, 55, 255), width=1)
    draw.line((44, 2, 44, 36), fill=(30, 125, 210, 255), width=1)
    return image


def test_f07_lossless_flat_art_preserves_holes_thin_lines_and_palette() -> None:
    source = _flat_art()
    svg, diagnostics = vectorize_with_diagnostics(
        source,
        {"mode": "color", "colors": 6, "simplify": 1.2, "min_area": 2, "complexity": 70},
    )
    rerendered = _independent_rasterize(svg, source.size)
    assert np.array_equal(np.asarray(rerendered), np.asarray(source))
    assert diagnostics["strategy"] == "lossless_flat_art_runs"
    assert diagnostics["quality_score"] == 1.0
    assert diagnostics["suitability"]["photo_like_blocked"] is False
    assert 'fill-rule="evenodd"' in svg


def test_f07_fidelity_fallback_is_recorded_instead_of_silent_recolor() -> None:
    source = _flat_art()
    svg, diagnostics = vectorize_with_diagnostics(
        source,
        {"mode": "mono", "colors": 2, "simplify": 1.2, "min_area": 2},
    )
    rerendered = _independent_rasterize(svg, source.size)
    assert np.array_equal(np.asarray(rerendered), np.asarray(source))
    assert diagnostics["requested_mode"] == "mono"
    assert diagnostics["effective_palette"] == "source_preserving"
    assert diagnostics["fidelity_fallback_recorded"] is True


def test_f07_suitability_fail_closes_photo_like_noise() -> None:
    rng = np.random.default_rng(20260815)
    rgb = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    alpha = np.full((128, 128, 1), 255, dtype=np.uint8)
    image = Image.fromarray(np.concatenate([rgb, alpha], axis=2), "RGBA")
    with pytest.raises(ProcessingError, match="suitability check"):
        vectorize_with_diagnostics(image, {"mode": "color", "complexity": 70})


def test_f07_lossless_svg_is_self_contained_and_bounded() -> None:
    svg, diagnostics = vectorize_with_diagnostics(_flat_art(), {"mode": "color", "complexity": 25})
    low = svg.lower()
    assert "<path" in low
    assert "<image" not in low
    assert "href=" not in low
    assert "base64" not in low
    assert "<script" not in low
    assert diagnostics["svg_size_bytes"] == len(svg.encode("utf-8"))
    assert diagnostics["path_count"] <= 8000
