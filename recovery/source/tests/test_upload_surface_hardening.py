from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.services.file_inspector import (
    UploadValidationError,
    inspect_and_sanitize_svg,
    inspect_upload,
)

ROOT = Path(__file__).resolve().parents[1]


def test_product_scope_is_uploaded_image_only_with_separate_operations() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text("utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text("utf-8")
    api = (ROOT / "app" / "main.py").read_text("utf-8")
    combined = f"{html}\n{js}\n{api}".casefold()

    for required in (
        'id="fileinput"',
        'data-module="extract"',
        'data-pane="extract"',
        'id="applyextractprint"',
        'data-module="cleanup"',
        'data-pane="cleanup"',
        'id="applycleanup"',
        'id="removebackground"',
        "ширина, мм",
        "высота, мм",
        "мягкость края, px",
        "processselected('extract_print'",
        "applycleanupflow",
        "/upload",
    ):
        assert required in combined

    for forbidden in (
        "text-to-image",
        "text2image",
        "txt2img",
        "генерация изображения по тексту",
        "сгенерировать изображение по описанию",
        "гарантируем авторские права",
        "юридически безопасный принт",
        'id="unittoggle"',
        'id="units"',
        'value="cm"',
    ):
        assert forbidden not in combined

    assert js.index("#applyExtractPrint") != js.index("#applyCleanup")
    assert "processSelected('extract_print'" in js
    assert "processSelected('background'" in js or "remove_background" in js


def test_svg_rejects_late_doctype_beyond_initial_probe_window() -> None:
    payload = (
        b" " * 9000
        + b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        + b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">&x;</svg>'
    )
    with pytest.raises(UploadValidationError, match="DTD"):
        inspect_and_sanitize_svg(payload)


def test_svg_rejects_external_url_in_non_style_attribute() -> None:
    payload = b'''<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">
      <path d="M0 0L10 10" marker-start="url(https://evil.test/marker.svg#x)"/>
    </svg>'''
    with pytest.raises(UploadValidationError, match="URL"):
        inspect_and_sanitize_svg(payload)


def test_svg_allows_only_internal_fragment_url_references() -> None:
    payload = b'''<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">
      <defs><clipPath id="safeClip"><rect width="10" height="10"/></clipPath></defs>
      <rect width="20" height="20" clip-path="url(#safeClip)"/>
    </svg>'''
    result = inspect_and_sanitize_svg(payload)
    assert result.width_px == 20
    assert b"safeClip" in result.sanitized


def test_multiframe_tiff_is_rejected_before_persistence() -> None:
    first = Image.new("RGB", (16, 16), (255, 0, 0))
    second = Image.new("RGB", (16, 16), (0, 0, 255))
    buffer = io.BytesIO()
    first.save(buffer, format="TIFF", save_all=True, append_images=[second])
    with pytest.raises(UploadValidationError, match="Многостраничные"):
        inspect_upload(buffer.getvalue(), "two-pages.tiff")


def test_animated_webp_is_rejected_when_codec_supports_animation() -> None:
    first = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    second = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
    buffer = io.BytesIO()
    try:
        first.save(
            buffer,
            format="WEBP",
            save_all=True,
            append_images=[second],
            duration=100,
            loop=0,
            lossless=True,
        )
    except (OSError, KeyError):
        pytest.skip("Pillow build has no animated WebP encoder")
    with pytest.raises(UploadValidationError, match="анимированные"):
        inspect_upload(buffer.getvalue(), "animated.webp")
