from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = SOURCE_ROOT / "tests" / "fixtures" / "pilot_v1" / "generated" / "rep_text_logo.png"
EVIDENCE_ROOT = Path(
    os.environ.get(
        "PILOT_EVIDENCE_DIR",
        SOURCE_ROOT / "artifacts" / "pilot-visual-reachability",
    )
).resolve()
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime-data"
REPORT_PATH = EVIDENCE_ROOT / "visual-reachability.json"
SERVER_LOG = EVIDENCE_ROOT / "visual-reachability-server.log"
HOST = "127.0.0.1"
PORT = 8766
ORIGIN = f"http://{HOST}:{PORT}"
PROJECT_ID = "TS-001"
SOURCE_SHA = os.environ.get("PILOT_SOURCE_SHA", "unknown").strip() or "unknown"
VIEWPORT_WIDTHS = (800, 1024, 1280, 1440, 1920)
VIEWPORT_HEIGHT = 900


class ReachabilityError(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReachabilityError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected: tuple[int, ...] = (200,),
    timeout: float = 30.0,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = {"Accept": "application/json", "Origin": ORIGIN}
    if headers:
        request_headers.update(headers)
    payload = body
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()
    if response.status not in expected:
        raise ReachabilityError(
            f"{method} {path}: HTTP {response.status}; {data.decode('utf-8', 'replace')[:1200]}"
        )
    return response.status, response_headers, data


def multipart_file(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"ImageLabVisual{uuid.uuid4().hex}"
    payload = bytearray()
    payload.extend(f"--{boundary}\r\n".encode("ascii"))
    payload.extend(
        (
            f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8")
    )
    payload.extend(data)
    payload.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return bytes(payload), boundary


def start_server() -> tuple[subprocess.Popen[bytes], Any]:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    log = SERVER_LOG.open("ab", buffering=0)
    env = dict(os.environ)
    env["IMAGELAB_DATA_DIR"] = str(RUNTIME_ROOT)
    env["PYTHONUTF8"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.entry:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "info",
        ],
        cwd=SOURCE_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 75
    last_error = "no response"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            raise ReachabilityError(f"runtime exited with code {process.returncode}")
        try:
            status, _, _ = request("GET", "/api/health", timeout=2)
            if status == 200:
                return process, log
        except Exception as exc:  # startup polling only
            last_error = str(exc)
        time.sleep(0.5)
    stop_server(process, log)
    raise ReachabilityError(f"runtime startup timeout: {last_error}")


def stop_server(process: subprocess.Popen[bytes] | None, log: Any | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    if log is not None and not log.closed:
        log.close()


def prepare_real_project() -> dict[str, Any]:
    # The source runtime creates TS-001 during startup. Reuse that real project
    # and reset only its assets instead of issuing a duplicate create request.
    request("GET", f"/api/projects/{PROJECT_ID}")
    request("DELETE", f"/api/projects/{PROJECT_ID}/assets")
    fixture_bytes = FIXTURE.read_bytes()
    upload_body, boundary = multipart_file(FIXTURE.name, fixture_bytes)
    _, _, data = request(
        "POST",
        f"/api/projects/{PROJECT_ID}/upload",
        body=upload_body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    asset = json.loads(data.decode("utf-8"))["uploaded"][0]
    require(asset["sha256"] == sha256(fixture_bytes), "real upload SHA mismatch")
    return asset


def launch_browser(manager) -> Browser:
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
    if executable:
        return manager.chromium.launch(headless=True, executable_path=executable)
    return manager.chromium.launch(headless=True)


def module_names(page: Page) -> list[str]:
    desktop = page.locator("button[data-module]").evaluate_all(
        "nodes => nodes.map(node => node.dataset.module).filter(Boolean)"
    )
    mobile = page.locator(".m2a-mobile-nav option").evaluate_all(
        "nodes => nodes.map(node => node.value).filter(Boolean)"
    )
    return list(dict.fromkeys([*desktop, *mobile]))


def activate_module(page: Page, module: str) -> str:
    desktop = page.locator(f'button[data-module="{module}"]:visible')
    mobile = page.locator(".m2a-mobile-nav:visible")
    if desktop.count():
        desktop.first.click()
        method = "button"
    elif mobile.count() and mobile.locator(f'option[value="{module}"]').count():
        mobile.select_option(module)
        method = "mobile_select"
    else:
        raise ReachabilityError(f"module navigation unavailable: {module}")
    page.wait_for_function(
        "module => { const pane = document.querySelector(`[data-pane=\"${module}\"]`); "
        "return pane && pane.classList.contains('active'); }",
        arg=module,
        timeout=5000,
    )
    return method


def inspect_active_controls(page: Page, module: str) -> list[dict[str, Any]]:
    pane = page.locator(f'[data-pane="{module}"].active').first
    require(pane.count() == 1, f"active pane missing: {module}")
    controls = pane.locator("button, a[href], input, select, textarea, summary")
    result: list[dict[str, Any]] = []
    for index in range(controls.count()):
        control = controls.nth(index)
        if not control.is_visible():
            continue
        metrics = control.evaluate(
            """element => {
                element.scrollIntoView({block: 'center', inline: 'nearest'});
                const rect = element.getBoundingClientRect();
                const disabled = Boolean(element.disabled) || element.getAttribute('aria-disabled') === 'true';
                const hidden = element.tagName === 'INPUT' && element.type === 'hidden';
                if (!disabled && !hidden) element.focus({preventScroll: true});
                const focused = disabled || hidden || document.activeElement === element || element.contains(document.activeElement);
                const x = Math.min(window.innerWidth - 1, Math.max(0, rect.left + rect.width / 2));
                const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + rect.height / 2));
                const top = document.elementFromPoint(x, y);
                const unobscured = Boolean(top && (top === element || element.contains(top) || top.contains(element)));
                const inside = rect.width > 0 && rect.height > 0 && rect.left >= -1 && rect.right <= window.innerWidth + 1 && rect.top >= -1 && rect.bottom <= window.innerHeight + 1;
                return {
                    id: element.id || null,
                    tag: element.tagName.toLowerCase(),
                    type: element.type || null,
                    text: (element.innerText || element.getAttribute('aria-label') || element.getAttribute('title') || element.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 100),
                    disabled,
                    focused,
                    unobscured,
                    inside,
                    rect: {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height}
                };
            }"""
        )
        metrics.update({"module": module, "index": index})
        result.append(metrics)
    return result


def width_probe(browser: Browser, width: int) -> dict[str, Any]:
    page = browser.new_page(viewport={"width": width, "height": VIEWPORT_HEIGHT})
    console_errors: list[str] = []
    page_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    report: dict[str, Any] = {
        "width": width,
        "height": VIEWPORT_HEIGHT,
        "modules": [],
        "module_reports": [],
        "failures": [],
    }
    try:
        page.goto(ORIGIN, wait_until="load", timeout=60_000)
        page.wait_for_selector("#projectName", state="visible", timeout=15_000)
        page.wait_for_function(
            "() => document.querySelectorAll('button[data-module]').length >= 9",
            timeout=15_000,
        )
        page.wait_for_timeout(500)
        require(
            page.locator("#aiTrainButton, #aiRollbackButton, #aiTrainModule").count() == 0,
            "runtime training controls leaked into served HTML",
        )
        modules = module_names(page)
        require(len(modules) >= 9, f"too few modules: {modules}")
        report["modules"] = modules
        max_overflow = 0.0
        for module in modules:
            try:
                navigation = activate_module(page, module)
                page.wait_for_timeout(40)
                overflow = float(
                    page.evaluate(
                        "Math.max(0, document.documentElement.scrollWidth - window.innerWidth)"
                    )
                )
                max_overflow = max(max_overflow, overflow)
                controls = inspect_active_controls(page, module)
                require(controls, f"active module has no visible controls: {module}")
                failures = [
                    item
                    for item in controls
                    if not item["inside"] or not item["unobscured"] or not item["focused"]
                ]
                if overflow > 1:
                    failures.append(
                        {
                            "module": module,
                            "kind": "horizontal_overflow",
                            "overflow_px": overflow,
                        }
                    )
                report["failures"].extend(failures)
                report["module_reports"].append(
                    {
                        "module": module,
                        "navigation": navigation,
                        "visible_controls": len(controls),
                        "horizontal_overflow_px": overflow,
                        "failures": failures,
                    }
                )
            except Exception as exc:
                failure = {
                    "module": module,
                    "kind": "module_probe_error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
                report["failures"].append(failure)
                report["module_reports"].append(
                    {"module": module, "navigation": None, "failures": [failure]}
                )
        screenshot_module = "geometry" if "geometry" in modules else modules[0]
        activate_module(page, screenshot_module)
        screenshot = EVIDENCE_ROOT / f"visual-{width}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        report.update(
            {
                "max_horizontal_overflow_px": max_overflow,
                "screenshot": screenshot.name,
                "screenshot_size_bytes": screenshot.stat().st_size,
            }
        )
    except Exception as exc:
        report["failures"].append(
            {
                "kind": "width_probe_error",
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        report["failures"].extend(
            {"kind": "console_error", "message": item} for item in console_errors
        )
        report["failures"].extend(
            {"kind": "page_error", "message": item} for item in page_errors
        )
        report["console_errors"] = console_errors
        report["page_errors"] = page_errors
        page.close()
    return report


def main() -> int:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    if SERVER_LOG.exists():
        SERVER_LOG.unlink()
    report: dict[str, Any] = {
        "schema": 1,
        "probe": "VISUAL_REACHABILITY_FIVE_WIDTH",
        "candidate_sha": SOURCE_SHA,
        "runtime": "real_uvicorn_fastapi_playwright_chromium",
        "route_mocks": False,
        "viewport_widths": list(VIEWPORT_WIDTHS),
        "viewport_height": VIEWPORT_HEIGHT,
        "release_status": "RELEASE_BLOCKED",
        "status": "PROBE_FAILED",
        "width_reports": [],
    }
    process: subprocess.Popen[bytes] | None = None
    log: Any | None = None
    try:
        require(FIXTURE.is_file(), f"frozen fixture missing: {FIXTURE}")
        process, log = start_server()
        asset = prepare_real_project()
        report["fixture_asset_id"] = asset["id"]
        report["fixture_sha256"] = asset["sha256"]
        with sync_playwright() as manager:
            browser = launch_browser(manager)
            try:
                report["width_reports"] = [
                    width_probe(browser, width) for width in VIEWPORT_WIDTHS
                ]
            finally:
                browser.close()
        failures = [
            failure
            for width_report in report["width_reports"]
            for failure in width_report["failures"]
        ]
        report["failure_count"] = len(failures)
        if failures:
            report["status"] = "DEFECT_REPRODUCED"
            print(
                f"VISUAL_REACHABILITY_FIVE_WIDTH: DEFECT_REPRODUCED failures={len(failures)}",
                file=sys.stderr,
            )
            return 1
        report["status"] = "VERIFIED_L2_NO_REACHABILITY_DEFECTS"
        print("VISUAL_REACHABILITY_FIVE_WIDTH: VERIFIED_L2_NO_REACHABILITY_DEFECTS")
        return 0
    except Exception as exc:
        report["status"] = "PROBE_FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(f"VISUAL_REACHABILITY_FIVE_WIDTH: PROBE_FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        stop_server(process, log)
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            "utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
