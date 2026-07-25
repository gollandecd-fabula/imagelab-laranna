from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "zero-trust-genesis-request.yml"
SOURCE_WORKFLOW = SOURCE_ROOT / ".github" / "workflows" / "zero-trust-genesis-release.yml"
ATTEST_V4_SHA = "f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6"


def action_references(path: Path) -> list[tuple[str, str]]:
    workflow = path.read_text("utf-8")
    return re.findall(r"^\s*-\s+uses:\s+([^@\s]+)@([^\s]+)\s*$", workflow, re.MULTILINE)


def test_all_genesis_workflows_pin_every_external_action_to_commit_sha() -> None:
    for path in (ACTIVE_WORKFLOW, SOURCE_WORKFLOW):
        references = action_references(path)
        assert references, path
        for action, ref in references:
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"mutable action ref in {path}: {action}@{ref}"


def test_attestation_actions_use_exact_v4_commit_without_storage_record() -> None:
    for path in (ACTIVE_WORKFLOW, SOURCE_WORKFLOW):
        workflow = path.read_text("utf-8")
        assert f"uses: actions/attest@{ATTEST_V4_SHA}" in workflow
        assert "uses: actions/attest@v4" not in workflow
        assert "create-storage-record: false" in workflow
