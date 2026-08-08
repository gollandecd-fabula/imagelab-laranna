from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run_isolated(command: list[str], env: dict[str, str], timeout: int) -> tuple[int, str, str, bool]:
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
        return int(process.returncode or 0), stdout or "", stderr or "", False
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
        suffix = "; ".join(cleanup_notes)
        if suffix:
            stderr = (stderr or "") + f"\ncleanup: {suffix}"
        return 124, stdout or "", (stderr or "") + f"\nTIMEOUT after {timeout}s", True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one pytest file in an isolated release-gate process.")
    parser.add_argument("--test-file", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    test_file = Path(args.test_file)
    if not test_file.is_absolute():
        test_file = ROOT / test_file
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_pytest_exit_safe.py"),
        "-q",
        str(test_file.relative_to(ROOT)),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    exit_code, stdout, stderr, timed_out = run_isolated(command, env, args.timeout)

    result: dict[str, Any] = {
        "schema": 1,
        "status": "PASS" if exit_code == 0 else "FAIL",
        "case_id": args.case_id,
        "test_file": test_file.relative_to(ROOT).as_posix(),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started, 3),
        "command": command,
        "stdout": stdout[-30000:],
        "stderr": stderr[-30000:],
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
