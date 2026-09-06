from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def _candidate_root() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--candidate-root', required=True)
    args, remaining = parser.parse_known_args()
    sys.argv[:] = [sys.argv[0], *remaining]
    root = Path(args.candidate_root).resolve()
    if not (root / 'app' / 'services' / 'image_processing.py').is_file():
        raise SystemExit(f'candidate root is missing reconstructed app: {root}')
    return root


ROOT = _candidate_root()
sys.path.insert(0, str(ROOT))

# The reproducibility snapshot intentionally contains only the three exact
# correction endpoints. image_processing imports unrelated application modules
# at module import time, but these smoothing regressions do not call those
# services. Install explicit inert stubs so the exact reconstructed module can
# be imported without inventing product source bytes.
import types  # noqa: E402

def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod

class _StubSettings:
    def __getattr__(self, name):
        return None

class _StubRecord:
    pass

class _StubUploadValidationError(Exception):
    pass

class _StubAIModelError(Exception):
    pass

app_mod = _stub_module('app')
app_mod.__path__ = [str(ROOT / 'app')]
ai_mod = _stub_module('app.ai'); ai_mod.__path__ = []
services_mod = _stub_module('app.services'); services_mod.__path__ = [str(ROOT / 'app' / 'services')]
_stub_module('app.ai.registry', AIModelError=_StubAIModelError)
_stub_module('app.ai.runtime', get_ai_engine=lambda *a, **k: None)
_stub_module('app.config', settings=_StubSettings())
_stub_module('app.models', AssetRecord=_StubRecord, CheckItem=_StubRecord)
_stub_module('app.services.file_inspector', UploadValidationError=_StubUploadValidationError, inspect_upload=lambda *a, **k: None)

from app.services import image_processing as ip  # noqa: E402


def full_alpha_reference(image: Image.Image, strength: int, upscale_factor: float = 1.0) -> Image.Image:
    value = int(np.clip(int(strength), 0, 100))
    if value <= 0:
        return image
    rgba = np.asarray(image.convert('RGBA'), dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    premul = rgb * alpha[:, :, None]
    t = value / 100.0
    scale = float(np.clip(upscale_factor, 1.0, 10.0))
    sigma = 0.28 + t * (0.72 + 0.18 * scale)
    base_weight = float(np.clip(0.08 + 0.62 * t, 0.08, 0.70))
    gray = cv2.cvtColor(np.clip(premul, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    reference = max(6.0, float(np.percentile(np.rint(mag), 88.0)))
    soft_premul = cv2.GaussianBlur(premul, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REPLICATE)
    soft_alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REPLICATE)
    soft = np.zeros_like(soft_premul)
    np.divide(
        soft_premul,
        np.maximum(soft_alpha[:, :, None], 1e-6),
        out=soft,
        where=soft_alpha[:, :, None] > 1e-6,
    )
    edge = np.clip(mag / reference, 0, 1)
    weight = (base_weight * (1.0 - 0.28 * edge))[:, :, None]
    smoothed = np.clip(rgb * (1.0 - weight) + soft * weight, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack((smoothed, rgba[:, :, 3])), 'RGBA')


class R7SmoothingRegression(unittest.TestCase):
    def test_zero_is_strict_noop(self):
        arr = np.arange(64 * 48 * 4, dtype=np.uint8).reshape(48, 64, 4)
        image = Image.fromarray(arr, 'RGBA')
        result = ip._post_resize_smoothing(image, 0, upscale_factor=12)
        self.assertIs(result, image)
        self.assertTrue(np.array_equal(np.asarray(result), arr))

    def test_hidden_rgb_cannot_bleed_into_visible_pixels(self):
        h = w = 160
        alpha = np.zeros((h, w), np.uint8)
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((xx - 80) ** 2 + (yy - 80) ** 2)
        alpha[dist <= 46] = 255
        ring = (dist > 46) & (dist < 48)
        alpha[ring] = np.clip((48 - dist[ring]) * 127.5, 1, 254).astype(np.uint8)
        common = np.full((h, w, 3), 255, np.uint8)
        red = common.copy()
        blue = common.copy()
        red[alpha == 0] = (255, 0, 0)
        blue[alpha == 0] = (0, 0, 255)
        out_red = np.asarray(
            ip._post_resize_smoothing(Image.fromarray(np.dstack((red, alpha)), 'RGBA'), 100, upscale_factor=12)
        )
        out_blue = np.asarray(
            ip._post_resize_smoothing(Image.fromarray(np.dstack((blue, alpha)), 'RGBA'), 100, upscale_factor=12)
        )
        visible = alpha > 0
        self.assertTrue(np.array_equal(out_red[:, :, 3], alpha))
        self.assertTrue(np.array_equal(out_blue[:, :, 3], alpha))
        self.assertEqual(
            int(
                np.max(
                    np.abs(
                        out_red[:, :, :3][visible].astype(np.int16)
                        - out_blue[:, :, :3][visible].astype(np.int16)
                    )
                )
            ),
            0,
        )
        self.assertLessEqual(int(np.max(np.ptp(out_red[:, :, :3][visible].astype(np.int16), axis=1))), 1)

    def test_tile_result_matches_full_frame_reference(self):
        rng = np.random.default_rng(20260906)
        rgba = rng.integers(0, 256, size=(1150, 1370, 4), dtype=np.uint8)
        rgba[:, :, 3] = rng.choice(
            np.array([0, 32, 96, 160, 224, 255], dtype=np.uint8), size=(1150, 1370)
        )
        image = Image.fromarray(rgba, 'RGBA')
        tiled = np.asarray(ip._post_resize_smoothing(image.copy(), 76, upscale_factor=8))
        reference = np.asarray(full_alpha_reference(image, 76, 8))
        self.assertTrue(np.array_equal(tiled[:, :, 3], reference[:, :, 3]))
        delta = np.abs(tiled[:, :, :3].astype(np.int16) - reference[:, :, :3].astype(np.int16))
        self.assertLessEqual(int(delta.max()), 2)
        border = np.concatenate(
            [delta[:, 1022:1026].reshape(-1, 3), delta[1022:1026, :].reshape(-1, 3)], axis=0
        )
        self.assertLessEqual(int(border.max()), 2)

    def test_auto_strength_is_deterministic_bounded_and_scale_monotone(self):
        source = Image.new('RGBA', (100, 80), (100, 120, 140, 255))
        for preset in ('soft', 'standard', 'detail'):
            values = []
            for scale in (1, 2, 4, 8, 12):
                result = Image.new('RGBA', (100 * scale, 80 * scale), (0, 0, 0, 0))
                params = {'preset': preset, 'denoise': 100}
                first = ip._automatic_smoothing_strength(source, result, params)
                second = ip._automatic_smoothing_strength(source, result, params)
                self.assertEqual(first, second)
                self.assertGreaterEqual(first, 0)
                self.assertLessEqual(first, 78)
                values.append(first)
            self.assertEqual(values, sorted(values))


if __name__ == '__main__':
    unittest.main(verbosity=2)
