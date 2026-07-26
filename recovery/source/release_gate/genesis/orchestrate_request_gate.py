from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

RULE = "GENESIS-FIRST-RELEASE-V1"
AUTHORIZATION_WORKFLOWS = [
    "ImageLab Genesis First Release Gate",
    "ImageLab Genesis Request Gate",
    "ImageLab Zero-Trust Release Gate",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} root is not an object")
    return value


def _cleanup_authorized(output: Path) -> None:
    candidates = list(output.glob("*RELEASE_AUTHORIZED*.exe"))
    candidates.extend(
        [
            output / "ImageLab-RELEASE-AUTHORIZATION.json",
            output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json",
            output / "installer-sha256.txt",
            output / ".authorization-record-orchestrated.tmp",
        ]
    )
    for path in candidates:
        if path.exists():
            path.unlink()


def _validate_request_and_history(
    request: dict[str, Any],
    history: dict[str, Any],
    *,
    repository: str,
    genesis_run_id: int,
    request_id: str,
    qualification_run_id: int,
    qualification_head_sha: str,
    g7_bundle_sha: str,
    physical_l5_sha: str,
) -> list[str]:
    failed: list[str] = []
    expected_request = {
        "schema": 2,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "request_id": request_id,
        "qualification_run_id": qualification_run_id,
        "qualification_head_sha": qualification_head_sha,
        "g7_evidence_bundle_sha256": g7_bundle_sha,
        "physical_l5_evidence_sha256": physical_l5_sha,
        "failed_conditions": [],
    }
    for field, wanted in expected_request.items():
        if request.get(field) != wanted:
            failed.append(f"genesis_request_invalid:{field}")
    if request.get("request_source") not in {"reviewed_recovery_push", "workflow_dispatch"}:
        failed.append("genesis_request_invalid:request_source")
    if not isinstance(request.get("enable_attestation"), bool):
        failed.append("genesis_request_invalid:enable_attestation")
    g7_tag = str(request.get("g7_evidence_release_tag") or "")
    if not g7_tag.strip() or len(g7_tag) > 200 or any(character in g7_tag for character in "\r\n\0"):
        failed.append("genesis_request_invalid:g7_evidence_release_tag")
    physical_url = str(request.get("physical_l5_evidence_url") or "")
    if not physical_url.startswith("https://") or len(physical_url) > 2048 or any(
        character in physical_url for character in "\r\n\0"
    ):
        failed.append("genesis_request_invalid:physical_l5_evidence_url")
    if not _is_sha256(request.get("request_sha256")):
        failed.append("genesis_request_invalid:request_sha256")

    expected_history = {
        "schema": 3,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "query_source": "github_api_releases_all_authorization_runs_artifacts_paginated",
        "query_complete": True,
        "current_run_id": genesis_run_id,
        "authorization_workflow_names": AUTHORIZATION_WORKFLOWS,
        "authorized_installer_asset_count": 0,
        "authorization_record_asset_count": 0,
        "prior_successful_authorization_run_count": 0,
        "prior_authorized_artifact_count": 0,
        "prior_successful_authorization_runs": [],
        "prior_authorized_artifacts": [],
        "matching_assets": [],
    }
    for field, wanted in expected_history.items():
        if history.get(field) != wanted:
            failed.append(f"genesis_history_invalid:{field}")
    for field in ("release_count_scanned", "workflow_run_count_scanned", "artifact_count_scanned"):
        count = history.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            failed.append(f"genesis_history_invalid:{field}")
    return failed


def _write_blocked(output: Path, aggregate: Path, failed: list[str]) -> None:
    _cleanup_authorized(output)
    output.mkdir(parents=True, exist_ok=True)
    verdict = {
        "schema": 5,
        "status": "RELEASE_BLOCKED",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "failed_conditions": sorted(set(failed)),
    }
    verdict_path = output / "final-verdict.json"
    verdict_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), "utf-8")
    archive_path = output / "release-evidence.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(aggregate.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(aggregate).as_posix())
        archive.write(verdict_path, "final-verdict.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--finalizer", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--genesis-run-id", type=int, required=True)
    parser.add_argument("--genesis-request-id", required=True)
    parser.add_argument("--qualification-run-id", type=int, required=True)
    parser.add_argument("--qualification-head-sha", required=True)
    parser.add_argument("--g7-bundle-sha256", required=True)
    parser.add_argument("--physical-l5-sha256", required=True)
    args = parser.parse_args()

    aggregate = args.aggregate_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    history_path = aggregate / "genesis" / "genesis-history-verification.json"
    request_path = aggregate / "request" / "genesis-request-verification.json"
    finalizer_history_path = aggregate / "genesis" / "genesis-baseline-verification.json"
    failed: list[str] = []
    request: dict[str, Any] = {}

    try:
        request = _read(request_path)
        history = _read(history_path)
        failed.extend(
            _validate_request_and_history(
                request,
                history,
                repository=args.repository,
                genesis_run_id=args.genesis_run_id,
                request_id=args.genesis_request_id,
                qualification_run_id=args.qualification_run_id,
                qualification_head_sha=args.qualification_head_sha,
                g7_bundle_sha=args.g7_bundle_sha256.lower(),
                physical_l5_sha=args.physical_l5_sha256.lower(),
            )
        )
        finalizer_history_path.write_bytes(history_path.read_bytes())
    except Exception as exc:
        failed.append(f"genesis_orchestrator_input:{type(exc).__name__}:{exc}")

    if failed:
        _write_blocked(output, aggregate, failed)
        return 1

    command = [
        sys.executable,
        str(args.finalizer.resolve()),
        "--aggregate-dir",
        str(aggregate),
        "--output-dir",
        str(output),
        "--repository",
        args.repository,
        "--genesis-run-id",
        str(args.genesis_run_id),
        "--qualification-run-id",
        str(args.qualification_run_id),
        "--qualification-head-sha",
        args.qualification_head_sha,
        "--g7-bundle-sha256",
        args.g7_bundle_sha256.lower(),
        "--physical-l5-sha256",
        args.physical_l5_sha256.lower(),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        return completed.returncode

    try:
        record_path = output / "ImageLab-GENESIS-RELEASE-AUTHORIZATION.json"
        record = _read(record_path)
        if record.get("status") != "GENESIS_RELEASE_AUTHORIZED":
            raise ValueError("authorization record is not GENESIS_RELEASE_AUTHORIZED")
        if (output / "ImageLab-RELEASE-AUTHORIZATION.json").exists():
            raise ValueError("ordinary authorization record emitted in Genesis mode")
        if list(output.glob("ImageLab_by_LarannA_RELEASE_AUTHORIZED*_Setup_x64.exe")):
            raise ValueError("ordinary authorized installer emitted in Genesis mode")
        record.update(
            {
                "authorization_orchestrator": "release_gate/genesis/orchestrate_request_gate.py",
                "genesis_request_id": args.genesis_request_id,
                "genesis_request_sha256": request.get("request_sha256"),
                "genesis_history_evidence_sha256": _sha256(history_path),
            }
        )
        temp = output / ".authorization-record-orchestrated.tmp"
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
        temp.replace(record_path)
        return 0
    except Exception as exc:
        _write_blocked(
            output,
            aggregate,
            [f"genesis_orchestrator_postprocess:{type(exc).__name__}:{exc}"],
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
