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
        cleanup_notes: list[str] = []
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
            except subprocess.TimeoutExpired:
                cleanup_notes.append("taskkill timeout")
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            cleanup_notes.append("bounded reap timeout")
            try:
                process.kill()
            except OSError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "process pipes remained open after bounded kill"
        exit_code = 124
        stderr = (stderr or "") + f"\nTIMEOUT after {timeout}s"
        if cleanup_notes:
            stderr += "\ncleanup: " + "; ".join(cleanup_notes)
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
    progress = output.with_suffix(".progress.log")
    progress.write_text("START\n", "utf-8")

    def mark(message: str) -> None:
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
            stream.flush()

    checks: dict[str, Any] = {}
    try:
        ident = identity()
        mark("IDENTITY PASS")
        checks["compileall"] = run([sys.executable, "-m", "compileall", "-q", "app", "release_gate", "scripts"])
        mark(f"COMPILEALL {checks['compileall']['exit_code']}")
        critical_files = [
            ROOT / "tests" / "test_a0.py",
            ROOT / "tests" / "test_a1.py",
            ROOT / "tests" / "test_a2_a4.py",
            ROOT / "tests" / "test_ai_audit_concurrency.py",
            ROOT / "tests" / "test_ai_contours.py",
            ROOT / "tests" / "test_bootstrap.py",
            ROOT / "tests" / "test_core_failure_regression.py",
            ROOT / "tests" / "test_installer_update_lock.py",
            ROOT / "tests" / "test_isolated_processing.py",
            ROOT / "tests" / "test_l5_iz017_regression.py",
            ROOT / "tests" / "test_m1_ui.py",
            ROOT / "tests" / "test_print_extraction.py",
            ROOT / "tests" / "test_product_workflows.py",
            ROOT / "tests" / "test_project_lookup_resilience.py",
            ROOT / "tests" / "test_project_store_concurrency.py",
            ROOT / "tests" / "test_redteam_adversarial.py",
            ROOT / "tests" / "test_redteam_contracts.py",
            ROOT / "tests" / "test_second_core_failure_regression.py",
            ROOT / "tests" / "test_segmentation_governance.py",
            ROOT / "tests" / "test_slu_m1_units.py",
            ROOT / "tests" / "test_slu_m2_m5.py",
            ROOT / "tests" / "test_slu_m3_segmentation.py",
            ROOT / "tests" / "test_slu_m5_e2e.py",
            ROOT / "tests" / "test_storage_and_package_integrity.py",
            ROOT / "tests" / "test_windows_packaging_config.py",
            ROOT / "tests" / "test_zero_trust_release_gate.py",
        ]
        pytest_results = {}
        for test_file in critical_files:
            with tempfile.TemporaryDirectory(prefix=f"imagelab-critical-{test_file.stem}-") as test_temp:
                test_env = dict(os.environ)
                test_env["IMAGELAB_DATA_DIR"] = str(Path(test_temp) / "data")
                test_env["PYTHONPATH"] = str(ROOT)
                mark(f"PYTEST START {test_file.name}")
                pytest_results[test_file.name] = run(
                    [sys.executable, "scripts/run_pytest_exit_safe.py", "-q", str(test_file.relative_to(ROOT))],
                    env=test_env,
                    timeout=180,
                )
                mark(f"PYTEST END {test_file.name} {pytest_results[test_file.name]['exit_code']}")
        pytest_failures = [name for name, item in pytest_results.items() if item.get("exit_code") != 0]
        checks["critical_pytest"] = {
            "command": ["isolated critical pytest files"],
            "exit_code": 0 if not pytest_failures else 1,
            "duration_seconds": round(sum(float(item.get("duration_seconds", 0)) for item in pytest_results.values()), 3),
            "stdout": f"{len(pytest_results) - len(pytest_failures)}/{len(pytest_results)} critical test files passed",
            "stderr": "failed: " + ", ".join(pytest_failures) if pytest_failures else "",
            "files": pytest_results,
        }
        mark("PYTEST MATRIX COMPLETE")
        if shutil_which("node"):
            checks["javascript"] = run(["node", "--check", "app/static/app.js"])
        else:
            checks["javascript"] = {"command": ["node", "--check", "app/static/app.js"], "exit_code": 1, "stderr": "node not found", "stdout": "", "duration_seconds": 0}
        mark(f"JAVASCRIPT {checks['javascript']['exit_code']}")
        with tempfile.TemporaryDirectory(prefix="imagelab-source-gate-") as temp:
            env = dict(os.environ)
            env["IMAGELAB_DATA_DIR"] = str(Path(temp) / "data")
            env["PYTHONPATH"] = str(ROOT)
            selftest_output = Path(temp) / "backend-selftest.json"
            checks["backend_selftest"] = run([sys.executable, "-m", "app.release_selftest", "--output", str(selftest_output)], env=env)
            backend = json.loads(selftest_output.read_text("utf-8")) if selftest_output.exists() else {"status": "MISSING"}
        mark(f"BACKEND {backend.get('status')}")
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
    mark(f"FINAL {result.get('status')}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
