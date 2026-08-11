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
        "created_at": "2026-08-11T00:00:00Z",
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
    m2a = "".join(
        path.read_text("utf-8")
        for path in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part"))
    )
    javascript = "\n".join(
        (
            (ROOT / "app/static/app.js").read_text("utf-8"),
            (ROOT / "app/static/m1-hardening.js").read_text("utf-8"),
            m2a,
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
            (
                path
                for path in (
                    shutil.which("chromium"),
                    shutil.which("chromium-browser"),
                    shutil.which("google-chrome"),
                )
                if path
            ),
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


def _load(page, *, fail_project_b: bool = False, fail_process_index: int | None = None):
    project_a = {
        "id": "TS-001",
        "title": "Primary",
        "created_at": "x",
        "updated_at": "x",
        "assets": [
            _asset("aaaaaaaa", "one.png", "a"),
            _asset("bbbbbbbb", "two.png", "b"),
            _asset("cccccccc", "three.png", "c"),
        ],
        "workspace": {"active_asset_id": "aaaaaaaa", "active_revision": 1, "presets": {}, "batch_reports": []},
    }
    project_b = {
        "id": "B-002",
        "title": "Second",
        "created_at": "x",
        "updated_at": "x",
        "assets": [_asset("dddddddd", "second.png", "d")],
        "workspace": {"active_asset_id": "dddddddd", "active_revision": 1, "presets": {}, "batch_reports": []},
    }
    projects = {"TS-001": project_a, "B-002": project_b}
    state = {
        "projects": projects,
        "process_calls": [],
        "workspace_puts": [],
        "preset_puts": [],
        "project_gets": [],
        "fail_project_b": fail_project_b,
        "fail_process_index": fail_process_index,
    }
    png = _png()

    def handler(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method

        if path == "/api/projects" and method == "GET":
            body = [project_a, project_b]
        elif path.startswith("/api/projects/") and path.count("/") == 3 and method == "GET":
            project_id = path.rsplit("/", 1)[-1]
            state["project_gets"].append(project_id)
            if project_id == "B-002" and state["fail_project_b"]:
                route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "project load failed"}))
                return
            body = projects[project_id]
        elif path.startswith("/api/projects/") and path.endswith("/active") and method == "POST":
            project_id = path.split("/")[3]
            project = projects[project_id]
            project["workspace"]["active_asset_id"] = request.post_data_json["asset_id"]
            project["workspace"]["active_revision"] = project["workspace"].get("active_revision", 0) + 1
            body = project
        elif path.startswith("/api/projects/") and path.endswith("/process") and method == "POST":
            project_id = path.split("/")[3]
            payload = request.post_data_json
            state["process_calls"].append({"project_id": project_id, "payload": payload})
            call_index = len(state["process_calls"])
            if state["fail_process_index"] == call_index:
                route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "synthetic item failure"}))
                return
            project = projects[project_id]
            source = next(asset for asset in project["assets"] if asset["id"] == payload["asset_id"])
            result = dict(source)
            result.update(
                {
                    "id": f"result-{call_index:02d}",
                    "original_name": f"result-{call_index}.png",
                    "source_asset_id": source["id"],
                    "operation": payload["operation"],
                    "sha256": str(call_index % 10) * 64,
                    "preview_url": source["preview_url"],
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
        elif path.startswith("/api/m2a/projects/") and "/workspace/" in path and method == "PUT":
            parts = path.split("/")
            project_id = parts[4]
            section = parts[-1]
            value = request.post_data_json["value"]
            state["workspace_puts"].append({"project_id": project_id, "section": section, "value": value})
            projects[project_id]["workspace"][section] = value
            body = {"project": projects[project_id], "section": section, "status": "saved"}
        elif path.startswith("/api/m2a/projects/") and path.endswith("/presets") and method == "PUT":
            project_id = path.split("/")[4]
            payload = request.post_data_json
            state["preset_puts"].append({"project_id": project_id, "payload": payload})
            projects[project_id]["workspace"].setdefault("presets", {})[payload["name"]] = {
                "module": payload["module"],
                "parameters": payload["parameters"],
            }
            body = {"project": projects[project_id], "status": "saved"}
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
            current = project_a
            body = {
                "project": current,
                "result": current["assets"][-1],
                "results": [],
                "overall_passed": True,
                "checks": [],
            }

        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/*", handler)
    page.set_content(_document(), wait_until="load")
    expect(page.locator("#projectName")).to_have_text("Primary")
    expect(page.locator("#m2aProjectList .m2a-project-row")).to_have_count(2)
    return state


def _pump_until(page, predicate, *, timeout_ms: int = 6000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(20)
    raise AssertionError("condition was not met before timeout")


def _open_second(page) -> None:
    page.locator('[data-module="projects"]').click()
    page.locator("#m2aProjectList .m2a-project-row", has_text="Second").click()


def test_failed_project_switch_restores_route_and_persistence(browser) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state = _load(page, fail_project_b=True)

    _open_second(page)
    expect(page.locator("#projectName")).to_have_text("Primary")
    assert page.evaluate("window.localStorage.getItem('imagelab.activeProjectId')") is None

    state["fail_project_b"] = False
    page.locator("#refreshButton").click()
    expect(page.locator("#projectName")).to_have_text("Primary")
    assert state["project_gets"][-1] == "TS-001"
    page.close()


def test_batch_pins_project_and_persists_terminal_fail_report(browser) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state = _load(page)

    page.locator('[data-module="batch"]').click()
    page.locator("#m2aBatchAll").click()
    page.locator("#m2aBatchOperation").select_option("enhance")
    page.locator("#m2aRunBatch").click()

    _pump_until(page, lambda: len(state["process_calls"]) >= 1)
    _open_second(page)
    expect(page.locator("#projectName")).to_have_text("Second")
    _pump_until(page, lambda: not page.evaluate("window.imagelabM2A.batch?.running"))

    assert len(state["process_calls"]) == 3
    assert {call["project_id"] for call in state["process_calls"]} == {"TS-001"}
    reports = [
        item for item in state["workspace_puts"]
        if item["section"] == "batch_reports"
    ]
    assert reports
    assert reports[-1]["project_id"] == "TS-001"
    assert reports[-1]["value"][-1]["project_id"] == "TS-001"
    assert reports[-1]["value"][-1]["status"] == "PASS"
    expect(page.locator("#projectName")).to_have_text("Second")
    page.close()

    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state = _load(page, fail_process_index=2)
    page.locator('[data-module="batch"]').click()
    page.locator("#m2aBatchAll").click()
    page.locator("#m2aRunBatch").click()
    _pump_until(page, lambda: len(state["process_calls"]) >= 2)
    _pump_until(page, lambda: not page.evaluate("window.imagelabM2A.batch?.running"))

    reports = [
        item for item in state["workspace_puts"]
        if item["section"] == "batch_reports"
    ]
    assert reports, "terminal FAIL report must survive the failed item"
    terminal = reports[-1]["value"][-1]
    assert terminal["status"] == "FAIL"
    assert terminal["completed"] == 1
    assert [item["status"] for item in terminal["items"]] == ["PASS", "FAIL"]
    page.close()


def test_full_size_controller_preset_improve_serializer_and_switch_flush(browser) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state = _load(page)

    page.locator('[data-module="geometry"]').click()
    chain = page.locator('[data-size-grid="geometrySizeGrid"] .m2a-chain')
    expect(chain).to_have_attribute("aria-pressed", "true")
    chain.click()
    expect(chain).to_have_attribute("aria-pressed", "false")
    page.locator("#m2aLeading").select_option("height")
    page.locator("#m2aResample").uncheck()
    page.locator("#widthMm").fill("120")
    page.locator("#heightMm").fill("80")
    page.locator("#geometryPpi").fill("300")
    page.locator("#m2aCanvasWidth").fill("180")
    page.locator("#m2aCanvasHeight").fill("140")
    page.locator("#m2aCanvasAnchor").select_option("bottom-right")
    page.locator("#m2aCanvasTop").fill("5")
    page.locator("#m2aCanvasBottom").fill("6")
    page.locator("#m2aCanvasLeft").fill("7")
    page.locator("#m2aCanvasRight").fill("8")

    page.locator('[data-module="presets"]').click()
    page.locator("#m2aPresetModule").select_option("geometry")
    page.locator("#m2aPresetName").fill("full-size")
    page.locator("#m2aSavePreset").click()
    _pump_until(page, lambda: bool(state["preset_puts"]))

    payload = state["preset_puts"][-1]["payload"]
    size = payload["parameters"]["size_controller"]
    assert size["linked"] is False
    assert size["leading"] == "height"
    assert size["resample"] is False
    assert size["canvas"] == {
        "width_mm": "180",
        "height_mm": "140",
        "anchor": "bottom-right",
        "top_mm": 5,
        "bottom_mm": 6,
        "left_mm": 7,
        "right_mm": 8,
    }

    page.locator("#m2aPresetList .m2a-preset-row", has_text="full-size").locator("[data-use]").click()
    expect(page.locator('[data-module="geometry"]')).to_have_class("nav-item active")
    expect(page.locator("#m2aCanvasWidth")).to_have_value("180")
    expect(page.locator("#m2aCanvasHeight")).to_have_value("140")
    expect(page.locator("#m2aCanvasAnchor")).to_have_value("bottom-right")
    expect(chain).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#m2aResample")).not_to_be_checked()

    page.locator('[data-module="improve"]').click()
    page.locator("#improveWidthMm").fill("90")
    page.locator("#improveHeightMm").fill("60")
    page.locator("#improvePpi").fill("300")
    before = len(state["process_calls"])
    page.locator("#applyEnhance").click()
    _pump_until(page, lambda: len(state["process_calls"]) > before)
    params = state["process_calls"][-1]["payload"]["parameters"]
    assert params["width_mm"] == "90"
    assert params["height_mm"] == "60"
    assert params["ppi"] == 300
    assert params["preserve_aspect"] is False
    assert params["leading_side"] == "height"
    assert params["resample"] is False

    page.locator('[data-module="geometry"]').click()
    prior_put_count = len(state["workspace_puts"])
    page.locator("#widthMm").fill("121")
    _open_second(page)
    expect(page.locator("#projectName")).to_have_text("Second")
    size_puts = [
        item for item in state["workspace_puts"][prior_put_count:]
        if item["section"] == "size_controller"
    ]
    assert size_puts
    assert {item["project_id"] for item in size_puts} == {"TS-001"}
    assert size_puts[-1]["value"]["canvas"]["anchor"] == "bottom-right"
    page.close()


def test_auto_canvas_overflow_is_blocked_before_dispatch(browser) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    state = _load(page)

    page.locator('[data-module="geometry"]').click()
    page.locator("#geometryPpi").fill("1000")
    page.locator("#m2aCanvasWidth").fill("")
    page.locator("#m2aCanvasHeight").fill("")
    for selector in ("#m2aCanvasTop", "#m2aCanvasBottom", "#m2aCanvasLeft", "#m2aCanvasRight"):
        page.locator(selector).fill("500")

    before = len(state["process_calls"])
    page.locator("#applyGeometry").click()
    page.wait_for_timeout(100)
    assert len(state["process_calls"]) == before
    expect(page.locator("#toast")).to_contain_text("безопасный лимит памяти")
    page.close()
