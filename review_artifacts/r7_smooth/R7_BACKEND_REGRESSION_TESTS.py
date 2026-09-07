from __future__ import annotations

import argparse
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image


def _candidate_root() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--candidate-root', required=True)
    args, remaining = parser.parse_known_args()
    sys.argv[:] = [sys.argv[0], *remaining]
    root = Path(args.candidate_root).resolve()
    required = [
        root / 'app/services/image_processing.py',
        root / 'app/services/m2a_processing.py',
    ]
    if not all(path.is_file() for path in required):
        raise SystemExit(f'candidate root is missing exact Improve backend files: {root}')
    return root


ROOT = _candidate_root()
sys.path.insert(0, str(ROOT))


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _StubSettings:
    max_processing_pixels = 200_000_000
    max_image_pixels = 200_000_000
    workspace_ppi = 300

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
services_mod = _stub_module('app.services'); services_mod.__path__ = [str(ROOT / 'app/services')]
_stub_module('app.ai.registry', AIModelError=_StubAIModelError)
_stub_module('app.ai.runtime', get_ai_engine=lambda *a, **k: None)
_stub_module('app.config', settings=_StubSettings())
_stub_module('app.models', AssetRecord=_StubRecord, CheckItem=_StubRecord)
_stub_module('app.services.file_inspector', UploadValidationError=_StubUploadValidationError, inspect_upload=lambda *a, **k: None)
_stub_module('app.services.restore_fidelity', restore_with_diagnostics=lambda *a, **k: (_ for _ in ()).throw(AssertionError('restore path not expected')))
_stub_module('app.services.vector_fidelity', process_vector=lambda *a, **k: (_ for _ in ()).throw(AssertionError('vector path not expected')))

from app.services import image_processing as ip  # noqa: E402
from app.services import m2a_processing as m2a  # noqa: E402


class R7ImproveBackendRegression(unittest.TestCase):
    def _run_backend(self, params: dict):
        source = Image.new('RGBA', (64, 48), (90, 120, 150, 255))
        arr = np.asarray(source).copy()
        arr[12:36, 18:46, :3] = (230, 80, 30)
        source = Image.fromarray(arr, 'RGBA')
        asset = SimpleNamespace(id='asset-backend', operation='upload')
        calls = []
        captured = {}
        original_smoothing = ip._post_resize_smoothing

        def smoothing_spy(image, strength, *, upscale_factor=1.0):
            calls.append({'strength': int(strength), 'upscale_factor': float(upscale_factor), 'size': image.size})
            return original_smoothing(image, strength, upscale_factor=upscale_factor)

        def save_spy(image, ppi, source_asset, operation, recorded, filename_suffix='png', ai=None):
            captured.update({
                'image': image.copy(),
                'ppi': float(ppi),
                'operation': operation,
                'recorded': dict(recorded),
                'ai': ai,
            })
            return captured

        with patch.object(ip, '_load_rgba', return_value=(source, 300.0)), \
             patch.object(ip, '_save_result', side_effect=save_spy), \
             patch.object(ip, '_post_resize_smoothing', side_effect=smoothing_spy):
            result = m2a.process_image(asset, 'enhance', dict(params))
        self.assertIs(result, captured)
        return calls, captured

    def test_backend_manual_smoothing_uses_slider_value(self):
        calls, captured = self._run_backend({
            'preset': 'custom', 'contrast': 1.0, 'sharpness': 1.0, 'denoise': 0,
            'brightness': 1.0, 'smoothing': 73, 'ai_auto': False, 'ppi': 300,
        })
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['strength'], 73)
        self.assertAlmostEqual(calls[0]['upscale_factor'], 1.0, places=6)
        self.assertEqual(captured['recorded']['smoothing_mode'], 'manual')
        self.assertEqual(captured['recorded']['smoothing_effective'], 73)
        self.assertEqual(captured['operation'], 'enhance')

    def test_backend_manual_zero_does_not_call_smoothing(self):
        calls, captured = self._run_backend({
            'preset': 'custom', 'contrast': 1.0, 'sharpness': 1.0, 'denoise': 0,
            'brightness': 1.0, 'smoothing': 0, 'ai_auto': False, 'ppi': 300,
        })
        self.assertEqual(calls, [])
        self.assertEqual(captured['recorded']['smoothing_mode'], 'manual')
        self.assertEqual(captured['recorded']['smoothing_effective'], 0)

    def test_backend_automatic_smoothing_after_four_x_resize(self):
        width_mm = 256 / 300 * 25.4
        calls, captured = self._run_backend({
            'preset': 'detail', 'denoise': 100, 'smoothing_auto': True, 'ai_auto': False,
            'ppi': 300, 'width_mm': width_mm, 'preserve_aspect': True, 'resample': True,
        })
        self.assertEqual(captured['image'].size, (256, 192))
        self.assertEqual(len(calls), 1)
        expected = ip._automatic_smoothing_strength(
            Image.new('RGBA', (64, 48)), Image.new('RGBA', (256, 192)),
            {'preset': 'detail', 'denoise': 100},
        )
        self.assertEqual(expected, 60)
        self.assertEqual(calls[0]['strength'], expected)
        self.assertAlmostEqual(calls[0]['upscale_factor'], 4.0, places=6)
        self.assertEqual(captured['recorded']['smoothing_mode'], 'automatic')
        self.assertEqual(captured['recorded']['smoothing_effective'], expected)
        self.assertAlmostEqual(captured['recorded']['smoothing_upscale_factor'], 4.0, places=4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
