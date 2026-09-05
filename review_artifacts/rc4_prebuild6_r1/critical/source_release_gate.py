from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    "__pycache__", ".pytest_cache", ".git", ".slu_backup", ".slu_m6_build",
    ".plateau_build", ".core_recovery_build", ".update_lock_build", ".update_lock_backup",
    ".zero_trust_build", "dist", ".venv", "venv", ".verified_l3_runtime",
}
COLLECTION_MANIFEST_REL = Path("release_gate/pytest_collection_manifest.txt")
COLLECTION_MANIFEST_SHA256 = "0a3ccc1518d014d948890e61b610b447ccd4ad3fb22fb59c3886bcdcb5de4cad"
EXECUTION_POLICY = {
    "python_isolated": True,
    "python_no_site": True,
    "inherited_python_paths_discarded": True,
    "pytest_import_mode": "importlib",
    "runtime_precedes_source": True,
    "pytest_addopts_sanitized": True,
    "plugin_autoload_disabled": True,
    "pytest_config_ignored": True,
    "pytest_rootdir_pinned": True,
    "explicit_test_root": "tests",
    "pinned_collection_required": True,
    "pre_and_post_gate_source_tree_bound": True,
    "trusted_interpreter_site_only": True,
}

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _source_file(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in rel.parts): return False
    if path.suffix in {".pyc", ".pyo"} or path.name in {".coverage", "verified-runtime-receipt.json"}: return False
    if rel.parts and rel.parts[0] == "data": return False
    if rel == Path("windows_installer/installer/payload.zip"): return False
    if rel.parts and rel.parts[0].startswith("evidence"): return False
    if path.suffix == ".exe" and rel != Path("vendor/tools/stet/stet.exe"): return False
    return path.is_file()

def iter_source_files(root: Path = ROOT) -> list[Path]:
    root = root.resolve(); return [path for path in root.rglob("*") if _source_file(root, path)]

def compute_source_tree(root: Path = ROOT) -> dict[str, object]:
    root = root.resolve(); files = iter_source_files(root); digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix().encode("utf-8"); digest.update(len(rel).to_bytes(4, "big")); digest.update(rel); digest.update(bytes.fromhex(_sha256(path)))
    return {"sha256": digest.hexdigest(), "file_count": len(files)}

def assert_runtime_outside_source(*, root: Path, runtime_dir: Path) -> None:
    root = root.resolve(); runtime_dir = runtime_dir.resolve()
    try: runtime_dir.relative_to(root)
    except ValueError: return
    raise RuntimeError("verified L3 runtime must be outside source root")

def _runtime_tree(runtime_dir: Path) -> dict[str, object]:
    try: from l3_dependency_intake import compute_runtime_tree
    except ImportError: from scripts.l3_dependency_intake import compute_runtime_tree
    return compute_runtime_tree(runtime_dir)

