from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

PROJECT_ID = "TS-001"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def fixture(path: Path) -> None:
    image = Image.new("RGB", (320, 240), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 35, 250, 220), radius=25, fill=(35, 35, 40))
    draw.ellipse((120, 80, 200, 160), fill=(240, 70, 30))
    draw.rectangle((145, 155, 175, 210), fill=(250, 210, 40))
    image.save(path, format="PNG", dpi=(300, 300))


def project(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """async (projectId) => {
          const response = await fetch(`/api/projects/${projectId}`, {cache: 'no-store'});
          if (!response.ok) throw new Error(await response.text());
          return await response.json();
        }""",
        PROJECT_ID,
    )


def wait_project(page: Page, predicate, *, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = project(page)
        if predicate(last):
            return last
        page.wait_for_timeout(300)
    raise RuntimeError(f"project state timeout; last={last}")


def active_asset(record: dict[str, Any]) -> dict[str, Any]:
    active_id = record.get("workspace", {}).get("active_asset_id")
    for asset in record.get("assets", []):
        if asset.get("id") == active_id:
            return asset
    raise RuntimeError(f"active asset not found: {active_id}")


def wait_not_busy(page: Page, timeout: float = 120.0) -> None:
    page.wait_for_function("() => !document.body.classList.contains('busy')", timeout=timeout * 1000)


def save_asset(base_url: str, asset: dict[str, Any], output: Path) -> dict[str, Any]:
    data = get_bytes(f"{base_url}/api/assets/{asset['id']}/file")
    output.write_bytes(data)
    return {"path": str(output), "sha256": sha256_bytes(data), "size_bytes": len(data), "asset_id": asset["id"]}


def click_history(page: Page, asset_id: str) -> dict[str, Any]:
    selector = f'.history-thumb[data-asset-id="{asset_id}"]'
    page.locator(selector).click()
    return wait_project(page, lambda p: p.get("workspace", {}).get("active_asset_id") == asset_id, timeout=30)


def run(args: argparse.Namespace) -> dict[str, Any]:
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    screenshots = evidence / "screenshots"
    outputs = evidence / "generated-files"
    videos = evidence / "videos"
    screenshots.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    videos.mkdir(exist_ok=True)
    fixture_path = evidence / "release-gate-fixture.png"
    fixture(fixture_path)

    health = get_json(f"{args.base_url}/api/health")
    for key, expected in (("version", args.expected_version), ("build_id", args.expected_build_id), ("install_id", args.expected_install_id)):
        if expected and health.get(key) != expected:
            raise RuntimeError(f"health {key} mismatch: {health.get(key)!r} != {expected!r}")

    results: dict[str, Any] = {
        "schema": 1,
        "status": "IN_PROGRESS",
        "installer_sha256": args.installer_sha256,
        "health": health,
        "browser_channel": args.browser_channel,
        "steps": {},
        "outputs": {},
    }

    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": True}
        if args.browser_channel != "bundled":
            launch_options["channel"] = args.browser_channel
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(record_video_dir=str(videos), viewport={"width": 1600, "height": 1000})
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            page.goto(args.base_url, wait_until="networkidle", timeout=90_000)
            page.locator("#buildVersionChip").wait_for(state="visible")
            page.wait_for_function(
                """([version, build, install]) => {
                  const chip = document.querySelector('#buildVersionChip');
                  if (!chip) return false;
                  const text = chip.textContent || '';
                  const title = chip.getAttribute('title') || '';
                  return chip.classList.contains('ready')
                    && text.includes(version)
                    && text.includes(String(install).slice(0, 8))
                    && title.includes(build)
                    && title.includes(install);
                }""",
                arg=[args.expected_version, args.expected_build_id, args.expected_install_id],
                timeout=30_000,
            )
            page.screenshot(path=str(screenshots / "00-start.png"), full_page=True)

            # Ensure an empty deterministic project.
            current = project(page)
            if current.get("assets"):
                page.once("dialog", lambda dialog: dialog.accept())
                page.locator("#clearButton").click()
                wait_project(page, lambda p: len(p.get("assets", [])) == 0, timeout=30)

            page.locator("#fileInput").set_input_files(str(fixture_path))
            uploaded = wait_project(page, lambda p: len(p.get("assets", [])) == 1, timeout=60)
            source = active_asset(uploaded)
            source_id = source["id"]
            results["steps"]["upload"] = {"status": "PASS", "asset_id": source_id, "sha256": source["sha256"]}
            page.screenshot(path=str(screenshots / "01-upload.png"), full_page=True)

            # Resize + PPI through the real UI.
            page.locator('[data-module="improve"]').click()
            page.locator("#improveWidthMm").fill("50.8")
            page.locator("#improveHeightMm").fill("")
            page.locator("#improvePpi").fill("200")
            page.locator("#improvePreserveAspect").check()
            before_count = len(uploaded["assets"])
            page.locator("#applyEnhance").click()
            resized_project = wait_project(page, lambda p: len(p.get("assets", [])) > before_count and active_asset(p).get("operation") == "enhance", timeout=120)
            resized = active_asset(resized_project)
            if [resized.get("width_px"), resized.get("height_px")] != [400, 300]:
                raise RuntimeError(f"UI resize did not produce 400x300: {resized}")
            if abs(float(resized.get("ppi_x") or 0) - 200.0) > 0.01:
                raise RuntimeError(f"UI PPI did not change to 200: {resized.get('ppi_x')}")
            results["steps"]["resize_ppi"] = {"status": "PASS", "source_asset_id": resized.get("source_asset_id"), "asset_id": resized["id"], "size_px": [400, 300], "ppi": resized["ppi_x"]}
            results["outputs"]["resized"] = save_asset(args.base_url, resized, outputs / "resized.png")
            page.screenshot(path=str(screenshots / "02-resize.png"), full_page=True)

            # History switching must be immediate and server-authoritative.
            click_history(page, source_id)
            if page.locator(f'.history-thumb[data-asset-id="{source_id}"]').get_attribute("aria-pressed") != "true":
                raise RuntimeError("source history thumbnail was not visually activated")
            click_history(page, resized["id"])
            if page.locator(f'.history-thumb[data-asset-id="{resized["id"]}"]').get_attribute("aria-pressed") != "true":
                raise RuntimeError("result history thumbnail was not visually activated")
            results["steps"]["history_switch"] = {"status": "PASS", "source_asset_id": source_id, "result_asset_id": resized["id"]}

            # Background removal from the source.
            click_history(page, source_id)
            page.locator('[data-module="cleanup"]').click()
            page.locator("#removeBackground").check()
            page.locator("#removeHalo").uncheck()
            page.locator("#removeColor").uncheck()
            cleanup_before = len(project(page)["assets"])
            page.locator("#applyCleanup").click()
            cleaned_project = wait_project(page, lambda p: len(p.get("assets", [])) > cleanup_before and active_asset(p).get("operation") == "background", timeout=120)
            cleaned = active_asset(cleaned_project)
            results["steps"]["background"] = {"status": "PASS", "source_asset_id": cleaned.get("source_asset_id"), "asset_id": cleaned["id"]}
            results["outputs"]["background"] = save_asset(args.base_url, cleaned, outputs / "background.png")
            page.screenshot(path=str(screenshots / "03-background.png"), full_page=True)

            # Halftone from exact selected source.
            click_history(page, source_id)
            page.locator('[data-module="halftone"]').click()
            page.locator("#halftoneAiAuto").uncheck()
            page.locator("#halftoneSize").fill("0.30")
            page.locator("#halftoneMinSize").fill("0.10")
            page.locator("#halftoneMaxSize").fill("0.50")
            page.locator("#halftoneLpi").fill("35")
            halftone_before = len(project(page)["assets"])
            page.locator("#applyHalftone").click()
            halftone_project = wait_project(page, lambda p: len(p.get("assets", [])) > halftone_before and active_asset(p).get("operation") == "halftone", timeout=120)
            halftone = active_asset(halftone_project)
            if halftone.get("source_asset_id") != source_id:
                raise RuntimeError("halftone used a file other than the selected source")
            results["steps"]["halftone"] = {"status": "PASS", "source_asset_id": source_id, "asset_id": halftone["id"]}
            results["outputs"]["halftone"] = save_asset(args.base_url, halftone, outputs / "halftone.png")
            page.screenshot(path=str(screenshots / "04-halftone.png"), full_page=True)

            # Vectorization from exact selected source.
            click_history(page, source_id)
            page.locator('[data-module="vector"]').click()
            page.locator("#vectorAiAuto").uncheck()
            page.locator("#vectorColors").fill("6")
            page.locator("#vectorSimplifyMm").fill("0.15")
            page.locator("#vectorMinAreaMm2").fill("0.10")
            vector_before = len(project(page)["assets"])
            page.locator("#applyVectorize").click()
            vector_project = wait_project(page, lambda p: len(p.get("assets", [])) > vector_before and active_asset(p).get("operation") == "vectorize", timeout=120)
            vector = active_asset(vector_project)
            if vector.get("source_asset_id") != source_id or vector.get("format") != "SVG":
                raise RuntimeError(f"vectorization lineage/format invalid: {vector}")
            results["steps"]["vector"] = {"status": "PASS", "source_asset_id": source_id, "asset_id": vector["id"], "diagnostics": vector.get("parameters", {}).get("vector_diagnostics")}
            results["outputs"]["vector"] = save_asset(args.base_url, vector, outputs / "vector.svg")
            page.screenshot(path=str(screenshots / "05-vector.png"), full_page=True)

            final_project = project(page)
            results["lineage"] = {
                "active_asset_id": final_project.get("workspace", {}).get("active_asset_id"),
                "active_revision": final_project.get("workspace", {}).get("active_revision"),
                "assets": [{"id": item["id"], "operation": item.get("operation"), "source_asset_id": item.get("source_asset_id"), "sha256": item.get("sha256")} for item in final_project.get("assets", [])],
            }
            (evidence / "file-lineage.json").write_text(json.dumps(results["lineage"], ensure_ascii=False, indent=2), "utf-8")
            results["status"] = "PASS"
        except Exception:
            page.screenshot(path=str(screenshots / "99-failure.png"), full_page=True)
            raise
        finally:
            context.tracing.stop(path=str(evidence / "playwright-trace.zip"))
            context.close()
            browser.close()

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--installer-sha256", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-build-id", required=True)
    parser.add_argument("--expected-install-id", required=True)
    parser.add_argument("--browser-channel", choices=("bundled", "msedge"), default="bundled")
    args = parser.parse_args()
    output = args.evidence_dir.resolve() / "ui-gate.json"
    try:
        result = run(args)
    except Exception as exc:
        failure = {
            "schema": 1,
            "status": "FAIL",
            "installer_sha256": args.installer_sha256,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(failure, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
