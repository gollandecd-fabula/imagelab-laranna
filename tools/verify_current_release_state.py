#!/usr/bin/env python3
"""Verify that the current release-state index matches immutable evidence.

This verifier does not authorize release. It only prevents stale or contradictory
status documents from being presented as the current state.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "recovery" / "evidence" / "current-release-state.json"
WINDOWS_PATH = (
    ROOT
    / "recovery"
    / "evidence"
    / "windows-gate"
    / "rc13-windows-evidence-summary.json"
)
BLOCKER_PATH = (
    ROOT
    / "recovery"
    / "evidence"
    / "update-rollback"
    / "g6-authorized-baseline-blocker.json"
)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []

    try:
        state = load_json(STATE_PATH)
        windows = load_json(WINDOWS_PATH)
        blocker = load_json(BLOCKER_PATH)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        print(json.dumps({"status": "FAIL", "failures": [str(error)]}, sort_keys=True))
        return 1

    state_identity = state.get("identity", {})
    windows_identity = windows.get("identity", {})
    windows_source = windows.get("source", {})
    windows_installer = windows.get("installer", {})

    require(
        state_identity.get("version") == windows_identity.get("version"),
        "CURRENT_VERSION_MISMATCH",
        failures,
    )
    require(
        state_identity.get("build_id") == windows_identity.get("build_id"),
        "CURRENT_BUILD_ID_MISMATCH",
        failures,
    )
    require(
        state_identity.get("source_sha256") == windows_source.get("bootstrap_sha256"),
        "CURRENT_SOURCE_SHA256_MISMATCH",
        failures,
    )
    require(
        state_identity.get("installer_name") == windows_installer.get("name"),
        "CURRENT_INSTALLER_NAME_MISMATCH",
        failures,
    )
    require(
        state_identity.get("installer_sha256") == windows_installer.get("sha256"),
        "CURRENT_INSTALLER_SHA256_MISMATCH",
        failures,
    )
    require(
        windows_installer.get("sha256") == windows_installer.get("second_build_sha256"),
        "WINDOWS_REPRODUCIBILITY_SHA_MISMATCH",
        failures,
    )
    require(
        windows_installer.get("reproducible") is True,
        "WINDOWS_REPRODUCIBILITY_NOT_TRUE",
        failures,
    )

    expected_hosted = {
        "B0": "PASS",
        "B1": "PASS",
        "B2": "PASS",
        "B3_B5": "PASS",
        "B8": "PASS",
    }
    require(
        windows.get("gates") == expected_hosted,
        "HOSTED_GATE_SET_NOT_EXACT_PASS",
        failures,
    )

    state_blocked = state.get("blocked_or_unverified", {})
    blocker_boundary = blocker.get("claim_boundary", {})
    require(
        blocker.get("status") == "BASELINE_NOT_AVAILABLE",
        "G6_BLOCKER_STATUS_MISMATCH",
        failures,
    )
    require(
        blocker_boundary.get("G6") == "BLOCKED"
        and state_blocked.get("G6") == "BLOCKED_BASELINE_NOT_AVAILABLE",
        "G6_CURRENT_STATE_NOT_BLOCKED",
        failures,
    )
    require(
        blocker_boundary.get("G7") == "BLOCKED"
        and state_blocked.get("G7")
        == "BLOCKED_AUTHORIZING_FORM_DIAGNOSTIC_MECHANISM_PASS",
        "G7_CURRENT_STATE_NOT_BLOCKED",
        failures,
    )
    require(
        blocker_boundary.get("physical_L5") == "UNVERIFIED"
        and state_blocked.get("physical_user_machine_L5") == "UNVERIFIED",
        "PHYSICAL_L5_CLAIM_EXCEEDS_EVIDENCE",
        failures,
    )
    require(
        blocker_boundary.get("release") == "BLOCKED"
        and state_blocked.get("release") == "BLOCKED",
        "RELEASE_NOT_FAIL_CLOSED",
        failures,
    )

    verdict = {
        "schema": 1,
        "status": "PASS" if not failures else "FAIL",
        "checked": {
            "state": str(STATE_PATH.relative_to(ROOT)),
            "windows": str(WINDOWS_PATH.relative_to(ROOT)),
            "g6_blocker": str(BLOCKER_PATH.relative_to(ROOT)),
        },
        "identity": state_identity,
        "failures": failures,
        "release": "BLOCKED",
    }
    print(json.dumps(verdict, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
