from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services.background_fidelity import _solve_studio_matte
from app.services.image_processing import ProcessingError


def _composite(fg: Image.Image, bg: Image.Image) -> Image.Image:
    return Image.alpha_composite(bg.convert("RGBA"), fg.convert("RGBA"))


def test_f04_uniform_studio_preserves_hole_and_soft_hair_alpha() -> None:
    bg = Image.new("RGBA", (96, 96), (245, 245, 245, 255))
    fg = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(fg)
    draw.rounded_rectangle((24, 20, 72, 76), radius=10, fill=(215, 55, 70, 255))
    draw.ellipse((38, 34, 54, 50), fill=(0, 0, 0, 0))
    draw.line((18, 22, 10, 70), fill=(215, 55, 70, 220), width=1)
    result = _solve_studio_matte(_composite(fg, bg), {"edge_refine": True, "decontaminate": True})
    assert result is not None
    output, diagnostics = result
    alpha = np.asarray(output)[:, :, 3]
    assert alpha[42, 46] == 0
    assert 205 <= int(alpha[46, 14]) <= 230
    assert diagnostics["strategy"] == "m2b_studio_border_matte"
    assert diagnostics["fallback"] is False


def test_f04_checker_studio_preserves_opaque_multitone_white_subject() -> None:
    h = w = 96
    yy, xx = np.mgrid[0:h, 0:w]
    checker = ((xx // 12 + yy // 12) & 1).astype(bool)
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    arr[:, :, :3][~checker] = (220, 225, 230)
    arr[:, :, :3][checker] = (195, 205, 215)
    bg = Image.fromarray(arr, "RGBA")
    fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(fg)
    draw.rounded_rectangle((24, 18, 72, 78), radius=10, fill=(252, 252, 252, 255))
    draw.ellipse((37, 28, 55, 46), fill=(210, 210, 210, 255))
    result = _solve_studio_matte(_composite(fg, bg), {})
    assert result is not None
    output, diagnostics = result
    out = np.asarray(output)
    assert int(out[36, 46, 3]) == 255
    assert tuple(int(x) for x in out[36, 46, :3]) == (210, 210, 210)
    assert diagnostics["opaque_light_multitone"] is True


def test_f04_studio_mask_touching_frame_fail_closes() -> None:
    bg = Image.new("RGBA", (96, 96), (245, 245, 245, 255))
    fg = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    ImageDraw.Draw(fg).rectangle((0, 20, 72, 76), fill=(35, 145, 210, 255))
    # Border corruption makes the high-confidence studio model unavailable rather
    # than silently declaring a clean mask.
    assert _solve_studio_matte(_composite(fg, bg), {}) is None


