from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA40 = re.compile(r"[0-9a-f]{40}")
HISTORICAL = {
    "bootstrap-windows-gate-rc11-execution.yml",
    "rc12-windows-gate.yml",
    "rc13-windows-gate.yml",
    "diagnostic-real-project-preservation-148-to-149.yml",
    "diagnostic-update-rollback-148-to-149.yml",
    "recovery-apply-verified-patch.yml",
    "recovery-pr-apply-rc12.yml",
    "recovery-pr-apply-rc13.yml",
    "recovery-promote-bootstrap-rc13.yml",
}


def load_workflow(path: Path) -> dict:
    value = yaml.safe_load(path.read_text("utf-8"))
    assert isinstance(value, dict), f"workflow root must be mapping: {path.name}"
    # PyYAML 1.1 may parse the key `on` as boolean True.
    if True in value and "on" not in value:
        value["on"] = value.pop(True)
    return value


def event_names(workflow: dict) -> set[str]:
    value = workflow.get("on")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, dict):
        return {str(item) for item in value}
    raise AssertionError(f"invalid workflow event declaration: {value!r}")


def test_all_workflows_parse_and_external_actions_are_immutable() -> None:
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = load_workflow(path)
        assert workflow.get("name"), path.name
        for line in path.read_text("utf-8").splitlines():
            match = re.match(r"\s*-\s+uses:\s+([^@\s]+)@([^\s]+)\s*$", line)
            if match:
                assert SHA40.fullmatch(match.group(2)), f"mutable action ref in {path.name}: {line.strip()}"


def test_automatic_workflows_never_have_repository_write_permission() -> None:
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = load_workflow(path)
        events = event_names(workflow)
        automatic = events - {"workflow_dispatch"}
        permissions = workflow.get("permissions") or {}
        if isinstance(permissions, str):
            contents = permissions
        else:
            contents = permissions.get("contents")
        assert not (automatic and contents == "write"), f"automatic contents:write workflow: {path.name}"


def test_historical_workflows_are_manual_read_only_and_fail_closed() -> None:
    for name in HISTORICAL:
        path = WORKFLOWS / name
        workflow = load_workflow(path)
        assert event_names(workflow) == {"workflow_dispatch"}, name
        assert (workflow.get("permissions") or {}).get("contents") == "read", name
        source = path.read_text("utf-8")
        assert "RETIRED" in source and "exit 1" in source, name


def test_no_temporary_write_appliers_remain() -> None:
    names = {path.name for path in WORKFLOWS.glob("*.y*ml")}
    assert not any(name.startswith("apply-full-audit-") for name in names)
