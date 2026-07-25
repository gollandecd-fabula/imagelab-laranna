from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.services.project_store import ProjectStore, ProjectStoreError


def test_corrupt_unrelated_project_does_not_disable_inventory(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    valid = store.create("VALID-001", "Рабочий проект")
    (tmp_path / "BROKEN-001.json").write_text("{not-json", "utf-8")
    projects = store.list_projects()
    assert [item.id for item in projects] == [valid.id]
    assert store.get(valid.id).title == "Рабочий проект"


@pytest.mark.parametrize("project_id", ["CON", "con", "NUL", "COM1", "LPT9"])
def test_windows_reserved_project_ids_are_rejected(project_id: str, tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    with pytest.raises(ProjectStoreError, match="зарезервирован"):
        store.create(project_id)
    assert not list(tmp_path.glob("*.json"))


def test_missing_project_mutations_do_not_create_files(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    with pytest.raises(ProjectStoreError, match="не найден"):
        store.rename("MISSING-001", "Новое имя")
    with pytest.raises(ProjectStoreError, match="не найден"):
        store.set_preset("MISSING-001", "Профиль", "cleanup", {"remove_halo": True})
    with pytest.raises(ProjectStoreError, match="не найден"):
        store.clear_assets("MISSING-001")
    assert not (tmp_path / "MISSING-001.json").exists()


def test_get_or_create_is_bootstrap_only_and_read_paths_do_not_write(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    with pytest.raises(ProjectStoreError, match="не найден"):
        store.get_or_create("READ-ONLY-MISSING")
    assert not (tmp_path / "READ-ONLY-MISSING.json").exists()

    default = store.get_or_create(settings.default_project_id)
    assert default.id == settings.default_project_id
    assert (tmp_path / f"{settings.default_project_id}.json").exists()