def build_pytest_environment(*, root: Path, runtime_dir: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    for key in tuple(env):
        upper = key.upper()
        if upper.startswith("PYTHON") or upper.startswith("PYTEST"): env.pop(key, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"; return env

def _trusted_interpreter_site_paths() -> tuple[str, ...]:
    prefix = Path(sys.prefix).resolve(); candidates = [sysconfig.get_paths().get("purelib"), sysconfig.get_paths().get("platlib")]; trusted=[]
    for value in candidates:
        if not value: continue
        resolved = Path(value).resolve()
        try: resolved.relative_to(prefix)
        except ValueError as exc: raise RuntimeError(f"interpreter library path escapes sys.prefix: prefix={prefix}, path={resolved}") from exc
        text = str(resolved)
        if text not in trusted: trusted.append(text)
    if not trusted: raise RuntimeError("no trusted interpreter site-packages path available for isolated pytest")
    return tuple(trusted)

def _isolated_pytest_bootstrap(*, root: Path, runtime_dir: Path) -> str:
    runtime = str(runtime_dir.resolve()); source = str(root.resolve()); interpreter_paths = list(_trusted_interpreter_site_paths())
    return "import sys; " + f"trusted=[{runtime!r},{source!r},*{interpreter_paths!r}]; " + "clean=[]; [clean.append(p) for p in trusted if p and p not in clean]; sys.path[:0]=clean; import pytest; raise SystemExit(pytest.main(sys.argv[1:]))"

def build_pytest_command(junit: Path, *, root: Path, runtime_dir: Path) -> list[str]:
    return [sys.executable,"-I","-S","-c",_isolated_pytest_bootstrap(root=root,runtime_dir=runtime_dir),"-c",os.devnull,f"--rootdir={root.resolve()}","--import-mode=importlib","-q",f"--junitxml={junit}","tests"]

def build_collect_command(*, root: Path, runtime_dir: Path) -> list[str]:
    return [sys.executable,"-I","-S","-c",_isolated_pytest_bootstrap(root=root,runtime_dir=runtime_dir),"-c",os.devnull,f"--rootdir={root.resolve()}","--import-mode=importlib","--collect-only","-q","tests"]

def _manifest_path(root: Path) -> Path: return root.resolve() / COLLECTION_MANIFEST_REL

def load_pinned_collection(root: Path = ROOT) -> tuple[str, ...]:
    path=_manifest_path(root)
    if not path.is_file(): raise RuntimeError(f"pinned pytest collection manifest missing: {path}")
    digest=_sha256(path)
    if digest != COLLECTION_MANIFEST_SHA256: raise RuntimeError(f"pinned pytest collection manifest SHA-256 mismatch: expected {COLLECTION_MANIFEST_SHA256}, got {digest}")
    nodeids=tuple(line.strip() for line in path.read_text("utf-8").splitlines() if line.strip())
    if not nodeids or len(set(nodeids)) != len(nodeids): raise RuntimeError("pinned pytest collection manifest is empty or contains duplicates")
    return nodeids

def collect_test_nodeids(*, root: Path, runtime_dir: Path) -> tuple[str, ...]:
    env=build_pytest_environment(root=root,runtime_dir=runtime_dir); completed=subprocess.run(build_collect_command(root=root,runtime_dir=runtime_dir),cwd=root,env=env,text=True,capture_output=True)
    if completed.returncode != 0: raise RuntimeError(f"pytest collection failed rc={completed.returncode}\n{completed.stdout}\n{completed.stderr}")
    nodeids=tuple(line.strip() for line in completed.stdout.splitlines() if "::" in line)
    if not nodeids: raise RuntimeError("pytest collection returned no node ids")
    return nodeids

def verify_complete_collection(*, root: Path, runtime_dir: Path) -> tuple[str, ...]:
    expected=load_pinned_collection(root); actual=collect_test_nodeids(root=root,runtime_dir=runtime_dir)
    if actual != expected:
        missing=[node for node in expected if node not in set(actual)]; extra=[node for node in actual if node not in set(expected)]; raise RuntimeError("pytest collection differs from pinned manifest: "+json.dumps({"expected":len(expected),"actual":len(actual),"missing":missing[:20],"extra":extra[:20]},sort_keys=True))
    return expected

def _read_junit(path: Path) -> dict[str, int]:
    root=ET.parse(path).getroot(); suites=[root] if root.tag=="testsuite" else list(root.findall("testsuite")); totals={"tests":0,"failures":0,"errors":0,"skipped":0}
    for suite in suites:
        for key in totals: totals[key]+=int(float(suite.attrib.get(key,"0") or 0))
    totals["passed"]=totals["tests"]-totals["failures"]-totals["errors"]-totals["skipped"]; return totals

def write_pass_receipt_for_test(*, root: Path, runtime_dir: Path, receipt_path: Path, tests_total: int, tests_passed: int) -> dict[str, object]:
    source=compute_source_tree(root); runtime=_runtime_tree(runtime_dir); receipt={"schema":"imagelab.source-release-gate.v5","status":"PASS","execution_policy":dict(EXECUTION_POLICY),"source_tree":source,"runtime_tree":runtime,"tests":{"total":tests_total,"passed":tests_passed,"failures":0,"errors":0,"skipped":0}}; receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),"utf-8"); return receipt

def validate_source_gate_receipt(*, receipt_path: Path, root: Path = ROOT, runtime_dir: Path) -> dict[str, object]:
    assert_runtime_outside_source(root=root,runtime_dir=runtime_dir)
    try: receipt=json.loads(receipt_path.read_text("utf-8"))
    except Exception as exc: raise RuntimeError("source gate receipt unreadable") from exc
    if receipt.get("schema")!="imagelab.source-release-gate.v5" or receipt.get("status")!="PASS": raise RuntimeError("source gate receipt schema/status invalid")
    if receipt.get("execution_policy")!=EXECUTION_POLICY: raise RuntimeError("source gate receipt execution policy invalid")
    source=compute_source_tree(root); runtime=_runtime_tree(runtime_dir)
    if source!=receipt.get("source_tree"): raise RuntimeError(f"source tree hash mismatch: expected {receipt.get('source_tree')}, got {source}")
    if runtime!=receipt.get("runtime_tree"): raise RuntimeError(f"runtime tree hash mismatch: expected {receipt.get('runtime_tree')}, got {runtime}")
    tests=receipt.get("tests") or {}
    if any(int(tests.get(key,0))!=0 for key in ("failures","errors","skipped")): raise RuntimeError(f"source gate receipt contains non-PASS tests: {tests}")
    if int(tests.get("total",0))<=0 or int(tests.get("passed",0))!=int(tests.get("total",0)): raise RuntimeError(f"source gate receipt test totals invalid: {tests}")
    return {"status":"PASS","source_tree":source,"runtime_tree":runtime,"tests":tests}

