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

from PIL import Image

SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = SOURCE_ROOT / "tests" / "fixtures" / "pilot_v1" / "generated" / "rep_transparency.png"
EVIDENCE_ROOT = Path(os.environ.get("PILOT_EVIDENCE_DIR", SOURCE_ROOT / "artifacts" / "pilot-alpha")).resolve()
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime-data"
TRACE_PATH = EVIDENCE_ROOT / "live-e2e-01.json"
SERVER_LOG = EVIDENCE_ROOT / "live-e2e-01-server.log"
PROJECT_ID = "PILOT-LIVE-E2E-01"
HOST = "127.0.0.1"
PORT = 8765
BASE_ORIGIN = f"http://{HOST}:{PORT}"
SOURCE_SHA = os.environ.get("PILOT_SOURCE_SHA", "unknown").strip() or "unknown"


class LiveE2EError(AssertionError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveE2EError(message)


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
    request_headers = {"Accept": "application/json", "Origin": BASE_ORIGIN}
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
    finally:
        connection.close()
    if response.status not in expected:
        text = data.decode("utf-8", "replace")
        raise LiveE2EError(f"{method} {path}: HTTP {response.status}; {text[:2000]}")
    return response.status, normalized_headers, data


def request_json(method: str, path: str, *, json_body: Any | None = None) -> dict[str, Any]:
    _, headers, data = request(method, path, json_body=json_body)
    require(headers.get("content-type", "").startswith("application/json"), f"{path}: response is not JSON")
    payload = json.loads(data.decode("utf-8"))
    require(isinstance(payload, dict), f"{path}: JSON object expected")
    return payload


def multipart_file(field: str, filename: str, media_type: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"ImageLabPilot{uuid.uuid4().hex}"
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("ascii"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode("utf-8")
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return bytes(body), boundary


def start_server() -> tuple[subprocess.Popen[bytes], Any]:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    log_stream = SERVER_LOG.open("ab", buffering=0)
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
        stdout=log_stream,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 75.0
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_stream.close()
            raise LiveE2EError(f"source runtime exited with code {process.returncode}")
        try:
            _, _, data = request("GET", "/api/health", expected=(200,), timeout=2.0)
            payload = json.loads(data.decode("utf-8"))
            require(payload.get("app") == "ImageLab by LarannA", "health app identity mismatch")
            return process, log_stream
        except Exception as exc:  # startup polling only
            last_error = str(exc)
            time.sleep(0.5)
    stop_server(process, log_stream)
    raise LiveE2EError(f"source runtime startup timeout: {last_error}")


def stop_server(process: subprocess.Popen[bytes] | None, log_stream: Any | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    if log_stream is not None and not log_stream.closed:
        log_stream.close()


def validate_png(data: bytes, expected_width: int, expected_height: int, expected_ppi: float) -> dict[str, Any]:
    require(data.startswith(b"\x89PNG\r\n\x1a\n"), "download is not PNG")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        require(image.size == (expected_width, expected_height), f"PNG dimensions {image.size}")
        dpi = image.info.get("dpi")
        require(isinstance(dpi, tuple) and len(dpi) >= 2, "PNG embedded PPI is absent")
        require(abs(float(dpi[0]) - expected_ppi) <= 1.0, f"PNG PPI X {dpi[0]}")
        require(abs(float(dpi[1]) - expected_ppi) <= 1.0, f"PNG PPI Y {dpi[1]}")
        return {
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
            "ppi_x": round(float(dpi[0]), 4),
            "ppi_y": round(float(dpi[1]), 4),
        }


def run_route(trace: list[dict[str, Any]]) -> dict[str, Any]:
    fixture_bytes = FIXTURE.read_bytes()
    fixture_sha = sha256(fixture_bytes)

    project = request_json(
        "POST",
        f"/api/projects/{PROJECT_ID}",
        json_body={"title": "Pilot LIVE-E2E-01"},
    )
    require(project["id"] == PROJECT_ID, "created project id mismatch")
    trace.append({"step": "create_project", "assets": len(project["assets"])})

    upload_body, boundary = multipart_file("files", FIXTURE.name, "image/png", fixture_bytes)
    _, headers, upload_data = request(
        "POST",
        f"/api/projects/{PROJECT_ID}/upload",
        body=upload_body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    require(headers.get("content-type", "").startswith("application/json"), "upload response is not JSON")
    upload_payload = json.loads(upload_data.decode("utf-8"))
    source = upload_payload["uploaded"][0]
    source_id = source["id"]
    require(source["sha256"] == fixture_sha, "uploaded source hash mismatch")
    require((source["width_px"], source["height_px"]) == (256, 256), "uploaded dimensions mismatch")
    require(source["format"] == "PNG" and source["has_alpha"] is True, "uploaded metadata mismatch")
    stored_source = RUNTIME_ROOT / "uploads" / source["stored_name"]
    require(stored_source.is_file(), "uploaded source was not persisted")
    require(sha256(stored_source.read_bytes()) == fixture_sha, "persisted source bytes changed")
    trace.append({"step": "upload", "asset_id": source_id, "sha256": fixture_sha})

    _, preview_headers, preview_bytes = request("GET", source["preview_url"])
    require(preview_headers.get("content-type", "").startswith("image/png"), "preview media type mismatch")
    require(preview_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "preview is not PNG")
    _, _, source_download = request("GET", source["download_url"])
    require(source_download == fixture_bytes, "downloaded source differs from uploaded bytes")
    trace.append({"step": "preview_and_source_download", "preview_sha256": sha256(preview_bytes)})

    mask_value = {
        source_id: {
            "schema": 1,
            "asset_id": source_id,
            "width": 256,
            "height": 256,
            "revision": 1,
            "strokes": [
                {"tool": "add", "radius": 18, "points": [[48, 48], [128, 128], [208, 208]]},
                {"tool": "subtract", "radius": 6, "points": [[24, 232], [48, 208]]},
            ],
        }
    }
    mask_save = request_json(
        "PUT",
        f"/api/m2a/projects/{PROJECT_ID}/workspace/masks",
        json_body={"value": mask_value},
    )
    require(mask_save["status"] == "saved", "mask save status mismatch")
    workspace = request_json("GET", f"/api/m2a/projects/{PROJECT_ID}/workspace")
    require(workspace["workspace"]["masks"] == mask_value, "mask did not round-trip")
    trace.append({"step": "mask_persistence", "revision": 1})

    process_payload = request_json(
        "POST",
        f"/api/projects/{PROJECT_ID}/process",
        json_body={
            "asset_id": source_id,
            "operation": "enhance",
            "parameters": {
                "preset": "standard",
                "width_mm": 25.4,
                "height_mm": "",
                "ppi": 200,
                "preserve_aspect": True,
                "ai_auto": False,
                "auto_repair": False,
                "learn_from_result": False,
            },
        },
    )
    processed = process_payload["result"]
    processed_id = processed["id"]
    require(processed["source_asset_id"] == source_id, "processing lineage mismatch")
    require((processed["width_px"], processed["height_px"]) == (200, 200), "processed dimensions mismatch")
    require(processed["ppi_x"] == 200 and processed["ppi_y"] == 200, "processed PPI mismatch")
    require(process_payload["project"]["workspace"]["active_asset_id"] == processed_id, "processed asset is not active")
    require(stored_source.read_bytes() == fixture_bytes, "processing mutated source bytes")
    trace.append({"step": "process", "asset_id": processed_id, "source_asset_id": source_id})

    qa = request_json("GET", f"/api/projects/{PROJECT_ID}/qa?asset_id={processed_id}")
    require(qa["project_id"] == PROJECT_ID and qa["asset_id"] == processed_id, "QA identity mismatch")
    require(isinstance(qa["checks"], list) and qa["checks"], "QA checks missing")
    trace.append({"step": "qa", "overall_passed": qa["overall_passed"], "checks": len(qa["checks"])})

    export_payload = request_json(
        "POST",
        f"/api/projects/{PROJECT_ID}/export",
        json_body={
            "asset_id": processed_id,
            "format": "PNG",
            "parameters": {
                "filename": "pilot-live-e2e-01",
                "ppi": 200,
                "keep_alpha": True,
                "strip_metadata": False,
                "ai_auto": False,
                "allow_ai_warning": True,
                "learn_from_result": False,
            },
        },
    )
    exported = export_payload["result"]
    export_id = exported["id"]
    require(exported["source_asset_id"] == processed_id, "export lineage mismatch")
    require(export_payload["project"]["workspace"]["active_asset_id"] == export_id, "exported asset is not active")
    _, _, exported_bytes = request("GET", exported["download_url"])
    require(sha256(exported_bytes) == exported["sha256"], "export download hash mismatch")
    png_evidence = validate_png(exported_bytes, 200, 200, 200)
    (EVIDENCE_ROOT / "pilot-live-e2e-01.png").write_bytes(exported_bytes)
    trace.append({"step": "export_download", "asset_id": export_id, "sha256": exported["sha256"], **png_evidence})

    _, bundle_headers, bundle_bytes = request("GET", f"/api/projects/{PROJECT_ID}/bundle")
    require(bundle_headers.get("content-type", "").startswith("application/zip"), "bundle media type mismatch")
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        require(archive.testzip() is None, "project bundle ZIP is corrupt")
        names = set(archive.namelist())
        require("project.json" in names and "report.json" in names, "bundle metadata missing")
    (EVIDENCE_ROOT / "pilot-live-e2e-01-bundle.zip").write_bytes(bundle_bytes)
    trace.append({"step": "bundle_download", "sha256": sha256(bundle_bytes), "size_bytes": len(bundle_bytes)})

    return {
        "fixture_sha256": fixture_sha,
        "source": source,
        "processed": processed,
        "exported": exported,
        "mask_value": mask_value,
        "export_sha256": sha256(exported_bytes),
    }


def verify_after_restart(route: dict[str, Any], trace: list[dict[str, Any]]) -> None:
    project = request_json("GET", f"/api/projects/{PROJECT_ID}")
    by_id = {item["id"]: item for item in project["assets"]}
    source = route["source"]
    processed = route["processed"]
    exported = route["exported"]
    for item in (source, processed, exported):
        require(item["id"] in by_id, f"asset missing after restart: {item['id']}")
        require(by_id[item["id"]]["sha256"] == item["sha256"], f"asset hash changed after restart: {item['id']}")
    require(by_id[processed["id"]]["source_asset_id"] == source["id"], "processed lineage lost after restart")
    require(by_id[exported["id"]]["source_asset_id"] == processed["id"], "export lineage lost after restart")
    require(project["workspace"]["active_asset_id"] == exported["id"], "active asset lost after restart")

    workspace = request_json("GET", f"/api/m2a/projects/{PROJECT_ID}/workspace")
    require(workspace["workspace"]["masks"] == route["mask_value"], "mask lost after restart")

    _, _, source_bytes = request("GET", source["download_url"])
    _, _, export_bytes = request("GET", exported["download_url"])
    require(sha256(source_bytes) == route["fixture_sha256"], "source bytes changed after restart")
    require(sha256(export_bytes) == route["export_sha256"], "export bytes changed after restart")

    project_file = RUNTIME_ROOT / "projects" / f"{PROJECT_ID}.json"
    require(project_file.is_file(), "persisted project JSON missing")
    persisted = json.loads(project_file.read_text("utf-8"))
    require(persisted["id"] == PROJECT_ID, "persisted project JSON identity mismatch")
    shutil.copy2(project_file, EVIDENCE_ROOT / f"{PROJECT_ID}.json")
    trace.append(
        {
            "step": "restart_reopen",
            "assets": len(project["assets"]),
            "active_asset_id": project["workspace"]["active_asset_id"],
            "project_json_sha256": sha256(project_file.read_bytes()),
        }
    )


def main() -> int:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    if SERVER_LOG.exists():
        SERVER_LOG.unlink()
    trace: list[dict[str, Any]] = []
    process: subprocess.Popen[bytes] | None = None
    log_stream: Any | None = None
    report: dict[str, Any] = {
        "schema": 1,
        "test": "LIVE-E2E-01",
        "candidate_sha": SOURCE_SHA,
        "runtime": "real_uvicorn_fastapi_http",
        "route_mocks": False,
        "data_root": str(RUNTIME_ROOT),
        "release_status": "RELEASE_BLOCKED",
        "status": "FAILED",
        "trace": trace,
    }
    try:
        require(FIXTURE.is_file(), f"frozen fixture missing: {FIXTURE}")
        process, log_stream = start_server()
        route = run_route(trace)
        stop_server(process, log_stream)
        process = None
        log_stream = None
        trace.append({"step": "runtime_stopped_for_restart"})

        process, log_stream = start_server()
        verify_after_restart(route, trace)
        report.update(
            {
                "status": "VERIFIED_L2_FOUNDATION_ROUTE",
                "project_id": PROJECT_ID,
                "source_asset_id": route["source"]["id"],
                "processed_asset_id": route["processed"]["id"],
                "exported_asset_id": route["exported"]["id"],
                "source_sha256": route["fixture_sha256"],
                "export_sha256": route["export_sha256"],
                "limitations": [
                    "This foundation route does not close the full M2B-PILOT processing slice.",
                    "PNG DTF, five-width visual review, runtime training lock and physical Windows paths remain separate gates.",
                ],
            }
        )
        print("LIVE-E2E-01: VERIFIED_L2_FOUNDATION_ROUTE")
        return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(f"LIVE-E2E-01: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        stop_server(process, log_stream)
        TRACE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
