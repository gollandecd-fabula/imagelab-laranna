from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.services.halftone_fidelity import _binary_halftone
from app.services.image_processing import ProcessingError


def _tone(value: int) -> Image.Image:
    return Image.new("RGBA", (96, 80), (value, value, value, 255))


def _coverage(image: Image.Image) -> float:
    alpha = np.asarray(image.getchannel("A"))
    assert set(int(v) for v in np.unique(alpha)).issubset({0, 255})
    return float(np.count_nonzero(alpha)) / float(alpha.size)


def test_f06_production_alpha_is_binary_and_tracks_darkness() -> None:
    dark, dd = _binary_halftone(_tone(45), 300.0, {
        "mode":"mono","raster":"dot","shape":"circle","size_mm":0.22,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":40,"density":65,"angle":15,
    })
    light, ld = _binary_halftone(_tone(205), 300.0, {
        "mode":"mono","raster":"dot","shape":"circle","size_mm":0.22,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":40,"density":65,"angle":15,
    })
    assert _coverage(dark) > _coverage(light)
    assert abs(_coverage(dark) - dd["target_coverage"]) < 0.002
    assert abs(_coverage(light) - ld["target_coverage"]) < 0.002
    assert dd["alpha_mode"] == "production_binary"


@pytest.mark.parametrize("raster", ["dot", "line", "hybrid"])
@pytest.mark.parametrize("shape", ["circle", "ellipse", "square", "diamond"])
def test_f06_supported_raster_shape_controls_execute(raster: str, shape: str) -> None:
    out, diag = _binary_halftone(_tone(105), 300.0, {
        "mode":"color","raster":raster,"shape":shape,"size_mm":0.26,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":45,"density":70,"angle":37,
    })
    assert out.size == (96, 80)
    assert diag["raster"] == raster
    assert diag["shape"] == shape
    assert diag["angle"] == 37.0
    assert 0.0005 <= _coverage(out) <= 0.90


def test_f06_raster_and_angle_change_geometry_at_same_tone() -> None:
    source = _tone(120)
    a, da = _binary_halftone(source, 300.0, {
        "mode":"mono","raster":"dot","shape":"diamond","size_mm":0.22,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":40,"density":65,"angle":0,
    })
    b, db = _binary_halftone(source, 300.0, {
        "mode":"mono","raster":"line","shape":"diamond","size_mm":0.22,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":40,"density":65,"angle":45,
    })
    assert not np.array_equal(np.asarray(a), np.asarray(b))
    assert abs(_coverage(a) - _coverage(b)) < 0.002
    assert abs(da["target_coverage"] - db["target_coverage"]) < 1e-9


def test_f06_never_prints_outside_visible_alpha() -> None:
    source = Image.new("RGBA", (80, 64), (100, 100, 100, 0))
    ImageDraw.Draw(source).rectangle((10, 8, 65, 55), fill=(100, 100, 100, 255))
    result, _ = _binary_halftone(source, 300.0, {
        "mode":"color","raster":"hybrid","shape":"square","size_mm":0.30,
        "min_size_mm":0.08,"max_size_mm":0.45,"lpi":50,"density":75,"angle":75,
    })
    sa = np.asarray(source.getchannel("A")) > 8
    ra = np.asarray(result.getchannel("A")) > 8
    assert not np.any(ra & ~sa)


def test_f06_invalid_dot_bounds_fail_closed() -> None:
    with pytest.raises(ProcessingError, match="Минимальный размер точки"):
        _binary_halftone(_tone(120), 300.0, {
            "mode":"mono","raster":"dot","shape":"circle","size_mm":0.2,
            "min_size_mm":0.5,"max_size_mm":0.1,"lpi":45,"density":70,"angle":45,
        })
