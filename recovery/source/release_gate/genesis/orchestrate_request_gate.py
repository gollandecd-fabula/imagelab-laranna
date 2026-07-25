from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

RULE = "GENESIS-FIRST-RELEASE-V1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} root is not an object")
    return value


def _cleanup_authorized(output: Path) -> None:
    for path in list(output.glob("*RELEASE_AUTHORIZED*.exe")) + [
        output / "ImageLab-RELEASE-AUTHORIZATION.json",
        output / "installer-sha256.txt",
    ]:
        if path.exists():
            path.unlink()


def _compatibility_evidence(history: dict[str, Any], repository: str, valid: bool) -> dict[str, Any]:
    return {
        "schema": 1,
        "status": "PASS" if valid else "FAIL",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "query_source": "github_api_releases_paginated",
        "query_complete": bool(history.get("query_complete")) if valid else False,
        "release_count_scanned": history.get("release_count_scanned", 0),
        "authorized_installer_asset_count": history.get("authorized_installer_asset_count"),
        "authorization_record_asset_count": history.get("authorization_record_asset_count"),
        "matching_assets": history.get("matching_assets", []),
        "history_evidence_sha256": None,
    }


def _validate_request_and_history(
    request: dict[str, Any],
    history: dict[str, Any],
    *,
    repository: str,
    request_id: str,
    qualification_run_id: int,
    qualification_head_sha: str,
    manifest_sha: str,
    bundle_sha: str,
) -> list[str]:
    failed: list[str] = []
    expected_request = {
        "schema": 1,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "request_id": request_id,
        "qualification_run_id": qualification_run_id,
        "qualification_head_sha": qualification_head_sha,
        "physical_l5_manifest_sha256": manifest_sha,
        "physical_l5_bundle_sha256": bundle_sha,
        "failed_conditions": [],
    }
    for field, wanted in expected_request.items():
        if request.get(field) != wanted:
            failed.append(f"genesis_request_invalid:{field}")
    if request.get("request_source") not in {"reviewed_recovery_push", "workflow_dispatch"}:
        failed.append("genesis_request_invalid:request_source")
    if not isinstance(request.get("enable_attestation"), bool):
        failed.append("genesis_request_invalid:enable_attestation")
    request_sha = str(request.get("request_sha256") or "")
    if len(request_sha) != 64 or any(ch not in "0123456789abcdef" for ch in request_sha.lower()):
        failed.append("genesis_request_invalid:request_sha256")

    expected_history = {
        "schema": 2,
        "status": "PASS",
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
        "query_source": "github_api_releases_actions_paginated",
        "query_complete": True,
        "authorized_installer_asset_count": 0,
        "authorization_record_asset_count": 0,
        "prior_successful_genesis_run_count": 0,
        "prior_authorized_genesis_artifact_count": 0,
        "prior_successful_genesis_run_ids": [],
        "prior_authorized_genesis_artifacts": [],
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
        "schema": 4,
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
    parser.add_argument("--genesis-request-id", required=True)
    parser.add_argument("--qualification-run-id", type=int, required=True)
    parser.add_argument("--qualification-head-sha", required=True)
    parser.add_argument("--physical-manifest-sha256", required=True)
    parser.add_argument("--physical-bundle-sha256", required=True)
    args = parser.parse_args()

    aggregate = args.aggregate_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    history_path = aggregate / "genesis" / "genesis-history-verification.json"
    request_path = aggregate / "request" / "genesis-request-verification.json"
    compat_path = aggregate / "genesis" / "genesis-baseline-verification.json"
    failed: list[str] = []
    try:
        request = _read(request_path)
        history = _read(history_path)
        failed.extend(
            _validate_request_and_history(
                request,
                history,
                repository=args.repository,
                request_id=args.genesis_request_id,
                qualification_run_id=args.qualification_run_id,
                qualification_head_sha=args.qualification_head_sha,
                manifest_sha=args.physical_manifest_sha256.lower(),
                bundle_sha=args.physical_bundle_sha256.lower(),
            )
        )
        compat = _compatibility_evidence(history, args.repository, not failed)
        compat["history_evidence_sha256"] = _sha256(history_path)
        compat_path.write_text(json.dumps(compat, ensure_ascii=False, indent=2), "utf-8")
    except Exception as exc:
        failed.append(f"genesis_orchestrator_input:{type(exc).__name__}:{exc}")
        compat_path.parent.mkdir(parents=True, exist_ok=True)
        compat_path.write_text(
            json.dumps(_compatibility_evidence({}, args.repository, False), ensure_ascii=False, indent=2),
            "utf-8",
        )
        request = {}

    command = [
        sys.executable,
        str(args.finalizer.resolve()),
        "--aggregate-dir",
        str(aggregate),
        "--output-dir",
        str(output),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)

    if failed or completed.returncode != 0:
        if completed.returncode == 0:
            failed.append("legacy_genesis_finalizer_unexpected_success")
        _write_blocked(output, aggregate, failed or ["legacy_genesis_finalizer_blocked"])
        return 1

    try:
        record_path = output / "ImageLab-RELEASE-AUTHORIZATION.json"
        record = _read(record_path)
        if record.get("status") != "RELEASE_AUTHORIZED":
            raise ValueError("authorization record is not RELEASE_AUTHORIZED")
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
        _write_blocked(output, aggregate, [f"genesis_orchestrator_postprocess:{type(exc).__name__}:{exc}"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
