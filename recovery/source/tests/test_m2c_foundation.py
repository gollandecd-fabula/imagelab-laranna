from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import PROJECT_SCHEMA_VERSION, AssetRecord, ProjectRecord
from app.services.project_store import ProjectStore, ProjectStoreError


def _asset(
    asset_id: str,
    *,
    source_asset_id: str | None = None,
    operation: str | None = None,
    digest: str = "a",
) -> AssetRecord:
    now = datetime.now(timezone.utc).isoformat()
    return AssetRecord(
        id=asset_id,
        original_name=f"{asset_id}.png",
        stored_name=f"{asset_id}.png",
        preview_name=f"{asset_id}.preview.png",
        size_bytes=10,
        sha256=digest * 64,
        mime_type="image/png",
        format="PNG",
        ppi_origin="embedded",
        created_at=now,
        preview_url=f"/preview/{asset_id}",
        source_asset_id=source_asset_id,
        operation=operation,
        parameters={"input_asset_id": source_asset_id} if source_asset_id else {},
    )


def _write_legacy(path: Path, project: ProjectRecord) -> bytes:
    payload = project.model_dump()
    payload.pop("schema_version", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")
    path.write_bytes(encoded)
    return encoded


def _complex_project(project_id: str) -> ProjectRecord:
    now = "2026-08-16T00:00:00+00:00"
    source = _asset("source01", digest="1")
    derivative = _asset(
        "deriv001",
        source_asset_id=source.id,
        operation="enhance",
        digest="2",
    )
    master = _asset(
        "master01",
        source_asset_id=source.id,
        operation="master_dtf",
        digest="3",
    )
    export = _asset(
        "export01",
        source_asset_id=source.id,
        operation="export",
        digest="4",
    )
    return ProjectRecord(
        id=project_id,
        title="Legacy mixed project",
        created_at=now,
        updated_at=now,
        assets=[source, derivative, master, export],
        workspace={
            "active_asset_id": export.id,
            "active_revision": 7,
            "history": [source.id, derivative.id, master.id, export.id],
            "masks": {source.id: {"edits": [{"tool": "add", "points": [[0.1, 0.2]]}]}},
            "presets": {
                "DTF": {
                    "module": "export",
                    "parameters": {"ppi": 300, "profile": "srgb"},
                }
            },
            "batch_reports": [
                {"id": "batch-1", "status": "CANCELLED", "completed": 2}
            ],
            "qa_reports": [
                {"id": "qa-1", "status": "PASS", "asset_id": export.id}
            ],
        },
    )


def test_legacy_project_migrates_in_memory_without_read_side_write(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    path = tmp_path / "LEGACY-001.json"
    original = _write_legacy(path, _complex_project("LEGACY-001"))
    original_hash = hashlib.sha256(original).hexdigest()

    loaded = store.get("LEGACY-001")

    assert loaded.schema_version == PROJECT_SCHEMA_VERSION
    assert path.read_bytes() == original
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_first_explicit_write_persists_current_schema_and_preserves_foundation(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    path = tmp_path / "LEGACY-002.json"
    legacy = _complex_project("LEGACY-002")
    original = _write_legacy(path, legacy)
    before = json.loads(original)

    loaded = store.get("LEGACY-002")
    source_before = loaded.assets[0].model_dump()
    workspace_before = json.loads(json.dumps(loaded.workspace))
    store.rename("LEGACY-002", "Migrated safely")

    persisted = json.loads(path.read_text("utf-8"))
    reopened = store.get("LEGACY-002")
    assert persisted["schema_version"] == PROJECT_SCHEMA_VERSION
    assert reopened.schema_version == PROJECT_SCHEMA_VERSION
    assert reopened.title == "Migrated safely"
    assert reopened.assets[0].model_dump() == source_before
    assert reopened.workspace == workspace_before
    assert persisted["assets"] == before["assets"]
    assert persisted["workspace"] == before["workspace"]
    assert reopened.collections.sources == ["source01"]
    assert reopened.collections.derivatives == ["deriv001", "master01", "export01"]
    assert reopened.collections.masters == ["master01"]
    assert reopened.collections.exports == ["export01"]
    assert reopened.collections.presets == workspace_before["presets"]
    assert reopened.collections.qa_reports == workspace_before["qa_reports"]


def test_future_or_invalid_schema_fails_closed_without_rewriting_data(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    base = _complex_project("FUTURE-001").model_dump()

    for value in (PROJECT_SCHEMA_VERSION + 1, -1, True, "1"):
        payload = dict(base)
        payload["schema_version"] = value
        path = tmp_path / "FUTURE-001.json"
        original = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(original)
        with pytest.raises(ProjectStoreError):
            store.get("FUTURE-001")
        assert path.read_bytes() == original


def test_mixed_legacy_and_current_projects_reload_without_cross_project_mutation(
    tmp_path: Path,
) -> None:
    store = ProjectStore(tmp_path)
    legacy_path = tmp_path / "LEGACY-MIXED.json"
    current_path = tmp_path / "CURRENT-MIXED.json"
    legacy_bytes = _write_legacy(legacy_path, _complex_project("LEGACY-MIXED"))
    current = _complex_project("CURRENT-MIXED")
    current_bytes = json.dumps(
        current.model_dump(), ensure_ascii=False, indent=2, allow_nan=False
    ).encode("utf-8")
    current_path.write_bytes(current_bytes)

    inventory = {project.id: project for project in store.list_projects()}

    assert set(inventory) == {"LEGACY-MIXED", "CURRENT-MIXED"}
    assert all(
        project.schema_version == PROJECT_SCHEMA_VERSION for project in inventory.values()
    )
    assert legacy_path.read_bytes() == legacy_bytes
    assert current_path.read_bytes() == current_bytes
    assert inventory["LEGACY-MIXED"].workspace == inventory["CURRENT-MIXED"].workspace
    assert [a.sha256 for a in inventory["LEGACY-MIXED"].assets] == [
        a.sha256 for a in inventory["CURRENT-MIXED"].assets
    ]


def test_schema_migration_is_deterministic_and_preserves_lineage(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    path = tmp_path / "DETERMINISTIC.json"
    original = _write_legacy(path, _complex_project("DETERMINISTIC"))

    first = store.get("DETERMINISTIC")
    second = store.get("DETERMINISTIC")

    first_dump = first.model_dump()
    second_dump = second.model_dump()
    assert first_dump == second_dump
    assert path.read_bytes() == original
    assert [(a.id, a.source_asset_id, a.parameters.get("input_asset_id")) for a in first.assets] == [
        ("source01", None, None),
        ("deriv001", "source01", "source01"),
        ("master01", "source01", "source01"),
        ("export01", "source01", "source01"),
    ]
