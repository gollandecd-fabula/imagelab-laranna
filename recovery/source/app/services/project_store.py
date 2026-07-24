from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import AssetRecord, ProjectRecord


class ProjectStoreError(ValueError):
    pass


MAX_ASSETS_PER_PROJECT = 5000


class ProjectStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or settings.project_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, project_id: str) -> Path:
        safe = "".join(ch for ch in project_id if ch.isalnum() or ch in {"-", "_"})
        if not safe or safe != project_id or len(project_id) > 64:
            raise ProjectStoreError("Некорректный идентификатор проекта")
        path = (self.directory / f"{safe}.json").resolve()
        if path.parent != self.directory:
            raise ProjectStoreError("Путь проекта выходит за каталог проектов")
        return path

    @staticmethod
    def _read(path: Path) -> ProjectRecord:
        try:
            if path.stat().st_size > 100 * 1024 * 1024:
                raise ProjectStoreError("Файл проекта превышает безопасный лимит")
            return ProjectRecord.model_validate_json(path.read_text("utf-8"))
        except ProjectStoreError:
            raise
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ProjectStoreError(f"Файл проекта повреждён: {path.name}") from exc

    def get_or_create(self, project_id: str) -> ProjectRecord:
        with self._lock:
            path = self._path(project_id)
            if path.exists():
                return self._read(path)
            now = datetime.now(timezone.utc).isoformat()
            project = ProjectRecord(
                id=project_id,
                title=project_id,
                created_at=now,
                updated_at=now,
                workspace={"ppi": settings.workspace_ppi, "units": "mm"},
            )
            self.save(project)
            return project

    def save(self, project: ProjectRecord) -> None:
        with self._lock:
            if len(project.assets) > MAX_ASSETS_PER_PROJECT:
                raise ProjectStoreError("Проект содержит слишком много файлов")
            project.updated_at = datetime.now(timezone.utc).isoformat()
            path = self._path(project.id)
            encoded = json.dumps(project.model_dump(), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
            fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            finally:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass

    def add_assets(self, project_id: str, assets: list[AssetRecord]) -> ProjectRecord:
        with self._lock:
            project = self.get_or_create(project_id)
            if len(project.assets) + len(assets) > MAX_ASSETS_PER_PROJECT:
                raise ProjectStoreError("Проект достиг лимита файлов")
            existing_ids = {asset.id for asset in project.assets}
            for asset in assets:
                if asset.id in existing_ids:
                    raise ProjectStoreError("Дублирующийся идентификатор файла")
                existing_ids.add(asset.id)
            project.assets.extend(assets)
            if assets:
                project.workspace["active_asset_id"] = assets[-1].id
                project.workspace["active_revision"] = int(project.workspace.get("active_revision", 0)) + 1
            self.save(project)
            return project


    def set_active_asset(self, project_id: str, asset_id: str) -> ProjectRecord:
        with self._lock:
            project = self.get_or_create(project_id)
            if not any(asset.id == asset_id for asset in project.assets):
                raise ProjectStoreError("Активный файл не найден в проекте")
            project.workspace["active_asset_id"] = asset_id
            project.workspace["active_revision"] = int(project.workspace.get("active_revision", 0)) + 1
            self.save(project)
            return project

    def clear_assets(self, project_id: str) -> tuple[ProjectRecord, list[AssetRecord]]:
        with self._lock:
            project = self.get_or_create(project_id)
            removed = list(project.assets)
            project.assets = []
            project.workspace.pop("active_asset_id", None)
            project.workspace["active_revision"] = int(project.workspace.get("active_revision", 0)) + 1
            self.save(project)
            return project, removed

    def find_asset(self, asset_id: str) -> tuple[ProjectRecord, AssetRecord] | None:
        if not asset_id.isalnum() or not (8 <= len(asset_id) <= 64):
            return None
        with self._lock:
            for project_file in sorted(self.directory.glob("*.json")):
                try:
                    project = self._read(project_file)
                except ProjectStoreError:
                    # A corrupt unrelated project must not expose files or disable all
                    # other projects. Its own access still fails through get_or_create.
                    continue
                for asset in project.assets:
                    if asset.id == asset_id:
                        return project, asset
        return None

    def referenced_storage_names(self, exclude_project_id: str | None = None) -> set[str]:
        names: set[str] = set()
        with self._lock:
            for project_file in sorted(self.directory.glob("*.json")):
                try:
                    project = self._read(project_file)
                except ProjectStoreError:
                    continue
                if exclude_project_id and project.id == exclude_project_id:
                    continue
                for asset in project.assets:
                    names.add(asset.stored_name)
                    names.add(asset.preview_name)
        return names
