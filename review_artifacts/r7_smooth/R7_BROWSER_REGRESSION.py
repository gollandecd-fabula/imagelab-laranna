from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument('--candidate-root', required=True)
args = parser.parse_args()

candidate_root = Path(args.candidate_root).resolve()
root = candidate_root / 'app' / 'static'


def synthetic_fixture_bytes() -> tuple[bytes, bytes]:
    # Deterministic, self-contained browser-only fixture. It is not claimed to
    # reproduce the historical /mnt/data PNGs; the regression checks UI routing
    # and divider geometry, not image-quality metrics.
    w, h = 192, 144
    image = Image.new('RGBA', (w, h))
    pixels = []
    for y in range(h):
        for x in range(w):
            block = ((x // 16) + (y // 16)) & 1
            pixels.append(((x * 5 + y * 3) & 255, (x * 2 + 40 * block) & 255, (y * 4 + 80 * (1 - block)) & 255, 255))
    image.putdata(pixels)
    result = image.resize((2304, 1728), Image.Resampling.NEAREST)
    def encode(im: Image.Image) -> bytes:
        stream = io.BytesIO()
        im.save(stream, format='PNG', optimize=False)
        return stream.getvalue()
    return encode(image), encode(result)


source_bytes, result_bytes = synthetic_fixture_bytes()
source_sha = hashlib.sha256(source_bytes).hexdigest()
result_sha = hashlib.sha256(result_bytes).hexdigest()
html = (root / 'index.html').read_text('utf-8')
html = re.sub(r'<script src="/static/app\.js[^>]*></script>', '', html)
html = html.replace('<head>', '<head><base href="http://imagelab.test/">', 1)
css = '\n'.join((root / name).read_text('utf-8') for name in [
    'styles.css', 'm1-hardening.css', 'm2a-ui.css', 'm2a-completeness.css'
])
appjs = (root / 'app.js').read_text('utf-8')
parts = root / 'm2a-ui-parts'
order = [
    '00-project-bootstrap-route.js.part','01.js.part','02.js.part','03a.js.part','03b.js.part',
    '04a.js.part','04b.js.part','05a.js.part','05b.js.part','06a.js.part','07-scope-lock.js.part',
    '08-workspace-batch.js.part','09-preview-controller.js.part','10-direct-controls.js.part',
    '11-rtm-hardening.js.part','12-canvas-controller.js.part','13-m2a-closure-fixes.js.part',
    '14-project-switch-flush.js.part','15-m2a-runtime-race-guard.js.part','16-project-bootstrap-restore.js.part',
    '17-accessible-info-drawer.js.part','18-preset-policy-restore.js.part','19-canonical-v144-scope.js.part',
    '20-accessible-info-focus-guard.js.part','20-f09-export-contract.js.part','21-preset-policy-draft.js.part',
    '22-f01-improve-contract.js.part'
]
m2ajs = ''.join((parts / name).read_text('utf-8') for name in order)


def asset(i, name, op, source_id, url, sha, w, h, size_bytes):
    return {
        'id': i, 'original_name': name, 'format': 'PNG', 'width_px': w, 'height_px': h,
        'ppi_x': 300, 'ppi_y': 300, 'ppi_origin': 'embedded',
        'print_width_mm': w / 300 * 25.4, 'print_height_mm': h / 300 * 25.4,
        'size_bytes': size_bytes, 'has_alpha': True, 'color_profile': 'sRGB',
        'preview_url': url, 'download_url': url, 'source_asset_id': source_id,
        'operation': op, 'parameters': {}, 'ai': {}, 'checks': [], 'sha256': sha,
    }


source = asset('src', 'source.png', None, None, '/img/source.png', source_sha, 192, 144, len(source_bytes))
result = asset('res', 'result.png', 'enhance', 'src', '/img/result.png', result_sha, 2304, 1728, len(result_bytes))
project = {
    'schema_version': 1, 'id': 'TS-001', 'title': 'TS-001', 'created_at': '', 'updated_at': '',
    'assets': [source, result],
    'workspace': {'ppi': 300, 'units': 'mm', 'active_asset_id': 'res', 'active_revision': 1},
    'collections': {'sources': ['src'], 'derivatives': ['res'], 'masters': [], 'exports': [], 'masks': {}, 'presets': {}, 'qa_reports': []},
}

with sync_playwright() as p:
    chromium_path = shutil.which('chromium') or shutil.which('chromium-browser')
    kwargs = {'headless': True, 'args': ['--no-sandbox']}
    if chromium_path:
        kwargs['executable_path'] = chromium_path
    browser = p.chromium.launch(**kwargs)
    page = browser.new_page(viewport={'width': 1640, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def route(r):
        u = r.request.url
        if '/img/source.png' in u:
            return r.fulfill(status=200, body=source_bytes, content_type='image/png')
        if '/img/result.png' in u:
            return r.fulfill(status=200, body=result_bytes, content_type='image/png')
        if u.endswith('/api/ai/health'):
            return r.fulfill(status=200, json={'status': 'ready', 'models': []})
        if u.endswith('/api/health'):
            return r.fulfill(status=200, json={'status': 'ok', 'version': '1.4.9', 'install_id': 'test', 'build_id': 'R7', 'scope': 'source'})
        if '/api/projects/TS-001' in u and r.request.method == 'GET':
            return r.fulfill(status=200, json=project)
        if u.endswith('/api/projects'):
            return r.fulfill(status=200, json=[project])
        if '/api/m2a/projects/TS-001/workspace' in u:
            return r.fulfill(status=200, json={'workspace': project['workspace']})
        if '/api/projects/TS-001/presets' in u:
            return r.fulfill(status=200, json={'presets': []})
        return r.fulfill(status=200, json={})

    page.route('http://imagelab.test/**', route)
    page.set_content(html, wait_until='domcontentloaded')
    page.add_style_tag(content=css)
    page.add_script_tag(content=appjs)
    page.wait_for_timeout(250)
    page.add_script_tag(content=m2ajs)
    page.wait_for_timeout(600)
    page.evaluate("(project)=>{state.project=project;state.selectedId='res';state.module='improve';renderProject();}", project)
    page.evaluate("()=>{document.querySelectorAll('.module-pane').forEach(n=>n.classList.toggle('active',n.dataset.pane==='improve'));window.__r7calls=[];processSelected=(operation,parameters)=>{window.__r7calls.push({operation,parameters});return Promise.resolve(null);};}")

    mode = lambda: page.locator('[data-improve-mode].active').get_attribute('data-improve-mode')
    hidden = lambda: page.locator('#improveManual').evaluate("n=>n.classList.contains('compact-hidden')")
    assert mode() == 'quick' and hidden() and page.locator('#enhancePreset').input_value() == 'detail'

    page.locator('[data-improve-mode="manual"]').click()
    assert mode() == 'manual' and not hidden() and page.locator('#enhancePreset').input_value() == 'custom'
    page.locator('#enhanceSmoothing').fill('73')
    page.locator('#applyEnhance').click()
    manual_call = page.evaluate('()=>window.__r7calls.at(-1)')
    assert manual_call['parameters'].get('smoothing') == 73 and 'smoothing_auto' not in manual_call['parameters']

    page.locator('#enhancePreset').select_option('detail')
    assert mode() == 'quick' and hidden()
    page.locator('#applyEnhance').click()
    quick_call = page.evaluate('()=>window.__r7calls.at(-1)')
    assert quick_call['parameters'].get('smoothing_auto') is True and 'smoothing' not in quick_call['parameters']

    page.locator('#enhancePreset').select_option('custom')
    assert mode() == 'manual' and not hidden()
    page.locator('[data-improve-mode="quick"]').click()
    assert mode() == 'quick' and hidden() and page.locator('#enhancePreset').input_value() == 'detail'
    assert page.locator('#enhanceSaturation').count() == 0
    assert page.locator('#improveManual #enhanceSmoothing').count() == 1

    page.locator('[data-preview-mode="split"]').click()
    page.wait_for_timeout(100)
    assert page.locator('.m2a-split-slider').count() == 0
    divider = page.locator('.m2a-split-divider')
    page.evaluate('()=>{imagelabM2A.zoom=1;imagelabM2A.panX=0;imagelabM2A.panY=0;imagelabM2A.splitRatio=.5;const p=document.querySelector("#previewStage .m2a-transform-wrap");p.style.transform="translate(0px,0px) scale(1)";imagelabM2A.syncSplitGeometry?.();}')
    box = divider.bounding_box()
    assert box is not None
    before = page.evaluate('()=>imagelabM2A.splitRatio')
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] * .4)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] / 2 + 137, box['y'] + box['height'] * .4, steps=6)
    page.mouse.up()
    after = page.evaluate('()=>imagelabM2A.splitRatio')
    assert abs(after - before) > .02
    delta = page.evaluate("""()=>{const d=document.querySelector('.m2a-split-divider'),p=document.querySelector('.m2a-transform-wrap'),r=document.querySelector('.m2a-result-image');const dr=d.getBoundingClientRect(),pr=p.getBoundingClientRect(),m=(r.style.clipPath.match(/([0-9.]+)%\\)$/)||[])[1],clip=Number(m||0);return Math.abs((dr.left+dr.right)/2-(pr.left+pr.width*clip/100));}""")
    assert delta <= 1.0, delta
    assert not errors, errors
    summary = {
        'status': 'PASS',
        'manual_smoothing': manual_call['parameters'].get('smoothing'),
        'manual_smoothing_auto_present': 'smoothing_auto' in manual_call['parameters'],
        'quick_smoothing_present': 'smoothing' in quick_call['parameters'],
        'quick_smoothing_auto': quick_call['parameters'].get('smoothing_auto'),
        'saturation_count': page.locator('#enhanceSaturation').count(),
        'bottom_split_slider_count': page.locator('.m2a-split-slider').count(),
        'divider_clip_delta_px': float(delta),
        'page_errors': errors,
    }
    browser.close()

print('R7_BROWSER_REGRESSION_PASS')
print(json.dumps(summary, sort_keys=True))
