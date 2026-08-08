from __future__ import annotations

import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import AssetRecord
from app.services.project_store import ProjectStore, ProjectStoreError


def _asset(asset_id: str, *, source_asset_id: str | None = None) -> AssetRecord:
    now = datetime.now(timezone.utc).isoformat()
    return AssetRecord(
        id=asset_id,
        original_name=f"{asset_id}.png",
        stored_name=f"{asset_id}.png",
        preview_name=f"{asset_id}.preview.png",
        size_bytes=10,
        sha256="0" * 64,
        mime_type="image/png",
        format="PNG",
        ppi_origin="unknown",
        created_at=now,
        preview_url=f"/preview/{asset_id}",
        source_asset_id=source_asset_id,
        operation="enhance" if source_asset_id else None,
        parameters={"input_asset_id": source_asset_id} if source_asset_id else {},
    )


def _add_worker(directory: str, project_id: str, asset_id: str, start) -> None:
    store = ProjectStore(Path(directory) / "projects")
    start.wait(10)
    store.add_assets(project_id, [_asset(asset_id)])


def test_project_store_prevents_multiprocess_lost_update(tmp_path: Path) -> None:
    project_id = "concurrency"
    context = mp.get_context("spawn")
    start = context.Event()
    processes = [
        context.Process(target=_add_worker, args=(str(tmp_path), project_id, "a" * 8, start)),
        context.Process(target=_add_worker, args=(str(tmp_path), project_id, "b" * 8, start)),
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    project = ProjectStore(tmp_path / "projects").get_or_create(project_id)
    assert {asset.id for asset in project.assets} == {"a" * 8, "b" * 8}


def test_derived_commit_is_atomic_and_requires_live_source(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    source = _asset("a1b2c3d4")
    project = store.add_assets("ATOMIC", [source])
    assert len(project.assets) == 1

    result = _asset("d4c3b2a1", source_asset_id=source.id)
    committed = store.commit_derived_assets(
        "ATOMIC", source.id, [result], active_asset_id=result.id
    )
    assert [asset.id for asset in committed.assets] == [source.id, result.id]
    assert committed.workspace["active_asset_id"] == result.id

    before = (tmp_path / "projects" / "ATOMIC.json").read_bytes()
    orphan = _asset("e5f6a7b8", source_asset_id="f" * 8)
    with pytest.raises(ProjectStoreError, match="Исходный файл"):
        store.commit_derived_assets("ATOMIC", "f" * 8, [orphan])
    assert (tmp_path / "projects" / "ATOMIC.json").read_bytes() == before


def test_derived_commit_rejects_forged_lineage(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    source = _asset("e1f2a3b4")
    store.add_assets("LINEAGE", [source])

    forged = _asset("b4a3f2e1", source_asset_id="9" * 8)
    with pytest.raises(ProjectStoreError, match="Исходный файл"):
        store.add_assets("LINEAGE", [forged])

    mismatched = _asset("c4d5e6f7", source_asset_id=source.id)
    mismatched.parameters["input_asset_id"] = "8" * 8
    with pytest.raises(ProjectStoreError, match="Lineage"):
        store.add_assets("LINEAGE", [mismatched])

    project = store.get_or_create("LINEAGE")
    assert [asset.id for asset in project.assets] == [source.id]


def test_atomic_commit_rejects_mixed_sources(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    first = _asset("11112222")
    second = _asset("33334444")
    store.add_assets("MIXED", [first, second])
    a = _asset("55556666", source_asset_id=first.id)
    b = _asset("77778888", source_asset_id=second.id)
    with pytest.raises(ProjectStoreError, match="другой исходный"):
        store.commit_derived_assets("MIXED", first.id, [a, b])
    assert len(store.get_or_create("MIXED").assets) == 2