def _assert_expected_source_tree(*, root: Path, expected: dict[str, object], phase: str) -> dict[str, object]:
    current=compute_source_tree(root)
    if current!=expected: raise RuntimeError(f"source tree changed during source gate ({phase}): expected {expected}, got {current}")
    return current

def run_full_source_gate(*, root: Path, runtime_dir: Path, receipt_path: Path, expected_source_tree: dict[str, object] | None = None) -> dict[str, object]:
    assert_runtime_outside_source(root=root,runtime_dir=runtime_dir); source_before=compute_source_tree(root); expected_source_tree=dict(expected_source_tree or source_before)
    if source_before!=expected_source_tree: raise RuntimeError(f"source tree changed during source gate (entry): expected {expected_source_tree}, got {source_before}")
    try: from l3_dependency_intake import validate_verified_runtime
    except ImportError: from scripts.l3_dependency_intake import validate_verified_runtime
    validate_verified_runtime(runtime_dir=runtime_dir); _assert_expected_source_tree(root=root,expected=expected_source_tree,phase="after-runtime-validation")
    try: from release_capability_preflight import assert_source_test_runtime_capability
    except ImportError: from scripts.release_capability_preflight import assert_source_test_runtime_capability
    assert_source_test_runtime_capability(extra_runtime=runtime_dir); _assert_expected_source_tree(root=root,expected=expected_source_tree,phase="after-capability-preflight")
    expected_nodeids=verify_complete_collection(root=root,runtime_dir=runtime_dir); _assert_expected_source_tree(root=root,expected=expected_source_tree,phase="after-collection"); env=build_pytest_environment(root=root,runtime_dir=runtime_dir)
    with tempfile.TemporaryDirectory(prefix="imagelab-source-gate-") as tmp:
        junit=Path(tmp)/"pytest.xml"; command=build_pytest_command(junit,root=root,runtime_dir=runtime_dir); completed=subprocess.run(command,cwd=root,env=env,text=True,capture_output=True); source_after_pytest=_assert_expected_source_tree(root=root,expected=expected_source_tree,phase="after-pytest")
        if not junit.is_file(): raise RuntimeError(f"pytest did not produce JUnit receipt; rc={completed.returncode}\n{completed.stdout}\n{completed.stderr}")
        tests=_read_junit(junit)
    expected_total=len(expected_nodeids)
    if completed.returncode!=0 or tests["failures"] or tests["errors"] or tests["skipped"] or tests["tests"]!=expected_total or tests["passed"]!=expected_total: raise RuntimeError("full source gate failed: "+json.dumps({"returncode":completed.returncode,"expected_total":expected_total,**tests},sort_keys=True))
    runtime_tree=_runtime_tree(runtime_dir); _assert_expected_source_tree(root=root,expected=expected_source_tree,phase="receipt-write"); receipt={"schema":"imagelab.source-release-gate.v5","status":"PASS","execution_policy":dict(EXECUTION_POLICY),"collection":{"manifest_sha256":COLLECTION_MANIFEST_SHA256,"node_count":expected_total},"source_tree":source_after_pytest,"runtime_tree":runtime_tree,"tests":{"total":expected_total,"passed":expected_total,"failures":0,"errors":0,"skipped":0},"pytest":{"command":command}}; receipt_path.parent.mkdir(parents=True,exist_ok=True); receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),"utf-8"); return receipt

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--l3-runtime",type=Path,required=True); parser.add_argument("--receipt",type=Path,required=True); parser.add_argument("--verify-only",action="store_true"); args=parser.parse_args()
    try: result=validate_source_gate_receipt(receipt_path=args.receipt,root=ROOT,runtime_dir=args.l3_runtime) if args.verify_only else run_full_source_gate(root=ROOT,runtime_dir=args.l3_runtime,receipt_path=args.receipt)
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","error":str(exc)},ensure_ascii=False,indent=2)); return 2
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0

if __name__ == "__main__":
    raise SystemExit(main())
