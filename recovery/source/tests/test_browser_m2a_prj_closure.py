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
    parts = "".join(
        path.read_text("utf-8")
        for path in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part"))
    )
    javascript = "\n".join(
        (
            (ROOT / "app/static/app.js").read_text("utf-8"),
            (ROOT / "app/static/m1-hardening.js").read_text("utf-8"),
            parts,
        )
    ).replace("</script", "<\\/script")
    return (
        html.replace("<head>", '<head><base href="http://imagelab.test/">', 1)
        .replace(
            '<link rel="stylesheet" href="/static/styles.css?v=1.4.9-recovery-candidate">',
            f"<style>{css}</style>",
        )
        .replace(
            '<script src="/static/app.js?v=1.4.9-recovery-candidate"></script>',
            f"<script>{javascript}</script>",
        )
    )


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as manager:
        executable = next(
            (p for p in (shutil.which("chromium"), shutil.which("google-chrome")) if p),
            None,
        )
        instance = (
            manager.chromium.launch(headless=True, executable_path=executable)
            if executable
            else manager.chromium.launch(headless=True)
        )
        try:
            yield instance
        finally:
            instance.close()


def _load(page, *, initial_presets: dict | None = None):
    assets = [
        _asset("aaaaaaaa", "one.png", "a"),
        _asset("bbbbbbbb", "two.png", "b"),
        _asset("cccccccc", "three.png", "c"),
    ]
    project = {
        "id": "TS-001",
        "title": "PRJ closure",
        "created_at": "x",
        "updated_at": "x",
        "assets": assets,
        "workspace": {
            "active_asset_id": "aaaaaaaa",
            "active_revision": 1,
            "presets": dict(initial_presets or {}),
            "batch_reports": [],
        },
    }
    state = {"process_calls": [], "workspace_puts": [], "preset_puts": []}
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
            result.update(
                {
                    "id": f"result-{len(state['process_calls']):02d}",
                    "original_name": f"result-{len(state['process_calls'])}.png",
                    "source_asset_id": source["id"],
                    "operation": payload["operation"],
                    "sha256": str(len(state["process_calls"]) % 10) * 64,
                    "parameters": payload.get("parameters", {}),
                }
            )
            project["assets"].append(result)
            project["workspace"]["active_asset_id"] = result["id"]
            body = {
                "project": project,
                "result": result,
                "source_asset_id": source["id"],
                "attempts": [result],
            }
        elif path.startswith("/api/m2a/projects/TS-001/workspace/") and method == "PUT":
            section = path.rsplit("/", 1)[-1]
            value = request.post_data_json["value"]
            state["workspace_puts"].append({"section": section, "value": value})
            project["workspace"][section] = value
            body = {"project": project, "section": section, "status": "saved"}
        elif path == "/api/m2a/projects/TS-001/presets" and method == "PUT":
            payload = request.post_data_json
            state["preset_puts"].append(payload)
            project["workspace"].setdefault("presets", {})[payload["name"]] = {
                "module": payload["module"],
                "parameters": payload["parameters"],
            }
            body = {"project": project, "status": "saved"}
        elif path == "/api/m2a/diagnostics":
            body = {
                "application": {"host_policy": "localhost_only"},
                "system": {"cpu_logical": 8, "gpu": "not_configured"},
                "runtime": {"status": "ready", "providers": ["local"], "models": []},
                "disk": {"free_bytes": 1_000_000},
                "privacy": {"image_content_included": False, "secrets_included": False},
            }
        elif path == "/api/health":
            body = {
                "status": "ok",
                "version": "m2a",
                "build_id": "M2A",
                "install_id": "browser",
                "scope": "M2A",
                "host_policy": "localhost_only",
            }
        elif path == "/api/ai/health":
            body = {"status": "ready", "runtime": "local", "models": []}
        elif path.startswith("/preview/"):
            route.fulfill(status=200, content_type="image/png", body=png)
            return
        else:
            body = {
                "project": project,
                "result": project["assets"][-1],
                "results": [],
                "overall_passed": True,
                "checks": [],
            }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/*", handler)
    page.set_content(_document(), wait_until="load")
    expect(page.locator("#projectName")).to_have_text("PRJ closure")
    return state, project


def _wait(page, predicate, timeout_ms: int = 7000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(20)
    raise AssertionError("condition not met")


def test_prj004_autosave_exposes_saving_saved_and_error(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _load(page)
    page.evaluate(
        """
        () => {
          window.__prjOriginalFetch = window.fetch;
          window.__prjResolve = null;
          window.fetch = (input, init) => {
            const url = String(input?.url || input || '');
            if (url.includes('/workspace/settings')) {
              return new Promise(resolve => {
                window.__prjResolve = () => resolve(new Response(
                  JSON.stringify({project: structuredClone(state.project), section: 'settings', status: 'saved'}),
                  {status: 200, headers: {'Content-Type': 'application/json'}}
                ));
              });
            }
            return window.__prjOriginalFetch(input, init);
          };
          void window.imagelabM2A.workspacePut('settings', {probe: 'saving'}).catch(() => {});
        }
        """
    )
    expect(page.locator("#m2aSaveState")).to_have_attribute("data-state", "busy")
    expect(page.locator("#m2aSaveState")).to_contain_text("сохранение")
    page.evaluate("window.__prjResolve()")
    expect(page.locator("#m2aSaveState")).to_have_attribute("data-state", "saved")
    expect(page.locator("#m2aSaveState")).to_contain_text("сохранено")
    page.evaluate(
        """
        () => {
          window.fetch = (input, init) => {
            const url = String(input?.url || input || '');
            if (url.includes('/workspace/settings')) return Promise.reject(new Error('synthetic save failure'));
            return window.__prjOriginalFetch(input, init);
          };
          void window.imagelabM2A.workspacePut('settings', {probe: 'error'}).catch(() => {});
        }
        """
    )
    expect(page.locator("#m2aSaveState")).to_have_attribute("data-state", "error")
    expect(page.locator("#m2aSaveState")).to_contain_text("ошибка")
    page.close()


def test_prj005_real_preset_save_render_apply_round_trip_without_secrets(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state, _ = _load(page)

    page.locator('[data-module="geometry"]').click()
    chain = page.locator('[data-size-grid="geometrySizeGrid"] .m2a-chain')
    expect(chain).to_have_attribute("aria-pressed", "true")
    chain.click()
    expect(chain).to_have_attribute("aria-pressed", "false")
    page.locator("#widthMm").fill("120")
    page.locator("#heightMm").fill("80")
    page.wait_for_timeout(500)

    page.locator('[data-module="settings"]').click()
    page.locator("#m2aPrivacyLocal").check()
    page.locator("#m2aQaPolicy").select_option("strict")
    page.locator("#m2aExportProfile").select_option("dtf_pending")

    page.locator('[data-module="presets"]').click()
    page.locator("#m2aPresetModule").select_option("geometry")
    page.locator("#m2aPresetName").fill("policy-probe")
    page.locator("#m2aSavePreset").click()
    _wait(page, lambda: len(state["preset_puts"]) == 1)

    payload = state["preset_puts"][0]
    parameters = payload["parameters"]
    assert parameters["engine_policy"] == "local_only"
    assert parameters["qa_policy"] == "strict"
    assert parameters["export_profile"] == "dtf_pending"
    assert parameters["size_controller"]["linked"] is False
    assert parameters["size_controller"]["width_mm"] == "120"
    assert parameters["size_controller"]["height_mm"] == "80"
    serialized = json.dumps(payload).lower()
    assert not any(key in serialized for key in ("password", "api_key", "secret", "token"))

    row = page.locator("#m2aPresetList .m2a-preset-row", has_text="policy-probe")
    expect(row).to_have_count(1)

    page.locator('[data-module="settings"]').click()
    page.locator("#m2aPrivacyLocal").uncheck()
    page.locator("#m2aQaPolicy").select_option("mandatory")
    page.locator("#m2aExportProfile").select_option("transparent_png")
    page.locator('[data-module="presets"]').click()
    row.locator("[data-use]").click()

    expect(page.locator('[data-module="geometry"]')).to_have_class("nav-item active")
    expect(page.locator("#m2aPrivacyLocal")).to_be_checked()
    expect(page.locator("#m2aQaPolicy")).to_have_value("strict")
    expect(page.locator("#m2aExportProfile")).to_have_value("dtf_pending")
    expect(page.locator('[data-size-grid="geometrySizeGrid"] .m2a-chain')).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#widthMm")).to_have_value("120")
    expect(page.locator("#heightMm")).to_have_value("80")
    page.close()


def _batch_preset() -> dict:
    return {
        "batch-one": {
            "module": "geometry",
            "parameters": {
                "engine_policy": "local_only",
                "qa_policy": "mandatory",
                "export_profile": "transparent_png",
                "size_controller": {
                    "linked": True,
                    "leading": "width",
                    "resample": True,
                    "width_mm": "77",
                    "height_mm": "55",
                    "improve_width_mm": "77",
                    "improve_height_mm": "55",
                    "ppi": 300,
                    "improve_ppi": 300,
                    "canvas": {
                        "width_mm": "",
                        "height_mm": "",
                        "anchor": "center",
                        "top_mm": 0,
                        "bottom_mm": 0,
                        "left_mm": 0,
                        "right_mm": 0,
                    },
                },
            },
        }
    }


def test_prj006_prj009_batch_one_preset_report_and_factual_progress(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state, project = _load(page, initial_presets=_batch_preset())
    page.locator('[data-module="batch"]').click()
    page.locator("#m2aBatchAll").click()
    page.locator("#m2aBatchOperation").select_option("geometry")
    page.locator("#m2aBatchPreset").select_option("batch-one")
    progress = page.locator("#m2aBatchJob progress")
    expect(page.locator("#m2aBatchCancel")).to_have_count(1)
    page.locator("#m2aRunBatch").click()
    _wait(page, lambda: not page.evaluate("window.imagelabM2A.batch.running"))

    assert len(state["process_calls"]) == 3
    for call in state["process_calls"]:
        params = call["parameters"]
        assert params["width_mm"] == "77"
        assert params["height_mm"] == "55"
        assert params["ppi"] == 300
        assert params["preserve_aspect"] is True
        assert params["leading_side"] == "width"
        assert params["resample"] is True
    assert float(progress.evaluate("node => node.value")) == 100
    expect(page.locator("#m2aBatchStage")).to_contain_text("pass")
    expect(page.locator("#m2aBatchEngine")).to_contain_text("engine")
    expect(page.locator("#m2aBatchElapsed")).to_have_count(1)
    expect(page.locator("#m2aBatchCancel")).to_be_disabled()

    reports = [item for item in state["workspace_puts"] if item["section"] == "batch_reports"]
    assert reports
    terminal = reports[-1]["value"][-1]
    assert terminal["preset"] == "batch-one"
    assert terminal["status"] == "PASS"
    assert terminal["requested"] == 3
    assert terminal["completed"] == 3
    assert [item["status"] for item in terminal["items"]] == ["PASS", "PASS", "PASS"]
    assert project["workspace"]["active_asset_id"]
    page.close()


def test_prj006_pause_cancel_preserves_completed_items(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state, project = _load(page)
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
    reports = [item for item in state["workspace_puts"] if item["section"] == "batch_reports"]
    assert reports
    terminal = reports[-1]["value"][-1]
    assert terminal["status"] == "CANCELLED"
    assert any(item["status"] == "PASS" for item in terminal["items"])
    assert any(item["status"] == "CANCELLED" for item in terminal["items"])
    assert project["workspace"]["active_asset_id"]
    page.close()


def test_prj007_autoparams_is_distinct_from_prepare_print(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    _load(page)
    mode = page.locator("#globalOperationMode")
    autoparams = mode.locator('option[value="autoparams"]')
    expect(autoparams).to_have_count(1)
    expect(autoparams).to_contain_text("не однокнопочный маршрут")
    prepare = page.locator("#m2aPreparePrint")
    dialog = page.locator("#m2aAutopilotDialog")
    expect(prepare).to_be_visible()
    expect(dialog).not_to_have_class("m2a-autopilot-dialog open")
    page.evaluate(
        """
        () => {
          const mode = document.getElementById('globalOperationMode');
          mode.value = 'autoparams';
          mode.dispatchEvent(new Event('change', {bubbles: true}));
        }
        """
    )
    expect(mode).to_have_value("autoparams")
    expect(dialog).not_to_have_class("m2a-autopilot-dialog open")
    prepare.click()
    expect(dialog).to_have_class("m2a-autopilot-dialog open")
    expect(page.locator(".m2a-stage-list label")).to_have_count(7)
    expect(page.locator("#m2aMandatoryQa")).to_be_checked()
    expect(page.locator("#m2aMandatoryQa")).to_be_disabled()
    expect(page.locator("#m2aAutoStart")).to_be_disabled()
    expect(mode).to_have_value("autoparams")
    page.close()
