from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = SOURCE_ROOT / "tests" / "fixtures" / "pilot_v1" / "generated"
EVIDENCE_ROOT = Path(
    os.environ.get(
        "PILOT_EVIDENCE_DIR",
        SOURCE_ROOT / "artifacts" / "pilot-m2b-route",
    )
).resolve()
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime-data"
REPORT_PATH = EVIDENCE_ROOT / "m2b-pilot-route.json"
MANIFEST_PATH = EVIDENCE_ROOT / "m2b-pilot-output-manifest.json"
SERVER_LOG = EVIDENCE_ROOT / "m2b-pilot-server.log"
HOST = "127.0.0.1"
PORT = 8767
ORIGIN = f"http://{HOST}:{PORT}"
PROJECT_ID = "PILOT-M2B-01"
SOURCE_SHA = os.environ.get("PILOT_SOURCE_SHA", "unknown").strip() or "unknown"

FIXTURES = (
    "rep_non_uniform_background.png",
    "rep_text_logo.png",
    "rep_transparency.png",
    "rep_low_resolution.png",
)


class ProbeError(AssertionError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
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
        normalized_headers = {key.lower(): value for key, value in response.getheaders()}
        status = response.status
    finally:
        connection.close()
    return status, normalized_headers, data


def decode_body(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return data.decode("utf-8", "replace")[:4000]


def require_http(
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
    expected: tuple[int, ...] = (200,),
    timeout: float = 120.0,
) -> dict[str, Any]:
    status, headers, data = request(
        method,
        path,
        json_body=json_body,
        timeout=timeout,
    )
    if status not in expected:
        raise ProbeError(f"{method} {path}: HTTP {status}; {decode_body(data)!r}")
    if not headers.get("content-type", "").startswith("application/json"):
        raise ProbeError(f"{method} {path}: JSON response expected")
    payload = decode_body(data)
    if not isinstance(payload, dict):
        raise ProbeError(f"{method} {path}: object response expected")
    return payload


def multipart_file(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"ImageLabM2B{uuid.uuid4().hex}"
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
    deadline = time.monotonic() + 90.0
    last_error = "runtime did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            raise ProbeError(f"runtime exited with code {process.returncode}")
        try:
            status, _, data = request("GET", "/api/health", timeout=2.0)
            if status == 200 and decode_body(data).get("app") == "ImageLab by LarannA":
                return process, log
        except Exception as exc:  # startup polling only
            last_error = str(exc)
        time.sleep(0.5)
    stop_server(process, log)
    raise ProbeError(f"runtime startup timeout: {last_error}")


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


def image_from_bytes(data: bytes) -> tuple[Image.Image, np.ndarray, dict[str, Any]]:
    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        rgba = opened.convert("RGBA")
        dpi = opened.info.get("dpi")
        info = {
            "format": opened.format,
            "mode": opened.mode,
            "width": opened.width,
            "height": opened.height,
            "dpi": None
            if not isinstance(dpi, tuple)
            else [round(float(dpi[0]), 4), round(float(dpi[1]), 4)],
        }
        return rgba.copy(), np.asarray(rgba, dtype=np.uint8).copy(), info


def alpha_metrics(array: np.ndarray) -> dict[str, float]:
    alpha = array[:, :, 3]
    visible = alpha > 16
    height, width = visible.shape
    border = max(1, int(round(min(height, width) * 0.02)))
    frame = np.zeros_like(visible)
    frame[:border, :] = True
    frame[-border:, :] = True
    frame[:, :border] = True
    frame[:, -border:] = True
    selected = int(visible.sum())
    return {
        "coverage": selected / float(max(1, height * width)),
        "border_ratio": int((visible & frame).sum()) / float(max(1, selected)),
        "alpha_zero_ratio": float((alpha == 0).mean()),
        "alpha_partial_ratio": float(((alpha > 0) & (alpha < 255)).mean()),
    }


def main() -> int:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    if SERVER_LOG.exists():
        SERVER_LOG.unlink()

    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    outputs: dict[str, dict[str, Any]] = {}
    source_assets: dict[str, dict[str, Any]] = {}
    source_bytes: dict[str, bytes] = {}
    successful_assets: dict[str, dict[str, Any]] = {}

    report: dict[str, Any] = {
        "schema": 1,
        "probe": "M2B_PILOT_ROUTE",
        "candidate_sha": SOURCE_SHA,
        "runtime": "real_uvicorn_fastapi_http_filesystem",
        "route_mocks": False,
        "project_id": PROJECT_ID,
        "release_status": "RELEASE_BLOCKED",
        "status": "PROBE_FAILED",
        "checks": checks,
        "failures": failures,
    }

    def check(code: str, passed: bool, detail: str, **evidence: Any) -> None:
        item = {"code": code, "passed": bool(passed), "detail": detail, **evidence}
        checks.append(item)
        if not passed:
            failures.append(item)

    def download(asset: dict[str, Any]) -> bytes:
        status, _, data = request("GET", asset["download_url"])
        if status != 200:
            raise ProbeError(f"download {asset['id']}: HTTP {status}")
        return data

    def process_operation(
        label: str,
        asset_id: str,
        operation: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        status, _, data = request(
            "POST",
            f"/api/projects/{PROJECT_ID}/process",
            json_body={
                "asset_id": asset_id,
                "operation": operation,
                "parameters": {
                    **parameters,
                    "auto_repair": False,
                    "learn_from_result": False,
                },
            },
        )
        payload = decode_body(data)
        if status != 200 or not isinstance(payload, dict):
            check(
                f"{label}_http",
                False,
                f"expected HTTP 200, got {status}",
                response=payload,
            )
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            check(f"{label}_result", False, "result asset missing", response=payload)
            return None
        check(
            f"{label}_lineage",
            payload.get("source_asset_id") == asset_id
            and result.get("source_asset_id") == asset_id,
            "operation must point to the exact selected asset",
            selected_asset_id=asset_id,
            response_source_asset_id=payload.get("source_asset_id"),
            result_source_asset_id=result.get("source_asset_id"),
        )
        successful_assets[label] = result
        return result

    process: subprocess.Popen[bytes] | None = None
    log: Any | None = None
    try:
        missing = [name for name in FIXTURES if not (FIXTURE_ROOT / name).is_file()]
        if missing:
            raise ProbeError(f"frozen fixtures missing: {missing}")

        process, log = start_server()
        require_http(
            "POST",
            f"/api/projects/{PROJECT_ID}",
            json_body={"title": "Pilot M2B route"},
            expected=(200,),
        )

        # Runtime-served geometry contract: canvas/margin support must be wired
        # by the actual user action rather than inferred from static mock tests.
        status, _, app_js_bytes = request("GET", "/static/app.js")
        app_js = app_js_bytes.decode("utf-8", "replace")
        start = app_js.find("$('#applyGeometry').addEventListener")
        end = app_js.find("data-export-format", start if start >= 0 else 0)
        geometry_action = app_js[start:end] if start >= 0 and end > start else ""
        required_geometry_tokens = (
            "canvas_width_mm",
            "canvas_height_mm",
            "margin_top_mm",
            "margin_right_mm",
            "margin_bottom_mm",
            "margin_left_mm",
        )
        canvas_wired = bool(geometry_action) and all(
            token in geometry_action for token in required_geometry_tokens
        )
        check(
            "geometry_canvas_margin_runtime_contract",
            status == 200 and canvas_wired,
            "served applyGeometry action must transmit a canvas or margin contract",
            served_status=status,
            geometry_action=geometry_action,
        )

        for filename in FIXTURES:
            raw = (FIXTURE_ROOT / filename).read_bytes()
            body, boundary = multipart_file(filename, raw)
            status, headers, data = request(
                "POST",
                f"/api/projects/{PROJECT_ID}/upload",
                body=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            payload = decode_body(data)
            if status != 200 or not isinstance(payload, dict):
                raise ProbeError(f"upload {filename}: HTTP {status}; {payload!r}")
            asset = payload["uploaded"][0]
            source_assets[filename] = asset
            source_bytes[filename] = raw
            check(
                f"upload_{filename}_hash",
                asset.get("sha256") == sha256(raw),
                "uploaded source hash must match frozen fixture",
                expected_sha256=sha256(raw),
                actual_sha256=asset.get("sha256"),
            )
            downloaded = download(asset)
            check(
                f"upload_{filename}_roundtrip",
                downloaded == raw,
                "uploaded source bytes must round-trip unchanged",
            )

        non_uniform = source_assets["rep_non_uniform_background.png"]
        text_logo = source_assets["rep_text_logo.png"]
        transparency = source_assets["rep_transparency.png"]
        low_resolution = source_assets["rep_low_resolution.png"]

        background = process_operation(
            "background",
            non_uniform["id"],
            "background",
            {
                "action": "remove",
                "mode": "object",
                "ai_sensitivity": 55,
                "feather": 1,
                "ai_auto": True,
            },
        )
        if background:
            raw = download(background)
            _, array, info = image_from_bytes(raw)
            metrics = alpha_metrics(array)
            check(
                "background_dimensions",
                (info["width"], info["height"])
                == (non_uniform["width_px"], non_uniform["height_px"]),
                "background removal must preserve pixel dimensions",
                actual=info,
            )
            check(
                "background_alpha_boundary",
                0.01 <= metrics["coverage"] <= 0.90
                and metrics["border_ratio"] <= 0.03,
                "auto background mask must have useful coverage and clean frame",
                metrics=metrics,
            )
            source_array = image_from_bytes(source_bytes["rep_non_uniform_background.png"])[1]
            visible = array[:, :, 3] > 16
            rgb_equal = bool(np.array_equal(array[:, :, :3][visible], source_array[:, :, :3][visible]))
            check(
                "background_subject_rgb_unchanged",
                rgb_equal,
                "background removal may alter alpha but not visible subject RGB",
            )
            outputs["background"] = {
                "asset": background,
                "sha256": sha256(raw),
                "image": info,
                "alpha": metrics,
            }
            (EVIDENCE_ROOT / "background-result.png").write_bytes(raw)

        extracted = process_operation(
            "extract_print",
            text_logo["id"],
            "extract_print",
            {
                "mode": "auto",
                "sensitivity": 58,
                "texture_reduction": 0,
                "reduce_fabric_texture": False,
                "feather": 1,
                "crop_output": False,
                "padding_mm": 0,
                "ai_auto": True,
            },
        )
        if extracted:
            raw = download(extracted)
            _, array, info = image_from_bytes(raw)
            metrics = alpha_metrics(array)
            check(
                "extract_dimensions",
                (info["width"], info["height"])
                == (text_logo["width_px"], text_logo["height_px"]),
                "crop_output=false must preserve dimensions",
                actual=info,
            )
            check(
                "extract_alpha_boundary",
                0.002 <= metrics["coverage"] <= 0.94
                and metrics["border_ratio"] <= 0.03,
                "extracted print must be useful, transparent and detached from frame",
                metrics=metrics,
            )
            outputs["extract_print"] = {
                "asset": extracted,
                "sha256": sha256(raw),
                "image": info,
                "alpha": metrics,
            }
            (EVIDENCE_ROOT / "extract-print-result.png").write_bytes(raw)

        selected = process_operation(
            "manual_selection",
            text_logo["id"],
            "select",
            {
                "mode": "element",
                "grow_mm": 0,
                "brush_mm": 5,
                "feather": 0,
                "ai_auto": False,
                "manual_edits": [
                    {
                        "tool": "rectangle",
                        "points": [[0.16, 0.12], [0.92, 0.78]],
                    }
                ],
            },
        )
        selected_array: np.ndarray | None = None
        if selected:
            selected_raw = download(selected)
            _, selected_array, selected_info = image_from_bytes(selected_raw)
            selected_metrics = alpha_metrics(selected_array)
            check(
                "manual_selection_coverage",
                0.20 <= selected_metrics["coverage"] <= 0.60
                and selected_metrics["border_ratio"] == 0.0,
                "manual rectangle must produce a bounded non-empty mask",
                metrics=selected_metrics,
            )
            outputs["manual_selection"] = {
                "asset": selected,
                "sha256": sha256(selected_raw),
                "image": selected_info,
                "alpha": selected_metrics,
            }
            (EVIDENCE_ROOT / "manual-selection-result.png").write_bytes(selected_raw)

        cleanup_parent = selected or transparency
        cleanup = process_operation(
            "cleanup",
            cleanup_parent["id"],
            "cleanup",
            {
                "remove_background": False,
                "remove_halo": True,
                "remove_color": False,
                "defect_cleanup": 0,
                "binary_alpha": False,
                "ai_auto": False,
            },
        )
        cleanup_array: np.ndarray | None = None
        if cleanup:
            raw = download(cleanup)
            _, cleanup_array, info = image_from_bytes(raw)
            parent_raw = download(cleanup_parent)
            _, parent_array, parent_info = image_from_bytes(parent_raw)
            check(
                "cleanup_geometry_unchanged",
                cleanup_array.shape == parent_array.shape
                and cleanup.get("ppi_x") == cleanup_parent.get("ppi_x")
                and cleanup.get("ppi_y") == cleanup_parent.get("ppi_y"),
                "conservative cleanup must preserve geometry and PPI",
                input=parent_info,
                output=info,
            )
            interior = (parent_array[:, :, 3] >= 250) & (cleanup_array[:, :, 3] >= 250)
            mae = (
                float(
                    np.abs(
                        cleanup_array[:, :, :3][interior].astype(np.int16)
                        - parent_array[:, :, :3][interior].astype(np.int16)
                    ).mean()
                )
                if np.any(interior)
                else 0.0
            )
            check(
                "cleanup_interior_color_unchanged",
                mae <= 0.5,
                "halo cleanup must not silently recolor fully opaque interior pixels",
                mean_absolute_rgb_error=mae,
            )
            if selected_array is not None:
                outside = selected_array[:, :, 3] <= 8
                outside_alpha_ok = bool(np.all(cleanup_array[:, :, 3][outside] <= 8))
                outside_rgb_ok = bool(
                    np.array_equal(
                        cleanup_array[:, :, :3][outside],
                        selected_array[:, :, :3][outside],
                    )
                )
                check(
                    "cleanup_outside_manual_mask_unchanged",
                    outside_alpha_ok and outside_rgb_ok,
                    "cleanup must not change pixels outside the manual selection",
                    outside_alpha_ok=outside_alpha_ok,
                    outside_rgb_ok=outside_rgb_ok,
                )
            outputs["cleanup"] = {
                "asset": cleanup,
                "sha256": sha256(raw),
                "image": info,
            }
            (EVIDENCE_ROOT / "cleanup-result.png").write_bytes(raw)

        geometry_parent = cleanup or selected or transparency
        linked = process_operation(
            "geometry_linked",
            geometry_parent["id"],
            "geometry",
            {
                "width_mm": 50.8,
                "height_mm": "",
                "ppi": 300,
                "preserve_aspect": True,
                "rotate": 0,
                "crop": {"x": 0, "y": 0, "width": 100, "height": 100},
                "ai_auto_crop": False,
            },
        )
        if linked:
            raw = download(linked)
            _, _, info = image_from_bytes(raw)
            expected_width = 600
            expected_height = int(round(expected_width * geometry_parent["height_px"] / geometry_parent["width_px"]))
            check(
                "geometry_linked_binary",
                (info["width"], info["height"]) == (expected_width, expected_height)
                and info["dpi"] is not None
                and abs(info["dpi"][0] - 300) <= 1.0
                and abs(info["dpi"][1] - 300) <= 1.0,
                "linked width/PPI request must match decoded PNG",
                expected=[expected_width, expected_height, 300],
                actual=info,
            )
            outputs["geometry_linked"] = {
                "asset": linked,
                "sha256": sha256(raw),
                "image": info,
            }
            (EVIDENCE_ROOT / "geometry-linked-result.png").write_bytes(raw)

        unlinked = process_operation(
            "geometry_unlinked",
            geometry_parent["id"],
            "geometry",
            {
                "width_mm": 50.8,
                "height_mm": 50.8,
                "ppi": 300,
                "preserve_aspect": False,
                "rotate": 0,
                "crop": {"x": 0, "y": 0, "width": 100, "height": 100},
                "ai_auto_crop": False,
            },
        )
        if unlinked:
            raw = download(unlinked)
            _, _, info = image_from_bytes(raw)
            check(
                "geometry_unlinked_binary",
                (info["width"], info["height"]) == (600, 600)
                and info["dpi"] is not None
                and abs(info["dpi"][0] - 300) <= 1.0
                and abs(info["dpi"][1] - 300) <= 1.0,
                "unlinked width/height/PPI request must match decoded PNG",
                expected=[600, 600, 300],
                actual=info,
            )
            outputs["geometry_unlinked"] = {
                "asset": unlinked,
                "sha256": sha256(raw),
                "image": info,
            }
            (EVIDENCE_ROOT / "geometry-unlinked-result.png").write_bytes(raw)

        canvas_geometry = process_operation(
            "geometry_canvas",
            text_logo["id"],
            "geometry",
            {
                "width_mm": 50.8,
                "height_mm": "",
                "ppi": 300,
                "preserve_aspect": True,
                "rotate": 0,
                "crop": {"x": 0, "y": 0, "width": 100, "height": 100},
                "canvas_width_mm": 60.96,
                "canvas_height_mm": 30.48,
                "margin_top_mm": 2.54,
                "margin_right_mm": 5.08,
                "margin_bottom_mm": 2.54,
                "margin_left_mm": 5.08,
                "ai_auto_crop": False,
            },
        )
        if canvas_geometry:
            raw = download(canvas_geometry)
            _, array, info = image_from_bytes(raw)
            alpha = array[:, :, 3]
            ys, xs = np.nonzero(alpha > 250)
            alpha_box = (
                [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                if xs.size and ys.size
                else None
            )
            check(
                "geometry_canvas_margin_binary",
                (info["width"], info["height"]) == (720, 360)
                and info["dpi"] is not None
                and abs(info["dpi"][0] - 300) <= 1.0
                and abs(info["dpi"][1] - 300) <= 1.0
                and alpha_box == [60, 30, 660, 330]
                and bool(np.all(alpha[:30, :] == 0))
                and bool(np.all(alpha[-30:, :] == 0))
                and bool(np.all(alpha[:, :60] == 0))
                and bool(np.all(alpha[:, -60:] == 0)),
                "canvas dimensions, exact margins, placement and embedded PPI must match request",
                expected={"pixels": [720, 360], "alpha_box": [60, 30, 660, 330], "ppi": 300},
                actual={"image": info, "alpha_box": alpha_box},
            )
            outputs["geometry_canvas"] = {
                "asset": canvas_geometry,
                "sha256": sha256(raw),
                "image": info,
                "alpha_box": alpha_box,
            }
            (EVIDENCE_ROOT / "geometry-canvas-result.png").write_bytes(raw)

        before_invalid_canvas = require_http("GET", f"/api/projects/{PROJECT_ID}")
        invalid_canvas_status, _, invalid_canvas_data = request(
            "POST",
            f"/api/projects/{PROJECT_ID}/process",
            json_body={
                "asset_id": text_logo["id"],
                "operation": "geometry",
                "parameters": {
                    "width_mm": 50.8,
                    "height_mm": "",
                    "ppi": 300,
                    "preserve_aspect": True,
                    "canvas_width_mm": 50.8,
                    "canvas_height_mm": 25.4,
                    "margin_left_mm": 5.08,
                    "margin_right_mm": 5.08,
                    "margin_top_mm": 2.54,
                    "margin_bottom_mm": 2.54,
                    "auto_repair": False,
                    "learn_from_result": False,
                },
            },
        )
        after_invalid_canvas = require_http("GET", f"/api/projects/{PROJECT_ID}")
        check(
            "geometry_invalid_canvas_blocked",
            invalid_canvas_status == 422
            and len(before_invalid_canvas["assets"]) == len(after_invalid_canvas["assets"]),
            "canvas smaller than image plus margins must fail without creating an asset",
            http_status=invalid_canvas_status,
            response=decode_body(invalid_canvas_data),
            assets_before=len(before_invalid_canvas["assets"]),
            assets_after=len(after_invalid_canvas["assets"]),
        )

        before_invalid_margin = require_http("GET", f"/api/projects/{PROJECT_ID}")
        invalid_margin_status, _, invalid_margin_data = request(
            "POST",
            f"/api/projects/{PROJECT_ID}/process",
            json_body={
                "asset_id": text_logo["id"],
                "operation": "geometry",
                "parameters": {
                    "width_mm": 50.8,
                    "height_mm": "",
                    "ppi": 300,
                    "preserve_aspect": True,
                    "margin_left_mm": -1,
                    "auto_repair": False,
                    "learn_from_result": False,
                },
            },
        )
        after_invalid_margin = require_http("GET", f"/api/projects/{PROJECT_ID}")
        check(
            "geometry_negative_margin_blocked",
            invalid_margin_status == 422
            and len(before_invalid_margin["assets"]) == len(after_invalid_margin["assets"]),
            "negative margin must fail without creating an asset",
            http_status=invalid_margin_status,
            response=decode_body(invalid_margin_data),
            assets_before=len(before_invalid_margin["assets"]),
            assets_after=len(after_invalid_margin["assets"]),
        )

        before_invalid = require_http("GET", f"/api/projects/{PROJECT_ID}")
        invalid_status, _, invalid_data = request(
            "POST",
            f"/api/projects/{PROJECT_ID}/process",
            json_body={
                "asset_id": geometry_parent["id"],
                "operation": "geometry",
                "parameters": {
                    "width_mm": 0,
                    "height_mm": "",
                    "ppi": 300,
                    "preserve_aspect": True,
                    "auto_repair": False,
                    "learn_from_result": False,
                },
            },
        )
        after_invalid = require_http("GET", f"/api/projects/{PROJECT_ID}")
        check(
            "geometry_invalid_input_blocked",
            invalid_status == 422
            and len(before_invalid["assets"]) == len(after_invalid["assets"]),
            "invalid physical size must fail without creating an asset",
            http_status=invalid_status,
            response=decode_body(invalid_data),
            assets_before=len(before_invalid["assets"]),
            assets_after=len(after_invalid["assets"]),
        )

        positive_asset = linked or cleanup or selected or transparency
        positive_qa = require_http(
            "GET",
            f"/api/projects/{PROJECT_ID}/qa?asset_id={positive_asset['id']}",
        )
        check(
            "qa_positive",
            positive_qa.get("overall_passed") is True,
            "valid pilot result must pass deterministic QA",
            qa=positive_qa,
        )
        negative_qa = require_http(
            "GET",
            f"/api/projects/{PROJECT_ID}/qa?asset_id={low_resolution['id']}",
        )
        check(
            "qa_negative_low_resolution",
            negative_qa.get("overall_passed") is False,
            "32×32 adversarial fixture must not be accepted as a pilot-ready output",
            qa=negative_qa,
        )

        def export_asset(
            label: str,
            asset: dict[str, Any],
            format_name: str,
        ) -> dict[str, Any] | None:
            status, _, data = request(
                "POST",
                f"/api/projects/{PROJECT_ID}/export",
                json_body={
                    "asset_id": asset["id"],
                    "format": format_name,
                    "parameters": {
                        "filename": f"pilot-{label}",
                        "ppi": 300,
                        "keep_alpha": True,
                        "strip_metadata": False,
                        "ai_auto": False,
                        "allow_ai_warning": True,
                        "learn_from_result": False,
                    },
                },
            )
            payload = decode_body(data)
            if status != 200 or not isinstance(payload, dict):
                check(
                    f"{label}_export_http",
                    False,
                    f"expected HTTP 200, got {status}",
                    response=payload,
                )
                return None
            result = payload.get("result")
            if not isinstance(result, dict):
                check(f"{label}_export_result", False, "export result missing")
                return None
            raw = download(result)
            _, array, info = image_from_bytes(raw)
            metrics = alpha_metrics(array)
            check(
                f"{label}_export_lineage",
                payload.get("source_asset_id") == asset["id"]
                and result.get("source_asset_id") == asset["id"],
                "export must preserve selected-asset lineage",
            )
            check(
                f"{label}_export_binary",
                result.get("sha256") == sha256(raw)
                and info["format"] == "PNG"
                and info["dpi"] is not None
                and abs(info["dpi"][0] - 300) <= 1.0
                and abs(info["dpi"][1] - 300) <= 1.0,
                "downloaded export must match metadata and embedded PPI",
                asset=result,
                decoded=info,
            )
            successful_assets[label] = result
            outputs[label] = {
                "asset": result,
                "sha256": sha256(raw),
                "image": info,
                "alpha": metrics,
            }
            output_path = EVIDENCE_ROOT / f"{label}.png"
            output_path.write_bytes(raw)
            return result

        png_export = export_asset("png-export", positive_asset, "PNG")
        dtf_source = cleanup or extracted or selected or transparency
        png_dtf_export = export_asset("png-dtf-export", dtf_source, "PNG_DTF")
        if png_dtf_export:
            dtf_metrics = outputs["png-dtf-export"]["alpha"]
            check(
                "png_dtf_transparency",
                dtf_metrics["alpha_zero_ratio"] > 0
                and 0.002 <= dtf_metrics["coverage"] <= 0.98,
                "basic PNG DTF must retain a useful transparent contour",
                metrics=dtf_metrics,
            )

        # Every original source must remain byte-identical after all operations.
        for filename, asset in source_assets.items():
            current = download(asset)
            check(
                f"source_immutable_{filename}",
                current == source_bytes[filename],
                "processing and export must never mutate original source bytes",
                expected_sha256=sha256(source_bytes[filename]),
                actual_sha256=sha256(current),
            )

        project_before_restart = require_http("GET", f"/api/projects/{PROJECT_ID}")
        persisted_ids = {asset["id"] for asset in project_before_restart["assets"]}
        stop_server(process, log)
        process = None
        log = None
        process, log = start_server()
        project_after_restart = require_http("GET", f"/api/projects/{PROJECT_ID}")
        after_by_id = {asset["id"]: asset for asset in project_after_restart["assets"]}
        check(
            "restart_asset_set",
            persisted_ids == set(after_by_id),
            "all project assets must survive runtime restart",
            before_count=len(persisted_ids),
            after_count=len(after_by_id),
        )
        for label, asset in successful_assets.items():
            restored = after_by_id.get(asset["id"])
            check(
                f"restart_{label}",
                restored is not None
                and restored.get("sha256") == asset.get("sha256")
                and restored.get("source_asset_id") == asset.get("source_asset_id"),
                "asset hash and lineage must survive restart",
                asset_id=asset["id"],
            )

        project_file = RUNTIME_ROOT / "projects" / f"{PROJECT_ID}.json"
        check(
            "project_json_persisted",
            project_file.is_file(),
            "project JSON must exist in the configured runtime data root",
            path=str(project_file),
        )
        if project_file.is_file():
            shutil.copy2(project_file, EVIDENCE_ROOT / f"{PROJECT_ID}.json")

        bundle_status, bundle_headers, bundle_data = request(
            "GET", f"/api/projects/{PROJECT_ID}/bundle"
        )
        bundle_ok = bundle_status == 200 and bundle_headers.get(
            "content-type", ""
        ).startswith("application/zip")
        if bundle_ok:
            try:
                with zipfile.ZipFile(io.BytesIO(bundle_data)) as archive:
                    bundle_ok = archive.testzip() is None and {
                        "project.json",
                        "report.json",
                    }.issubset(archive.namelist())
            except zipfile.BadZipFile:
                bundle_ok = False
        check(
            "project_bundle",
            bundle_ok,
            "project bundle must be a readable ZIP with project/report metadata",
        )
        if bundle_ok:
            (EVIDENCE_ROOT / "m2b-pilot-project-bundle.zip").write_bytes(bundle_data)

        manifest = {
            "schema": 1,
            "candidate_sha": SOURCE_SHA,
            "project_id": PROJECT_ID,
            "release_status": "RELEASE_BLOCKED",
            "outputs": outputs,
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            "utf-8",
        )
        report["output_manifest_sha256"] = sha256(MANIFEST_PATH.read_bytes())
        report["failure_count"] = len(failures)
        report["check_count"] = len(checks)
        report["outputs"] = outputs
        if failures:
            report["status"] = "DEFECTS_REPRODUCED"
            print(
                f"M2B_PILOT_ROUTE: DEFECTS_REPRODUCED failures={len(failures)} checks={len(checks)}",
                file=sys.stderr,
            )
            return 1
        report["status"] = "VERIFIED_L2_M2B_PILOT_ROUTE"
        print(f"M2B_PILOT_ROUTE: VERIFIED_L2 checks={len(checks)}")
        return 0
    except Exception as exc:
        report["status"] = "PROBE_FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(f"M2B_PILOT_ROUTE: PROBE_FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        stop_server(process, log)
        report.setdefault("failure_count", len(failures))
        report.setdefault("check_count", len(checks))
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            "utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(main())
