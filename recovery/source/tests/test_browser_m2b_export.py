from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _asset(asset_id: str, operation: str | None = None) -> dict:
    return {
        "id": asset_id,
        "original_name": "f09.png",
        "stored_name": f"{asset_id}.png",
        "preview_name": f"{asset_id}.png",
        "size_bytes": 2048,
        "sha256": "a" * 64,
        "mime_type": "image/png",
        "format": "PNG",
        "width_px": 800,
        "height_px": 600,
        "ppi_x": 300,
        "ppi_y": 300,
        "ppi_origin": "embedded",
        "print_width_mm": 67.73,
        "print_height_mm": 50.8,
        "color_mode": "RGBA",
        "color_profile": "sRGB",
        "has_alpha": True,
        "created_at": "2026-08-16T00:00:00Z",
        "preview_url": "/preview/f09.png",
        "download_url": f"/api/assets/{asset_id}/file",
        "checks": [],
        "source_asset_id": "source0001" if operation else None,
        "operation": operation,
        "parameters": {},
        "ai": {"record": {"model_id": "qa_anomaly", "model_version": "1.0.0"}},
    }


def _document() -> str:
    html = (ROOT / "app/static/index.html").read_text("utf-8")
    css = "\n".join(
        (ROOT / f"app/static/{name}").read_text("utf-8")
        for name in ("styles.css", "m1-hardening.css", "m2a-ui.css", "m2a-completeness.css")
    )
    parts = "".join(path.read_text("utf-8") for path in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part")))
    javascript = "\n".join(((ROOT / "app/static/app.js").read_text("utf-8"), (ROOT / "app/static/m1-hardening.js").read_text("utf-8"), parts)).replace("</script", "<\\/script")
    return (
        html.replace("<head>", '<head><base href="http://imagelab.test/">', 1)
        .replace('<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate">', f"<style>{css}</style>")
        .replace('<script src="/static/app.js?v=1.4.9-recovery-candidate"></script>', f"<script>{javascript}</script>")
    )


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable = next((value for value in (shutil.which("chromium"), shutil.which("chromium-browser"), shutil.which("google-chrome")) if value), None)
        instance = manager.chromium.launch(headless=True, executable_path=executable) if executable else manager.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def test_f09_export_controls_send_complete_literal_contract(browser) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    source = _asset("source0001")
    project = {
        "id": "TS-001",
        "title": "F09",
        "created_at": "x",
        "updated_at": "x",
        "assets": [source],
        "workspace": {"active_asset_id": source["id"], "active_revision": 1, "presets": {}, "batch_reports": []},
    }
    observed: list[dict] = []

    def handler(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        if path == "/api/projects" and method == "GET":
            body = [project]
        elif path == "/api/projects/TS-001" and method == "GET":
            body = project
        elif path == "/api/ai/health":
            body = {"status": "ready", "models": []}
        elif path == "/api/health":
            body = {"status": "ok", "version": "1.4.9", "install_id": "test", "build_id": "test", "scope": "M2B"}
        elif path == "/api/projects/TS-001/export" and method == "POST":
            payload = request.post_data_json
            observed.append(payload)
            result = _asset("result0001", "export")
            result["source_asset_id"] = source["id"]
            result["parameters"] = dict(payload["parameters"], format=payload["format"])
            project["assets"].append(result)
            project["workspace"]["active_asset_id"] = result["id"]
            body = {"project": project, "source_asset_id": source["id"], "result": result, "learning": {"status": "disabled_for_request"}}
        elif path.startswith("/api/m2a/projects/TS-001/workspace"):
            body = {"project_id": "TS-001", "workspace": project["workspace"], "status": "saved", "project": project}
        elif path == "/api/projects/TS-001/active" and method == "POST":
            body = project
        elif path.startswith("/preview/"):
            route.fulfill(status=404, body="")
            return
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("http://imagelab.test/**", handler)
    page.set_content(_document(), wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#projectName')?.textContent === 'F09'")
    page.evaluate("activateModule('export')")

    for selector in ("#exportFilename", "#exportFolder", "#exportPpi", "#exportQuality", "#exportTransparency", "#exportColorProfile", "#exportMetadataPolicy", "#exportLogoMode", "#masterCleanButton", "#masterCardButton", "#masterDtfButton", "#cardlabButton"):
        expect(page.locator(selector)).to_have_count(1)

    page.locator("#exportFilename").fill("marketplace-final")
    page.locator("#exportFolder").fill("Order-2026")
    page.locator("#exportPpi").fill("300")
    page.locator("#exportQuality").fill("91")
    page.locator("#exportTransparency").select_option("flatten")
    page.locator("#exportColorProfile").select_option("srgb")
    page.locator("#exportMetadataPolicy").select_option("minimal")
    page.locator("#exportLogoMode").select_option("gray")
    page.locator('[data-export-format="JPG"]').click()
    page.locator("#applyExport").click()
    page.wait_for_function("() => document.querySelector('#toast')?.textContent.includes('Экспортный файл создан')")

    assert len(observed) == 1
    payload = observed[0]
    assert payload["asset_id"] == source["id"]
    assert payload["format"] == "JPG"
    assert payload["parameters"] == {
        "filename": "marketplace-final",
        "folder": "Order-2026",
        "ppi": 300,
        "quality": 91,
        "transparency": "flatten",
        "color_profile": "srgb",
        "metadata_policy": "minimal",
        "logo_variant": "gray",
        "ai_auto": False,
    }

    artifact_dir = os.environ.get("M2A_ARTIFACT_DIR")
    if artifact_dir:
        path = Path(artifact_dir) / "f09-export-1280.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)
    page.close()
