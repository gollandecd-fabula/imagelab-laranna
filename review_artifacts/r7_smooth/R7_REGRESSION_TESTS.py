import sys, unittest
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

ROOT = Path('/mnt/data/imagelab_r7work')
sys.path.insert(0, str(ROOT))
from app.services import image_processing as ip


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
    np.divide(soft_premul, np.maximum(soft_alpha[:, :, None], 1e-6), out=soft, where=soft_alpha[:, :, None] > 1e-6)
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
        red = common.copy(); blue = common.copy()
        red[alpha == 0] = (255, 0, 0); blue[alpha == 0] = (0, 0, 255)
        out_red = np.asarray(ip._post_resize_smoothing(Image.fromarray(np.dstack((red, alpha)), 'RGBA'), 100, upscale_factor=12))
        out_blue = np.asarray(ip._post_resize_smoothing(Image.fromarray(np.dstack((blue, alpha)), 'RGBA'), 100, upscale_factor=12))
        visible = alpha > 0
        self.assertTrue(np.array_equal(out_red[:, :, 3], alpha))
        self.assertTrue(np.array_equal(out_blue[:, :, 3], alpha))
        self.assertEqual(int(np.max(np.abs(out_red[:, :, :3][visible].astype(np.int16) - out_blue[:, :, :3][visible].astype(np.int16)))), 0)
        self.assertLessEqual(int(np.max(np.ptp(out_red[:, :, :3][visible].astype(np.int16), axis=1))), 1)

    def test_tile_result_matches_full_frame_reference(self):
        rng = np.random.default_rng(20260906)
        rgba = rng.integers(0, 256, size=(1150, 1370, 4), dtype=np.uint8)
        rgba[:, :, 3] = rng.choice(np.array([0, 32, 96, 160, 224, 255], dtype=np.uint8), size=(1150, 1370))
        image = Image.fromarray(rgba, 'RGBA')
        tiled = np.asarray(ip._post_resize_smoothing(image.copy(), 76, upscale_factor=8))
        reference = np.asarray(full_alpha_reference(image, 76, 8))
        self.assertTrue(np.array_equal(tiled[:, :, 3], reference[:, :, 3]))
        delta = np.abs(tiled[:, :, :3].astype(np.int16) - reference[:, :, :3].astype(np.int16))
        self.assertLessEqual(int(delta.max()), 2)
        border = np.concatenate([delta[:, 1022:1026].reshape(-1, 3), delta[1022:1026, :].reshape(-1, 3)], axis=0)
        self.assertLessEqual(int(border.max()), 2)

    def test_auto_strength_is_deterministic_bounded_and_scale_monotone(self):
        source = Image.new('RGBA', (100, 80), (100, 120, 140, 255))
        for preset in ('soft', 'standard', 'detail'):
            values = []
            for scale in (1, 2, 4, 8, 12):
                result = Image.new('RGBA', (100 * scale, 80 * scale), (0, 0, 0, 0))
                first = ip._automatic_smoothing_strength(source, result, {'preset': preset, 'denoise': 100})
                second = ip._automatic_smoothing_strength(source, result, {'preset': preset, 'denoise': 100})
                self.assertEqual(first, second)
                self.assertGreaterEqual(first, 0); self.assertLessEqual(first, 78)
                values.append(first)
            self.assertEqual(values, sorted(values))


if __name__ == '__main__':
    unittest.main(verbosity=2)
