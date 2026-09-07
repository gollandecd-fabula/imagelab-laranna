from __future__ import annotations

import hashlib
import importlib.util
import json
import py_compile
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXPECTED_R13_SHA256 = "60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991"
EXPECTED_R14_SHA256 = "a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c"
PARTS = [
    "R13_extract_fidelity.part01.py.txt",
    "R13_extract_fidelity.part02.py.txt",
    "R13_extract_fidelity.part03.py.txt",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_patcher():
    path = ROOT / "R14_APPLY_TO_EXACT_R13.py"
    spec = importlib.util.spec_from_file_location("r14_exact_patcher", path)
    require(spec is not None and spec.loader is not None, "PATCHER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    checks: list[dict[str, object]] = []

    def checked(name: str, fn):
        try:
            detail = fn()
            checks.append({"name": name, "status": "PASS", "detail": detail})
        except Exception as exc:
            checks.append({"name": name, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})
            raise

    try:
        for name in PARTS + [
            "R14_APPLY_TO_EXACT_R13.py",
            "R14_CLIENT_ROUTING_REGRESSION.js",
            "R14_APP_EXTRACT_ROUTING.patch",
            "R14_QA_REPAIR_SEMANTIC_ROUTING.patch",
        ]:
            require((ROOT / name).is_file(), f"MISSING_REQUIRED_ARTIFACT:{name}")

        r13_bytes = b"".join((ROOT / name).read_bytes() for name in PARTS)
        checked("exact_r13_sha256", lambda: (
            require(sha256(r13_bytes) == EXPECTED_R13_SHA256, "R13_SHA_MISMATCH") or EXPECTED_R13_SHA256
        ))

        patcher = load_patcher()
        candidate_text = patcher.patch_exact_r13(r13_bytes.decode("utf-8"), verify_hash=True)
        candidate_bytes = candidate_text.encode("utf-8")
        checked("deterministic_r14_sha256", lambda: (
            require(sha256(candidate_bytes) == EXPECTED_R14_SHA256, "R14_SHA_MISMATCH") or EXPECTED_R14_SHA256
        ))

        def compile_candidate():
            with tempfile.TemporaryDirectory(prefix="imagelab-r14-repro-") as td:
                out = Path(td) / "extract_fidelity.py"
                out.write_bytes(candidate_bytes)
                py_compile.compile(str(out), doraise=True)
            return "py_compile PASS"

        checked("candidate_py_compile", compile_candidate)

        def manual_static_guards():
            start = candidate_text.index("def _manual_roi_working_fragment(")
            end = candidate_text.index("def _local_dewarp(", start)
            manual = candidate_text[start:end]
            forbidden = ["segment_print(", "_ai_extract_print(", "MedianFilter(", "_crop_alpha(", "GaussianBlur("]
            leaked = [token for token in forbidden if token in manual]
            require(not leaked, f"MANUAL_DESTRUCTIVE_TOKEN:{leaked}")
            require('"semantics": "working_fragment"' in manual, "MISSING_WORKING_FRAGMENT_SEMANTICS")
            require('"strict_roi": True' in manual, "MISSING_STRICT_ROI")
            require('"segmentation_applied": False' in manual, "MISSING_NO_SEGMENTATION_DIAGNOSTIC")
            require('"background_removed": False' in manual, "MISSING_BACKGROUND_PRESERVATION_DIAGNOSTIC")
            return {"forbidden_tokens": leaked, "strict_roi": True}

        checked("manual_non_destructive_static_guards", manual_static_guards)

        def branch_guards():
            start = candidate_text.index("def process_extract(")
            process = candidate_text[start:]
            region = process.index('if mode == "region":')
            auto = process.index("else:", region)
            region_block = process[region:auto]
            require("_manual_roi_working_fragment(image, recorded)" in region_block, "REGION_NOT_HARD_ROUTED")
            require("_fidelity_extract(" not in region_block, "REGION_FIDELITY_FALLTHROUGH")
            require("_ai_extract_print(" not in region_block, "REGION_LEGACY_FALLTHROUGH")
            return "manual region hard branch PASS"

        checked("manual_no_auto_fallback_static_guard", branch_guards)

        def patch_contracts():
            client = (ROOT / "R14_APP_EXTRACT_ROUTING.patch").read_text(encoding="utf-8")
            qa = (ROOT / "R14_QA_REPAIR_SEMANTIC_ROUTING.patch").read_text(encoding="utf-8")
            require("if(mode==='auto') Object.assign" in client, "CLIENT_AUTO_SPLIT_MISSING")
            require("Рабочий фрагмент создан" in client, "CLIENT_REGION_MESSAGE_MISSING")
            require("working_fragment" in qa, "QA_WORKING_FRAGMENT_ROUTING_MISSING")
            return "client/QA semantic patch contracts present"

        checked("review_patch_contracts", patch_contracts)

        def no_hidden_runtime_paths():
            executable = [
                ROOT / "R14_REPRO_RUNNER.py",
                ROOT / "R14_APPLY_TO_EXACT_R13.py",
                ROOT / "R14_CLIENT_ROUTING_REGRESSION.js",
            ]
            forbidden_root = "/" + "mnt" + "/" + "data"
            forbidden_project = "imagelab" + "_r14"
            bad = []
            for path in executable:
                text = path.read_text(encoding="utf-8")
                if forbidden_root in text or forbidden_project in text:
                    bad.append(path.name)
            require(not bad, f"HIDDEN_RUNTIME_PATHS:{bad}")
            return "repository-relative only"

        checked("no_hidden_mnt_data_dependencies", no_hidden_runtime_paths)

        def node_regression():
            node = shutil.which("node")
            require(node is not None, "NODE_NOT_AVAILABLE")
            completed = subprocess.run(
                [node, str(ROOT / "R14_CLIENT_ROUTING_REGRESSION.js")],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
                check=False,
            )
            require(completed.returncode == 0, f"NODE_REGRESSION_FAILED:{completed.stdout.strip()}")
            require("3/3 PASS" in completed.stdout, "NODE_PASS_MARKER_MISSING")
            return completed.stdout.strip()

        checked("client_routing_node_regression", node_regression)

        result = {
            "schema": "imagelab.r14.repro.v1",
            "status": "PASS_L1_REPRODUCIBILITY",
            "evidence_ceiling": "L1_ONLY_DO_NOT_INFER_L2_L3_L4_L5",
            "r13_sha256": EXPECTED_R13_SHA256,
            "r14_candidate_sha256": EXPECTED_R14_SHA256,
            "checks": checks,
            "note": "This runner proves clean-checkout reconstruction/static/unit reproducibility only. R14 source-runtime L2 evidence is separate and requires the ImageLab runtime scaffold.",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {
            "schema": "imagelab.r14.repro.v1",
            "status": "FAIL_CLOSED",
            "evidence_ceiling": "L1_ONLY",
            "error": f"{type(exc).__name__}: {exc}",
            "checks": checks,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
