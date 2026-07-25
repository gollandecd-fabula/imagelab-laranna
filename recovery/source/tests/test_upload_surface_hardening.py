from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.file_inspector import (
    UploadValidationError,
    inspect_and_sanitize_svg,
    inspect_upload,
)


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
