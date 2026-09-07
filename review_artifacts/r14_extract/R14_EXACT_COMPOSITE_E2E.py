from __future__ import annotations

import io
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from app.config import settings
from app.services import extract_fidelity

client = TestClient(app)
PROJECT = 'R14-EXACT-COMPOSITE-E2E'


def _cleanup():
    client.delete(f'/api/projects/{PROJECT}/assets')
    path = settings.project_dir / f'{PROJECT}.json'
    if path.exists():
        path.unlink()


def _source_bytes() -> bytes:
    image = Image.new('RGB', (400, 500), (232, 232, 232))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 30, 330, 480), radius=35, fill=(38, 39, 44))
    draw.ellipse((125, 145, 275, 300), fill=(232, 77, 18))
    draw.rectangle((182, 108, 218, 342), fill=(246, 181, 22))
    draw.polygon([(135, 320), (200, 360), (265, 320), (235, 410), (165, 410)], fill=(205, 45, 30))
    buf = io.BytesIO(); image.save(buf, format='PNG', dpi=(300,300)); return buf.getvalue()


def _upload() -> dict:
    response = client.post(f'/api/projects/{PROJECT}/upload', files=[('files', ('source.png', _source_bytes(), 'image/png'))])
    assert response.status_code == 200, response.text
    return response.json()['uploaded'][0]


def _process(asset_id: str, operation: str, parameters: dict) -> dict:
    response = client.post(f'/api/projects/{PROJECT}/process', json={'asset_id':asset_id,'operation':operation,'parameters':parameters})
    assert response.status_code == 200, response.text
    return response.json()['result']


def _read(asset: dict) -> Image.Image:
    response = client.get(asset['download_url'])
    assert response.status_code == 200, response.text
    return Image.open(io.BytesIO(response.content)).convert('RGBA')


def test_exact_r14_manual_region_is_pixel_preserving_and_non_destructive(monkeypatch):
    _cleanup()
    source = _upload()
    engine = extract_fidelity.get_ai_engine()

    def forbidden(*args, **kwargs):
        raise AssertionError('destructive/auto path must not be called for manual region')

    monkeypatch.setattr(engine, 'segment_print', forbidden)
    monkeypatch.setattr(extract_fidelity.legacy, '_ai_extract_print', forbidden)
    monkeypatch.setattr(extract_fidelity, '_local_dewarp', forbidden)

    result = _process(source['id'], 'extract_print', {
        'mode':'region','x':20,'y':20,'width':60,'height':68,
        'strict_roi':True,
        'sensitivity':99,'texture_reduction':100,'reduce_fabric_texture':True,
        'feather':10,'crop_output':True,'padding_mm':9,'straighten':True,
    })
    output = _read(result)
    original = Image.open(io.BytesIO(_source_bytes())).convert('RGBA')
    expected = original.crop((80,100,320,440))
    assert output.size == expected.size == (240,340)
    assert np.array_equal(np.asarray(output), np.asarray(expected))

    d = result['parameters']['diagnostics']
    wf = d['manual_roi_working_fragment']
    assert wf['semantics'] == 'working_fragment'
    assert wf['strict_roi'] is True
    assert wf['segmentation_applied'] is False
    assert wf['background_removed'] is False
    assert wf['texture_reduction_applied'] is False
    assert wf['alpha_silhouette_dewarp_applied'] is False
    assert wf['fallback'] is False
    assert wf['deskew_requested'] is True and wf['deskew_applied'] is False
    assert set(wf['ignored_segmentation_controls']) >= {'sensitivity','texture_reduction','reduce_fabric_texture','feather','crop_output','padding_mm'}
    _cleanup()


def test_exact_r14_plain_region_is_valid_working_fragment():
    _cleanup()
    source = _upload()
    result = _process(source['id'], 'extract_print', {'mode':'region','x':0,'y':0,'width':12,'height':12,'strict_roi':True})
    assert result['operation'] == 'extract_print'
    assert result['parameters']['diagnostics']['manual_roi_working_fragment']['semantics'] == 'working_fragment'
    _cleanup()


def test_exact_r14_qa_accepts_working_fragment():
    _cleanup()
    source = _upload()
    result = _process(source['id'], 'extract_print', {'mode':'region','x':20,'y':20,'width':60,'height':68,'strict_roi':True})
    qa = client.get(f"/api/projects/{PROJECT}/qa?asset_id={result['id']}")
    assert qa.status_code == 200, qa.text
    data = qa.json()
    assert data['overall_passed'] is True, data
    by_code = {item['code']:item for item in data['checks']}
    for code in ('working_fragment_semantics','working_fragment_strict_roi','working_fragment_dimensions','working_fragment_non_destructive','working_fragment_no_fallback','working_fragment_coverage_contract'):
        assert by_code[code]['passed'] is True, (code, by_code[code])
    assert 'print_transparency' not in by_code
    _cleanup()


def test_exact_r14_extract_improve_background_chain_executes():
    _cleanup()
    source = _upload()
    fragment = _process(source['id'], 'extract_print', {'mode':'region','x':20,'y':20,'width':60,'height':68,'strict_roi':True})
    improved = _process(fragment['id'], 'enhance', {'preset':'detail','brightness':1,'contrast':1,'sharpness':1,'denoise':0,'smoothing':0})
    assert improved['source_asset_id'] == fragment['id']
    assert improved['operation'] == 'enhance'
    background = _process(improved['id'], 'background', {'mode':'auto','feather':1,'background_color':'transparent','ai_auto':False})
    assert background['source_asset_id'] == improved['id']
    assert background['operation'] == 'background'
    _cleanup()


def test_exact_r14_auto_path_still_executes():
    _cleanup()
    source = _upload()
    auto = _process(source['id'], 'extract_print', {'mode':'auto','sensitivity':60,'crop_output':False,'perspective':[[0,0],[100,0],[100,100],[0,100]]})
    assert auto['operation'] == 'extract_print'
    assert auto['parameters']['diagnostics']['region_box_px'] == [0,0,400,500]
    _cleanup()
