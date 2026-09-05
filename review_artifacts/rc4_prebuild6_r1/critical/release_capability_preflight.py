from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Any

REQUIRED_SOURCE_TEST_MODULES = {
    "PIL": ["raster import/export"],
    "numpy": ["image processing"],
    "cv2": ["enhance/background/vector"],
    "fitz": ["PDF import/export"],
    "pillow_heif": ["HEIF/HEIC import"],
    "psd_tools": ["PSD/PSB import/export tests"],
}

def probe_import(module: str, *, extra_runtime: Path | None = None, require_origin_under: Path | None = None) -> dict[str, object]:
    env = dict(os.environ)
    if extra_runtime is not None:
        runtime = str(Path(extra_runtime).resolve())
        env["PYTHONPATH"] = runtime + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    code = ("import importlib, json; " f"m=importlib.import_module({module!r}); " "print(json.dumps({'module': m.__name__, 'file': str(getattr(m, '__file__', ''))}))")
    completed = subprocess.run([sys.executable, "-P", "-c", code], text=True, capture_output=True, env=env)
    result = {"status": "ready" if completed.returncode == 0 else "unavailable", "returncode": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(), "origin_verified": False, "module_file": ""}
    if completed.returncode == 0:
        if require_origin_under is None: result["origin_verified"] = True
        try:
            payload = json.loads(completed.stdout.strip()); module_file_raw = str(payload.get("file") or ""); result["module_file"] = module_file_raw
            if require_origin_under is not None:
                if not module_file_raw: raise ValueError("module has no file origin")
                module_file = Path(module_file_raw).resolve(); required_root = Path(require_origin_under).resolve(); module_file.relative_to(required_root); result["origin_verified"] = True
        except Exception as exc:
            result["status"] = "unavailable"; result["origin_verified"] = False; result["stderr"] = (str(result.get("stderr") or "") + f"\nmodule origin outside verified runtime: {exc}").strip()
    return result

def check_source_test_runtime_capability(*, find_spec: Callable[[str], Any] | None = None, extra_runtime: Path | None = None) -> dict[str, object]:
    modules = {}; missing = []; runtime_validation = None
    if extra_runtime is not None:
        try: from l3_dependency_intake import validate_verified_runtime
        except ImportError: from scripts.l3_dependency_intake import validate_verified_runtime
        try: runtime_validation = validate_verified_runtime(runtime_dir=Path(extra_runtime))
        except Exception as exc: return {"schema":"imagelab.release-source-runtime-preflight.v2","status":"BLOCKED","missing":["verified_l3_runtime"],"modules":{},"verified_runtime":{"status":"BLOCKED","error":str(exc)}}
    verified_imports = {str(item.get("import_name")) for item in (runtime_validation or {}).get("wheels", []) if isinstance(item, dict) and item.get("import_name")}
    for module, required_for in REQUIRED_SOURCE_TEST_MODULES.items():
        if find_spec is not None:
            try: probe = {"status": "ready" if find_spec(module) is not None else "unavailable"}
            except Exception as exc: probe = {"status":"unavailable","stderr":str(exc)}
        else:
            probe = probe_import(module, extra_runtime=extra_runtime, require_origin_under=(Path(extra_runtime) if extra_runtime is not None and module in verified_imports else None))
        available = probe.get("status") == "ready"; modules[module] = {"status":"ready" if available else "missing","required_for":list(required_for),"probe":probe}
        if not available: missing.append(module)
    return {"schema":"imagelab.release-source-runtime-preflight.v2","status":"PASS" if not missing else "BLOCKED","missing":missing,"modules":modules,"verified_runtime":runtime_validation}

def assert_source_test_runtime_capability(*, extra_runtime: Path | None = None) -> dict[str, object]:
    result = check_source_test_runtime_capability(extra_runtime=extra_runtime)
    if result["status"] != "PASS": raise RuntimeError("source-test runtime capability is incomplete before build: " + ", ".join(result["missing"]))
    return result

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--l3-runtime", type=Path); args = parser.parse_args(); result = check_source_test_runtime_capability(extra_runtime=args.l3_runtime); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 2

if __name__ == "__main__": raise SystemExit(main())
