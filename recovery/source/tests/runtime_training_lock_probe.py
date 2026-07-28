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
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path(os.environ.get("PILOT_EVIDENCE_DIR", SOURCE_ROOT / "artifacts" / "pilot-runtime-training")).resolve()
RUNTIME_ROOT = EVIDENCE_ROOT / "runtime-data"
REPORT_PATH = EVIDENCE_ROOT / "runtime-training-lock.json"
SERVER_LOG = EVIDENCE_ROOT / "runtime-training-server.log"
HOST = "127.0.0.1"
PORT = 8765
ORIGIN = f"http://{HOST}:{PORT}"
SOURCE_SHA = os.environ.get("PILOT_SOURCE_SHA", "unknown").strip() or "unknown"


class ProbeError(AssertionError):
    pass


def request(method: str, path: str, *, payload: dict[str, Any] | None = None, expected: tuple[int, ...] | None = None) -> tuple[int, dict[str, str], bytes]:
    body = None
    headers = {"Accept": "application/json", "Origin": ORIGIN}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection(HOST, PORT, timeout=20)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
    finally:
        connection.close()
    if expected is not None and response.status not in expected:
        raise ProbeError(f"{method} {path}: HTTP {response.status}; {data.decode('utf-8', 'replace')[:1200]}")
    return response.status, response_headers, data


def start_server() -> tuple[subprocess.Popen[bytes], Any]:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    log = SERVER_LOG.open("ab", buffering=0)
    env = dict(os.environ)
    env["IMAGELAB_DATA_DIR"] = str(RUNTIME_ROOT)
    env["PYTHONUTF8"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.entry:app", "--host", HOST, "--port", str(PORT), "--log-level", "info"],
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
            raise ProbeError(f"runtime exited with code {process.returncode}")
        try:
            status, _, _ = request("GET", "/api/health")
            if status == 200:
                return process, log
        except Exception as exc:
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


def snapshot(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        data = path.read_bytes()
        result[str(path.relative_to(directory)).replace("\\", "/")] = {
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return result


def body_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return data.decode("utf-8", "replace")[:2000]


def main() -> int:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    if SERVER_LOG.exists():
        SERVER_LOG.unlink()
    process: subprocess.Popen[bytes] | None = None
    log: Any | None = None
    report: dict[str, Any] = {
        "schema": 1,
        "probe": "RUNTIME_TRAINING_LOCK",
        "candidate_sha": SOURCE_SHA,
        "runtime": "real_uvicorn_fastapi_http",
        "required_http_statuses": [403, 404],
        "release_status": "RELEASE_BLOCKED",
        "status": "FAILED",
    }
    try:
        process, log = start_server()
        promoted_dir = RUNTIME_ROOT / "ai_models"
        before = snapshot(promoted_dir)
        train_status, _, train_body = request("POST", "/api/ai/train", payload={"module": "upload"})
        rollback_status, _, rollback_body = request("POST", "/api/ai/rollback", payload={"module": "upload"})
        time.sleep(0.25)
        after = snapshot(promoted_dir)

        _, _, html = request("GET", "/", expected=(200,))
        _, _, core_js = request("GET", "/static/app.js", expected=(200,))
        _, _, m2a_js = request("GET", "/static/m2a-ui.js", expected=(200,))
        ui_text = b"\n".join((html, core_js, m2a_js)).decode("utf-8", "replace")
        ui_exposes_training = "/api/ai/train" in ui_text or "/api/ai/rollback" in ui_text

        report.update(
            {
                "train": {"http_status": train_status, "body": body_json(train_body)},
                "rollback": {"http_status": rollback_status, "body": body_json(rollback_body)},
                "promoted_models_before": before,
                "promoted_models_after": after,
                "promoted_models_unchanged": before == after,
                "ui_exposes_training_routes": ui_exposes_training,
            }
        )
        api_locked = train_status in {403, 404} and rollback_status in {403, 404}
        no_writes = before == after
        ui_locked = not ui_exposes_training
        if api_locked and no_writes and ui_locked:
            report["status"] = "VERIFIED_L2_RUNTIME_TRAINING_LOCK"
            print("RUNTIME_TRAINING_LOCK: VERIFIED_L2")
            return 0
        report["status"] = "DEFECT_REPRODUCED"
        report["defects"] = {
            "api_not_fail_closed": not api_locked,
            "promoted_model_write_detected": not no_writes,
            "ui_route_exposure_detected": not ui_locked,
        }
        print(
            "RUNTIME_TRAINING_LOCK: DEFECT_REPRODUCED "
            f"train={train_status} rollback={rollback_status} writes_changed={before != after} ui_exposed={ui_exposes_training}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        report["status"] = "PROBE_FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(f"RUNTIME_TRAINING_LOCK: PROBE_FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        stop_server(process, log)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), "utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
