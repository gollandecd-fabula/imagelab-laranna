from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

RULE = "GENESIS-FIRST-RELEASE-V1"
STATUS = "GENESIS_AUTHORIZATION_REQUESTED"
FIELDS = {
    "schema",
    "status",
    "release_mode",
    "protocol_rule",
    "repository",
    "request_id",
    "qualification_run_id",
    "qualification_head_sha",
    "g7_evidence_release_tag",
    "g7_evidence_bundle_sha256",
    "physical_l5_evidence_url",
    "physical_l5_evidence_sha256",
    "enable_attestation",
}


def _is_sha256(value: object) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")))


def _is_commit_sha(value: object) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", str(value or "")))


def _valid_tag(value: object) -> bool:
    text = str(value or "")
    return bool(text.strip()) and len(text) <= 200 and not any(character in text for character in "\r\n\0")


def _valid_https_url(value: object) -> bool:
    text = str(value or "").strip()
    if len(text) > 2048 or any(character in text for character in "\r\n\0"):
        return False
    parsed = urlsplit(text)
    return parsed.scheme.lower() == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None


def _placeholder_outputs() -> dict[str, str]:
    return {
        "request_id": "INVALID-GENESIS-REQUEST",
        "qualification_run_id": "0",
        "qualification_head_sha": "0" * 40,
        "g7_evidence_release_tag": "INVALID",
        "g7_evidence_bundle_sha256": "0" * 64,
        "physical_l5_evidence_url": "https://invalid.invalid/physical-l5.json",
        "physical_l5_evidence_sha256": "0" * 64,
        "enable_attestation": "false",
    }


def validate_request(
    value: Any,
    repository: str,
    source: str,
    request_sha256: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    errors: list[str] = []
    if not isinstance(value, dict):
        value = {}
        errors.append("request_root_not_object")
    unexpected = sorted(set(value) - FIELDS)
    missing = sorted(FIELDS - set(value))
    if unexpected:
        errors.append("unexpected_fields:" + ",".join(unexpected))
    if missing:
        errors.append("missing_fields:" + ",".join(missing))

    expected = {
        "schema": 2,
        "status": STATUS,
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "repository": repository,
    }
    for field, wanted in expected.items():
        if value.get(field) != wanted:
            errors.append(f"invalid:{field}")

    request_id = str(value.get("request_id") or "")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{7,79}", request_id):
        errors.append("invalid:request_id")
    run_id = value.get("qualification_run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        errors.append("invalid:qualification_run_id")
    if not _is_commit_sha(value.get("qualification_head_sha")):
        errors.append("invalid:qualification_head_sha")

    g7_tag = str(value.get("g7_evidence_release_tag") or "")
    if not _valid_tag(g7_tag):
        errors.append("invalid:g7_evidence_release_tag")
    if not _is_sha256(value.get("g7_evidence_bundle_sha256")):
        errors.append("invalid:g7_evidence_bundle_sha256")

    physical_url = str(value.get("physical_l5_evidence_url") or "")
    if not _valid_https_url(physical_url):
        errors.append("invalid:physical_l5_evidence_url")
    if not _is_sha256(value.get("physical_l5_evidence_sha256")):
        errors.append("invalid:physical_l5_evidence_sha256")
    if not isinstance(value.get("enable_attestation"), bool):
        errors.append("invalid:enable_attestation")

    status = "PASS" if not errors else "FAIL"
    evidence = {
        "schema": 2,
        "status": status,
        "release_mode": "genesis_first_release",
        "protocol_rule": RULE,
        "request_source": source,
        "repository": repository,
        "request_id": request_id,
        "request_sha256": request_sha256,
        "qualification_run_id": run_id,
        "qualification_head_sha": str(value.get("qualification_head_sha") or "").lower(),
        "g7_evidence_release_tag": g7_tag,
        "g7_evidence_bundle_sha256": str(value.get("g7_evidence_bundle_sha256") or "").lower(),
        "physical_l5_evidence_url": physical_url,
        "physical_l5_evidence_sha256": str(value.get("physical_l5_evidence_sha256") or "").lower(),
        "enable_attestation": value.get("enable_attestation"),
        "failed_conditions": errors,
    }
    outputs = _placeholder_outputs()
    if status == "PASS":
        outputs = {
            "request_id": request_id,
            "qualification_run_id": str(run_id),
            "qualification_head_sha": str(value["qualification_head_sha"]).lower(),
            "g7_evidence_release_tag": g7_tag,
            "g7_evidence_bundle_sha256": str(value["g7_evidence_bundle_sha256"]).lower(),
            "physical_l5_evidence_url": physical_url,
            "physical_l5_evidence_sha256": str(value["physical_l5_evidence_sha256"]).lower(),
            "enable_attestation": "true" if value["enable_attestation"] else "false",
        }
    return evidence, outputs


def _write_github_output(path: Path, outputs: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source", choices=("reviewed_recovery_push", "workflow_dispatch"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    outputs = _placeholder_outputs()
    try:
        raw = args.request.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
        evidence, outputs = validate_request(
            value,
            args.repository,
            args.source,
            hashlib.sha256(raw).hexdigest(),
        )
    except Exception as exc:
        evidence = {
            "schema": 2,
            "status": "FAIL",
            "release_mode": "genesis_first_release",
            "protocol_rule": RULE,
            "request_source": args.source,
            "repository": args.repository,
            "request_id": outputs["request_id"],
            "request_sha256": None,
            "failed_conditions": [f"{type(exc).__name__}: {exc}"],
        }
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), "utf-8")
    _write_github_output(args.github_output, outputs)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
