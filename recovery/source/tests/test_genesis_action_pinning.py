from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_WORKFLOW = ROOT / ".github" / "workflows" / "zero-trust-genesis-request.yml"
ATTEST_V4_SHA = "f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6"


def test_active_genesis_workflow_pins_every_external_action_to_commit_sha() -> None:
    workflow = ACTIVE_WORKFLOW.read_text("utf-8")
    references = re.findall(r"^\s*-\s+uses:\s+([^@\s]+)@([^\s]+)\s*$", workflow, re.MULTILINE)
    assert references
    for action, ref in references:
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"mutable action ref: {action}@{ref}"


def test_active_attestation_action_is_exact_v4_commit_without_storage_record() -> None:
    workflow = ACTIVE_WORKFLOW.read_text("utf-8")
    assert f"uses: actions/attest@{ATTEST_V4_SHA}" in workflow
    assert "uses: actions/attest@v4" not in workflow
    assert "create-storage-record: false" in workflow
