from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable = next((p for p in (shutil.which("chromium"), shutil.which("google-chrome")) if p), None)
        instance = manager.chromium.launch(headless=True, executable_path=executable) if executable else manager.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def document() -> str:
    html = (ROOT / "app/static/index.html").read_text("utf-8")
    css = "\n".join((ROOT / f"app/static/{name}").read_text("utf-8") for name in ("styles.css", "m1-hardening.css", "m2a-ui.css"))
    m2a = "".join(p.read_text("utf-8") for p in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part")))
    js = "\n".join(((ROOT / "app/static/app.js").read_text("utf-8"), (ROOT / "app/static/m1-hardening.js").read_text("utf-8"), m2a)).replace("</script", "<\\/script")
    return html.replace("<head>", '<head><base href="http://imagelab.test/">', 1).replace(
        '<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate">', f"<style>{css}</style>"
    ).replace('<script src="/static/app.js?v=1.4.9-recovery-candidate"></script>', f"<script>{js}</script>")


def load(page):
    asset = {"id":"aaaaaaaa","original_name":"source.png","stored_name":"a.png","preview_name":"a.png","size_bytes":10,"sha256":"a"*64,"mime_type":"image/png","format":"PNG","width_px":640,"height_px":480,"ppi_x":300,"ppi_y":300,"ppi_origin":"embedded","print_width_mm":54.19,"print_height_mm":40.64,"color_mode":"RGB","color_profile":"sRGB","has_alpha":False,"created_at":"x","preview_url":"/preview/a.png","checks":[],"parameters":{},"ai":{}}
    project = {"id":"TS-001","title":"Основной","created_at":"x","updated_at":"x","assets":[asset],"workspace":{"active_asset_id":"aaaaaaaa","presets":{}}}
    def route_handler(route):
        path = urlparse(route.request.url).path
        if path == "/api/projects": body = [project]
        elif path == "/api/projects/TS-001": body = project
        elif path == "/api/health": body = {"status":"ok","version":"m2a","build_id":"M2A","install_id":"browser","scope":"M2A","host_policy":"localhost_only"}
        elif path == "/api/ai/health": body = {"status":"ready","runtime":"local","models":[]}
        elif path.startswith("/preview/"):
            route.fulfill(status=200, content_type="image/png", body=b"\x89PNG\r\n\x1a\n"); return
        else: body = {"project": project, "result": asset, "results": [asset], "overall_passed": True, "checks": []}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    page.route("**/*", route_handler)
    page.set_content(document(), wait_until="load")
    expect(page.locator("#projectName")).to_have_text("Основной")


def test_m2a_opaque_storage_navigation_and_source_button(browser):
    page = browser.new_page(viewport={"width": 1024, "height": 800})
    load(page)
    expect(page.locator("#sourceButton")).to_have_count(1)
    for module in ("projects", "background", "color", "palette", "dtf", "masters", "logo", "cardlab", "settings"):
        page.locator(f'[data-module="{module}"]').click()
        expect(page.locator(f'[data-pane="{module}"]')).to_have_class("module-pane m2a-pane active")
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    page.close()


def test_m2a_size_chain_preview_and_mobile_selector(browser):
    page = browser.new_page(viewport={"width": 800, "height": 900})
    load(page)
    page.locator('.m2a-mobile-nav').select_option('geometry')
    chain = page.locator('[data-size-grid="geometrySizeGrid"] .m2a-chain')
    expect(chain).to_have_attribute("aria-pressed", "true")
    page.locator("#widthMm").fill("100")
    expect(page.locator("#heightMm")).to_have_value("75.00")
    page.locator('[data-preview-mode="difference"]').click()
    expect(page.locator('[data-preview-mode="difference"]')).to_have_class("m2a-tool active")
    expect(page.locator(".m2a-mobile-nav")).to_be_visible()
    page.locator(".m2a-mobile-nav").select_option("settings")
    expect(page.locator('[data-pane="settings"]')).to_have_class("module-pane m2a-pane active")
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    page.close()
