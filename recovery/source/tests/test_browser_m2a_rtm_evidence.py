from __future__ import annotations

import io
import json
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (640, 480), (70, 110, 180)).save(stream, format="PNG")
    return stream.getvalue()


def _asset(asset_id: str, name: str, digest: str) -> dict:
    return {
        "id": asset_id,
        "original_name": name,
        "stored_name": f"{asset_id}.png",
        "preview_name": f"{asset_id}.png",
        "size_bytes": 1024,
        "sha256": digest * 64,
        "mime_type": "image/png",
        "format": "PNG",
        "width_px": 640,
        "height_px": 480,
        "ppi_x": 300,
        "ppi_y": 300,
        "ppi_origin": "embedded",
        "print_width_mm": 54.19,
        "print_height_mm": 40.64,
        "color_mode": "RGB",
        "color_profile": "sRGB",
        "has_alpha": False,
        "created_at": "x",
        "preview_url": f"/preview/{asset_id}.png",
        "download_url": f"/api/assets/{asset_id}/file",
        "checks": [],
        "source_asset_id": None,
        "operation": None,
        "parameters": {},
        "ai": {},
    }


def _document() -> str:
    html = (ROOT / "app/static/index.html").read_text("utf-8")
    css = "\n".join(
        (ROOT / f"app/static/{name}").read_text("utf-8")
        for name in ("styles.css", "m1-hardening.css", "m2a-ui.css", "m2a-completeness.css")
    )
    parts = "".join(path.read_text("utf-8") for path in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part")))
    js = "\n".join(
        ((ROOT / "app/static/app.js").read_text("utf-8"), (ROOT / "app/static/m1-hardening.js").read_text("utf-8"), parts)
    ).replace("</script", "<\\/script")
    return (
        html.replace("<head>", '<head><base href="http://imagelab.test/">', 1)
        .replace('<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate">', f"<style>{css}</style>")
        .replace('<script src="/static/app.js?v=1.4.9-recovery-candidate"></script>', f"<script>{js}</script>")
    )


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable = next((p for p in (shutil.which("chromium"), shutil.which("google-chrome")) if p), None)
        instance = manager.chromium.launch(headless=True, executable_path=executable) if executable else manager.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def _load(page):
    assets = [_asset("aaaaaaaa", "one.png", "a"), _asset("bbbbbbbb", "two.png", "b"), _asset("cccccccc", "three.png", "c")]
    project = {
        "id": "TS-001",
        "title": "RTM Evidence",
        "created_at": "x",
        "updated_at": "x",
        "assets": assets,
        "workspace": {"active_asset_id": "aaaaaaaa", "active_revision": 1, "presets": {}, "batch_reports": []},
    }
    state = {"process_calls": [], "workspace_puts": []}
    png = _png()

    def handler(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        if path == "/api/projects" and method == "GET":
            body = [project]
        elif path == "/api/projects/TS-001" and method == "GET":
            body = project
        elif path == "/api/projects/TS-001/active" and method == "POST":
            project["workspace"]["active_asset_id"] = request.post_data_json["asset_id"]
            body = project
        elif path == "/api/projects/TS-001/process" and method == "POST":
            payload = request.post_data_json
            state["process_calls"].append(payload)
            source = next(asset for asset in project["assets"] if asset["id"] == payload["asset_id"])
            result = dict(source)
            result.update({
                "id": f"result-{len(state['process_calls']):02d}",
                "original_name": f"result-{len(state['process_calls'])}.png",
                "source_asset_id": source["id"],
                "operation": payload["operation"],
                "sha256": str(len(state["process_calls"]) % 10) * 64,
            })
            project["assets"].append(result)
            project["workspace"]["active_asset_id"] = result["id"]
            body = {"project": project, "result": result, "source_asset_id": source["id"], "attempts": [result]}
        elif path.startswith("/api/m2a/projects/TS-001/workspace/") and method == "PUT":
            section = path.rsplit("/", 1)[-1]
            value = request.post_data_json["value"]
            state["workspace_puts"].append({"section": section, "value": value})
            project["workspace"][section] = value
            body = {"project": project, "section": section, "status": "saved"}
        elif path == "/api/m2a/diagnostics":
            body = {
                "application": {"host_policy": "localhost_only"},
                "system": {"cpu_logical": 8, "gpu": "not_configured"},
                "runtime": {"status": "ready", "providers": ["local"], "models": [{"id": "restore-v1", "version": "1"}]},
                "disk": {"free_bytes": 1_000_000},
                "privacy": {"image_content_included": False, "secrets_included": False},
            }
        elif path == "/api/health":
            body = {"status": "ok", "version": "m2a", "build_id": "M2A", "install_id": "browser", "scope": "M2A", "host_policy": "localhost_only"}
        elif path == "/api/ai/health":
            body = {"status": "ready", "runtime": "local", "models": []}
        elif path.startswith("/preview/"):
            route.fulfill(status=200, content_type="image/png", body=png)
            return
        else:
            body = {"project": project, "result": project["assets"][-1], "results": [], "overall_passed": True, "checks": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/*", handler)
    page.set_content(_document(), wait_until="load")
    expect(page.locator("#projectName")).to_have_text("RTM Evidence")
    return state, project


def _wait(page, predicate, timeout_ms: int = 6000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(20)
    raise AssertionError("condition not met")


def test_rtm_preview_modes_background_zoom_pan_crop_mask_and_theme(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _load(page)

    # VIS-004/VIS-007: dark runtime surface and distinct state samples.
    background = page.locator("body").evaluate("node => getComputedStyle(node).backgroundColor")
    assert background not in {"rgb(255, 255, 255)", "rgba(255, 255, 255, 1)"}
    samples = page.locator("[data-state-sample]")
    expect(samples).to_have_count(6)
    styles = samples.evaluate_all("nodes => nodes.map(n => [getComputedStyle(n).color, getComputedStyle(n).backgroundColor].join('|'))")
    assert len(set(styles)) >= 4

    # PV-001/PV-002: six explicit preview modes and four distinct backgrounds.
    modes = page.locator("[data-preview-mode]")
    expect(modes).to_have_count(6)
    for mode in ("result", "original", "split", "overlay", "difference", "mask"):
        page.locator(f'[data-preview-mode="{mode}"]').click()
        expect(page.locator(f'[data-preview-mode="{mode}"]')).to_have_class("m2a-tool active")
        assert f"m2a-{mode}" in page.locator("#previewStage").get_attribute("class")
    background_select = page.locator("#m2aPreviewBackground")
    assert {option.get_attribute("value") for option in background_select.locator("option").all()} == {"transparent", "white", "black", "gray"}
    for value in ("transparent", "white", "black", "gray"):
        background_select.select_option(value)
        assert page.locator("#previewStage").get_attribute("data-preview-background") == value

    # PV-003/PV-004: zoom controls alter the actual transform and label follows runtime scale.
    page.locator('[data-preview-mode="result"]').click()
    page.locator("#m2aOneToOne").click()
    expect(page.locator("#m2aZoomValue")).to_have_text("100%")
    before_transform = page.locator(".m2a-transform-wrap").evaluate("node => getComputedStyle(node).transform")
    page.locator("#m2aZoomIn").click()
    after_transform = page.locator(".m2a-transform-wrap").evaluate("node => getComputedStyle(node).transform")
    assert after_transform != before_transform
    assert page.locator("#m2aZoomValue").inner_text() != "100%"
    page.locator("#m2aFit").click()
    runtime_zoom = page.evaluate("window.imagelabM2A.zoom")
    label_zoom = int(page.locator("#m2aZoomValue").inner_text().rstrip("%")) / 100
    assert abs(runtime_zoom - label_zoom) <= 0.011

    stage = page.locator("#previewStage")
    box = stage.bounding_box()
    assert box
    start = (box["x"] + box["width"] * 0.8, box["y"] + box["height"] * 0.8)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] - 35, start[1] - 20)
    page.mouse.up()
    assert abs(page.evaluate("window.imagelabM2A.panX")) + abs(page.evaluate("window.imagelabM2A.panY")) > 0

    # PV-008/PV-009: crop and perspective are interactive preview-only geometry controls.
    page.locator('[data-module="geometry"]').click()
    expect(page.locator("#m2aCropBox")).to_have_count(1)
    handle = page.locator("#m2aCropBox [data-corner='se']")
    hb = handle.bounding_box()
    assert hb
    before_width = float(page.locator("#cropWidth").input_value())
    page.mouse.move(hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2)
    page.mouse.down()
    page.mouse.move(hb["x"] - 25, hb["y"] - 15, steps=4)
    page.mouse.up()
    assert float(page.locator("#cropWidth").input_value()) != before_width

    page.locator("#usePerspective").check()
    expect(page.locator(".m2a-perspective-handle")).to_have_count(4)
    perspective = page.locator(".m2a-perspective-handle").first
    pb = perspective.bounding_box()
    assert pb
    before_x = float(page.locator("#pTLx").input_value())
    page.mouse.move(pb["x"] + pb["width"] / 2, pb["y"] + pb["height"] / 2)
    page.mouse.down()
    page.mouse.move(pb["x"] + 35, pb["y"] + 25, steps=4)
    page.mouse.up()
    assert float(page.locator("#pTLx").input_value()) != before_x

    # PV-006/PV-007: every required mask tool is reachable and cursor diameter is factual.
    page.locator('[data-module="selection"]').click()
    tools = {node.get_attribute("data-mask-tool") for node in page.locator("[data-mask-tool]").all()}
    assert {"add", "subtract", "erase", "lasso", "rectangle", "clear", "invert"}.issubset(tools)
    page.locator('[data-mask-tool="add"]').click()
    canvas = page.locator("canvas.m2a-selection-layer")
    cb = canvas.bounding_box()
    assert cb
    page.mouse.move(cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
    cursor = page.locator("#m2aBrushCursor")
    expect(cursor).to_be_visible()
    diameter = float(cursor.evaluate("node => parseFloat(getComputedStyle(node).width)"))
    expected = float(page.evaluate("selectionBrushPixels(selectedAsset())"))
    assert abs(diameter - expected) <= 1.0
    page.close()


def test_rtm_history_settings_and_batch_pause_cancel(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state, project = _load(page)

    # PRJ-004/PRJ-005: typed history and real active-version Undo/Redo.
    history = page.locator("#historyStrip [data-asset-id]")
    expect(history).to_have_count(3)
    assert all(node.get_attribute("data-history-type") == "Original" for node in history.all())
    page.locator('#historyStrip [data-asset-id="bbbbbbbb"]').click()
    page.wait_for_function("state.selectedId === 'bbbbbbbb'")
    page.locator("#m2aUndo").click()
    page.wait_for_function("state.selectedId === 'aaaaaaaa'")
    page.locator("#m2aRedo").click()
    page.wait_for_function("state.selectedId === 'bbbbbbbb'")

    # SET-001/SET-002: diagnostics categories and persisted safe settings surface.
    page.locator('[data-module="settings"]').click()
    page.locator("#m2aRefreshDiagnostics").click()
    expect(page.locator("#m2aDiagnostics")).to_contain_text("CPU")
    expect(page.locator("#m2aDiagnostics")).to_contain_text("GPU")
    expect(page.locator("#m2aDiagnostics")).to_contain_text("Runtime")
    expect(page.locator("#m2aDiagnostics")).to_contain_text("Диск")
    expect(page.locator("#m2aModelList")).to_contain_text("restore-v1")
    page.locator("#m2aDefaultFolder").fill("D:\\ImageLab\\Projects")
    page.locator('[data-model-pack="restore"]').check()
    page.locator("#m2aPrivacyLocal").check()
    page.locator("#m2aSaveSettings").click()
    _wait(page, lambda: any(item["section"] == "settings" for item in state["workspace_puts"]))
    saved = [item for item in state["workspace_puts"] if item["section"] == "settings"][-1]["value"]
    assert saved["default_folder"] == "D:\\ImageLab\\Projects"
    assert saved["requested_model_packs"] == ["restore"]
    assert saved["privacy"]["local_only"] is True
    assert not any(key in json.dumps(saved).lower() for key in ("password", "api_key", "secret", "token"))

    # PRJ-009/AUTO-003/AUTO-004: pause freezes dispatch; cancel preserves completed work.
    page.locator('[data-module="batch"]').click()
    page.locator("#m2aBatchAll").click()
    page.locator("#m2aRunBatch").click()
    _wait(page, lambda: len(state["process_calls"]) >= 1)
    page.locator("#m2aBatchPause").click()
    expect(page.locator("#m2aBatchPause")).to_have_text("Продолжить")
    expect(page.locator("#m2aBatchStage")).to_contain_text("пауза")
    paused_count = len(state["process_calls"])
    page.wait_for_timeout(250)
    assert len(state["process_calls"]) == paused_count
    page.locator("#m2aBatchPause").click()
    _wait(page, lambda: len(state["process_calls"]) > paused_count)
    page.locator("#m2aBatchCancel").click()
    _wait(page, lambda: not page.evaluate("window.imagelabM2A.batch.running"))
    assert project["workspace"]["active_asset_id"]
    reports = [item for item in state["workspace_puts"] if item["section"] == "batch_reports"]
    assert reports
    terminal = reports[-1]["value"][-1]
    assert terminal["status"] == "CANCELLED"
    assert any(item["status"] == "PASS" for item in terminal["items"])
    assert any(item["status"] == "CANCELLED" for item in terminal["items"])
    expect(page.locator("#m2aBatchElapsed")).to_have_count(1)
    expect(page.locator("#m2aBatchEngine")).to_contain_text("engine")
    page.close()
