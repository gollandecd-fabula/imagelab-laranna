from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    import signal
    started = time.time()
    kwargs: dict[str, Any] = {
        "cwd": ROOT,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        exit_code = int(process.returncode or 0)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        stdout, stderr = process.communicate()
        exit_code = 124
        stderr = (stderr or "") + f"\nTIMEOUT after {timeout}s"
    return {
        "command": command,
        "exit_code": exit_code,
        "duration_seconds": round(time.time() - started, 3),
        "stdout": (stdout or "")[-20000:],
        "stderr": (stderr or "")[-20000:],
    }


def identity() -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import settings
    expected = {"version": str(settings.app_version), "build_id": str(settings.build_id)}
    for path in (ROOT / "windows_installer" / "launcher" / "main.go", ROOT / "windows_installer" / "installer" / "main.go"):
        text = path.read_text("utf-8")
        version = re.search(r'appVersion\s*=\s*"([^"]+)"', text)
        build = re.search(r'buildID\s*=\s*"([^"]+)"', text)
        if not version or not build or version.group(1) != expected["version"] or build.group(1) != expected["build_id"]:
            raise RuntimeError(f"identity mismatch in {path}")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}
    try:
        ident = identity()
        checks["compileall"] = run([sys.executable, "-m", "compileall", "-q", "app", "release_gate", "scripts"])
        critical_files = [
            ROOT / "tests" / "test_zero_trust_release_gate.py",
            ROOT / "tests" / "test_installer_update_lock.py",
            ROOT / "tests" / "test_second_core_failure_regression.py",
        ]
        pytest_results = {}
        for test_file in critical_files:
            pytest_results[test_file.name] = run(
                [sys.executable, "scripts/run_pytest_exit_safe.py", "-q", str(test_file.relative_to(ROOT))],
                timeout=180,
            )
        pytest_failures = [name for name, item in pytest_results.items() if item.get("exit_code") != 0]
        checks["critical_pytest"] = {
            "command": ["isolated critical pytest files"],
            "exit_code": 0 if not pytest_failures else 1,
            "duration_seconds": round(sum(float(item.get("duration_seconds", 0)) for item in pytest_results.values()), 3),
            "stdout": f"{len(pytest_results) - len(pytest_failures)}/{len(pytest_results)} critical test files passed",
            "stderr": "failed: " + ", ".join(pytest_failures) if pytest_failures else "",
            "files": pytest_results,
        }
        if shutil_which("node"):
            checks["javascript"] = run(["node", "--check", "app/static/app.js"])
        else:
            checks["javascript"] = {"command": ["node", "--check", "app/static/app.js"], "exit_code": 1, "stderr": "node not found", "stdout": "", "duration_seconds": 0}
        with tempfile.TemporaryDirectory(prefix="imagelab-source-gate-") as temp:
            env = dict(os.environ)
            env["IMAGELAB_DATA_DIR"] = str(Path(temp) / "data")
            env["PYTHONPATH"] = str(ROOT)
            selftest_output = Path(temp) / "backend-selftest.json"
            checks["backend_selftest"] = run([sys.executable, "-m", "app.release_selftest", "--output", str(selftest_output)], env=env)
            backend = json.loads(selftest_output.read_text("utf-8")) if selftest_output.exists() else {"status": "MISSING"}
        failed = [name for name, check in checks.items() if int(check.get("exit_code", 1)) != 0]
        if backend.get("status") != "PASS":
            failed.append("backend_selftest_verdict")
        result = {
            "schema": 1,
            "status": "PASS" if not failed else "FAIL",
            "identity": ident,
            "failed_checks": failed,
            "checks": checks,
            "backend_selftest": backend,
        }
    except Exception as exc:
        result = {"schema": 1, "status": "FAIL", "error_type": type(exc).__name__, "error": str(exc), "checks": checks}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
