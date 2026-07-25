from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pytest
from PIL import Image

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable = next(
            (
                candidate
                for candidate in (
                    shutil.which("chromium"),
                    shutil.which("chromium-browser"),
                    shutil.which("google-chrome"),
                    shutil.which("google-chrome-stable"),
                )
                if candidate
            ),
            None,
        )
        options: dict[str, object] = {"headless": True}
        if executable:
            options["executable_path"] = executable
        instance = manager.chromium.launch(**options)
        try:
            yield instance
        finally:
            instance.close()


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def _asset(asset_id: str, name: str, color: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "original_name": name,
        "stored_name": f"{asset_id}.png",
        "preview_name": f"{asset_id}.png",
        "size_bytes": 1024,
        "sha256": color * 64,
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
        "created_at": "2026-07-26T00:00:00Z",
        "preview_url": f"/preview/{asset_id}.png",
        "checks": [],
        "source_asset_id": None,
        "operation": None,
        "parameters": {},
        "ai": {},
        "download_url": f"/api/assets/{asset_id}/file",
    }


def _ui_document() -> str:
    html = (ROOT / "app" / "static" / "index.html").read_text("utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text("utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text("utf-8").replace("</script", "<\\/script")
    html = html.replace("<head>", '<head><base href="http://imagelab.test/">', 1)
    html = html.replace(
        '<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate-m1-ui-hardening">',
        f"<style>{css}</style>",
    )
    html = html.replace(
        '<script src="/static/app.js?v=1.4.9-recovery-candidate-m1-ui-hardening"></script>',
        f"<script>{js}</script>",
    )
    return html


def _load_ui(page, *, malformed_project: bool = False):
    project = {"id": "TS-001", "title": "TS-001", "created_at": "x", "updated_at": "x", "assets": [], "workspace": {}}
    calls: list[str] = []
    images = {"a": _png_bytes((220, 50, 50)), "b": _png_bytes((50, 80, 220))}

    def handler(route):
        request = route.request
        calls.append(request.url)
        parsed = urlparse(request.url)
        path = parsed.path
        if path == "/api/ai/health":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ready", "models": [1, 2]}))
        elif path == "/api/health":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ok", "version": "1.4.9-recovery-candidate", "build_id": "M1", "install_id": "browser", "scope": "IMAGELAB_M1"}))
        elif path == "/api/projects/TS-001" and request.method == "GET":
            if malformed_project:
                route.fulfill(status=200, content_type="application/json", body="{broken-json")
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(project))
        elif path == "/api/projects/TS-001/active" and request.method == "POST":
            payload = request.post_data_json
            project["workspace"]["active_asset_id"] = payload["asset_id"]
            project["workspace"]["active_revision"] = int(project["workspace"].get("active_revision", 0)) + 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps(project))
        elif path.startswith("/preview/"):
            key = Path(path).stem
            route.fulfill(status=200, content_type="image/png", body=images.get(key, images["a"]))
        elif path == "/api/ai/train":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "promoted"}))
        elif path == "/broken":
            route.fulfill(status=200, content_type="application/json", body="{broken-json")
        else:
            route.fulfill(status=404, content_type="application/json", body=json.dumps({"detail": f"unhandled test route: {path}"}))

    page.route("**/*", handler)
    page.set_content(_ui_document(), wait_until="load")
    return project, calls


def _canvas_alpha_sum(page) -> int:
    return int(
        page.locator("canvas.selection-canvas").evaluate(
            "canvas => { const d=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data; let s=0; for(let i=3;i<d.length;i+=4)s+=d[i]; return s; }"
        )
    )


def test_navigation_responsive_modes_masks_busy_and_confirmation(browser) -> None:
    context = browser.new_context(viewport={"width": 1024, "height": 800})
    page = context.new_page()
    project, calls = _load_ui(page)
    expect(page.locator("#projectName")).to_have_text("TS-001")

    for module in ["upload", "improve", "extract", "selection", "cleanup", "halftone", "vector", "geometry", "export"]:
        page.locator(f'[data-module="{module}"]').click()
        expect(page.locator(f'[data-pane="{module}"]')).to_have_class("module-pane active")

    for width in (1024, 800):
        page.set_viewport_size({"width": width, "height": 800})
        page.wait_for_timeout(100)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"horizontal overflow at {width}px: {overflow}"

    mode = page.locator("#globalOperationMode")
    repair = page.locator("#globalAutoRepair")
    mode.select_option("fast")
    expect(repair).to_be_disabled()
    expect(repair).not_to_be_checked()
    mode.select_option("check-only")
    expect(repair).to_be_disabled()
    expect(repair).not_to_be_checked()
    mode.select_option("professional")
    expect(repair).to_be_enabled()
    expect(repair).to_be_checked()

    page.evaluate("setBusy(true)")
    expect(page.locator("body")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#chooseButton")).to_be_disabled()
    expect(page.locator("#globalAutoRepair")).to_be_disabled()
    page.evaluate("setBusy(false)")
    expect(page.locator("body")).to_have_attribute("aria-busy", "false")

    project["assets"] = [_asset("a", "first.png", "a"), _asset("b", "second.png", "b")]
    project["workspace"] = {"active_asset_id": "b", "active_revision": 1}
    page.evaluate(
        "project => { state.project=project; state.selectedId='b'; renderProject(); }",
        project,
    )
    expect(page.locator("#historyStrip .history-thumb")).to_have_count(2)
    page.locator('[data-module="selection"]').click()
    canvas = page.locator("canvas.selection-canvas")
    expect(canvas).to_be_visible()
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.25)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.55, steps=8)
    page.mouse.up()
    assert _canvas_alpha_sum(page) > 0

    page.locator("#historyStrip .history-thumb").nth(0).click()
    expect(page.locator("#historyStrip .history-thumb").nth(0)).to_have_class("history-thumb active")
    expect(page.locator("canvas.selection-canvas")).to_be_visible()
    assert _canvas_alpha_sum(page) == 0, "manual mask leaked to another asset"

    page.locator('[data-info-tab="ai"]').click()
    page.once("dialog", lambda dialog: dialog.dismiss())
    before = sum("/api/ai/train" in url for url in calls)
    page.locator("#aiTrainButton").click()
    page.wait_for_timeout(100)
    after = sum("/api/ai/train" in url for url in calls)
    assert after == before, "cancelled training still reached API"
    context.close()


def test_malformed_json_is_visible_and_fail_closed(browser) -> None:
    context = browser.new_context(viewport={"width": 1024, "height": 800})
    page = context.new_page()
    _load_ui(page, malformed_project=True)
    expect(page.locator("#toast")).to_contain_text("повреждённый ответ", timeout=5_000)
    expect(page.locator("#toast")).to_have_class("toast error show")
    page.evaluate("api('/broken').catch(error => toast(error.message, true))")
    expect(page.locator("#toast")).to_contain_text("повреждённый ответ")
    context.close()
