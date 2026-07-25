from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import AssetRecord, ProjectRecord, validate_project_identifier


class ProjectStoreError(ValueError):
    pass


MAX_ASSETS_PER_PROJECT = 5000
_LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.025


class _ProcessFileLock(AbstractContextManager["_ProcessFileLock"]):
    """Small cross-platform exclusive file lock with no external dependency."""

    def __init__(self, path: Path, timeout: float = _LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_ProcessFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        self._fd = fd
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    self._fd = None
                    raise ProjectStoreError(
                        f"Не удалось получить блокировку проекта: {self.path.name}"
                    ) from exc
                time.sleep(_LOCK_POLL_SECONDS)
                os.lseek(fd, 0, os.SEEK_SET)

    def __exit__(self, exc_type, exc, traceback) -> None:
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _merge_ai(existing: dict, incoming: dict) -> dict:
    """Merge AI evidence without dropping keys written by another request."""

    merged = dict(existing)
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge_ai(current, value)
        else:
            merged[key] = value
    return merged


class ProjectStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or settings.project_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, project_id: str) -> Path:
        try:
            safe = validate_project_identifier(project_id)
        except ValueError as exc:
            raise ProjectStoreError(str(exc)) from exc
        path = (self.directory / f"{safe}.json").resolve()
        if path.parent != self.directory:
            raise ProjectStoreError("Путь проекта выходит за каталог проектов")
        return path

    def _project_lock(self, project_id: str) -> _ProcessFileLock:
        path = self._path(project_id)
        return _ProcessFileLock(path.with_suffix(".lock"))

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

    @staticmethod
    def _new_project(project_id: str) -> ProjectRecord:
        now = datetime.now(timezone.utc).isoformat()
        return ProjectRecord(
            id=project_id,
            title=project_id,
            created_at=now,
            updated_at=now,
            workspace={"ppi": settings.workspace_ppi, "units": "mm"},
        )

    def _get_unlocked(self, project_id: str) -> ProjectRecord:
        path = self._path(project_id)
        if not path.exists():
            raise ProjectStoreError("Проект не найден")
        return self._read(path)

    def _get_or_create_unlocked(self, project_id: str) -> ProjectRecord:
        path = self._path(project_id)
        if path.exists():
            return self._read(path)
        project = self._new_project(project_id)
        self._save_unlocked(project)
        return project

    def _save_unlocked(self, project: ProjectRecord) -> None:
        if len(project.assets) > MAX_ASSETS_PER_PROJECT:
            raise ProjectStoreError("Проект содержит слишком много файлов")
        project.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._path(project.id)
        encoded = json.dumps(
            project.model_dump(), ensure_ascii=False, indent=2, allow_nan=False
        ).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=self.directory
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
            if os.name != "nt":
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _validate_new_assets(project: ProjectRecord, assets: list[AssetRecord]) -> None:
        if len(project.assets) + len(assets) > MAX_ASSETS_PER_PROJECT:
            raise ProjectStoreError("Проект достиг лимита файлов")
        known_ids = {asset.id for asset in project.assets}
        incoming_ids: set[str] = set()
        for asset in assets:
            if asset.id in known_ids or asset.id in incoming_ids:
                raise ProjectStoreError("Дублирующийся идентификатор файла")
            if asset.source_asset_id is not None:
                if not asset.operation:
                    raise ProjectStoreError("Производный файл должен содержать операцию")
                if (
                    asset.source_asset_id not in known_ids
                    and asset.source_asset_id not in incoming_ids
                ):
                    raise ProjectStoreError(
                        "Исходный файл производного результата отсутствует в проекте"
                    )
                if asset.source_asset_id == asset.id:
                    raise ProjectStoreError("Файл не может ссылаться сам на себя")
                input_asset_id = asset.parameters.get("input_asset_id")
                if (
                    input_asset_id is not None
                    and input_asset_id != asset.source_asset_id
                ):
                    raise ProjectStoreError(
                        "Lineage результата не совпадает с зафиксированным входным файлом"
                    )
            incoming_ids.add(asset.id)

    def get_or_create(self, project_id: str) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            return self._get_or_create_unlocked(project_id)

    def get(self, project_id: str) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            return self._get_unlocked(project_id)

    def create(self, project_id: str, title: str | None = None) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            path = self._path(project_id)
            if path.exists():
                raise ProjectStoreError("Проект уже существует")
            project = self._new_project(project_id)
            if title is not None:
                project.title = title
            self._save_unlocked(project)
            return project

    def list_projects(self) -> list[ProjectRecord]:
        projects: list[ProjectRecord] = []
        with self._lock:
            for project_file in sorted(self.directory.glob("*.json")):
                try:
                    project_id = project_file.stem
                    with self._project_lock(project_id):
                        projects.append(self._read(project_file))
                except ProjectStoreError:
                    continue
        return sorted(
            projects, key=lambda item: (item.updated_at, item.id), reverse=True
        )

    def rename(self, project_id: str, title: str) -> ProjectRecord:
        title = title.strip()
        if not title or len(title) > 160:
            raise ProjectStoreError(
                "Название проекта должно содержать от 1 до 160 символов"
            )
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            project.title = title
            self._save_unlocked(project)
            return project

    def set_preset(
        self, project_id: str, name: str, module: str, parameters: dict
    ) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            presets = dict(project.workspace.get("presets") or {})
            presets[name] = {"module": module, "parameters": parameters}
            project.workspace["presets"] = presets
            self._save_unlocked(project)
            return project

    def delete_preset(self, project_id: str, name: str) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            presets = dict(project.workspace.get("presets") or {})
            if name not in presets:
                raise ProjectStoreError("Профиль не найден")
            del presets[name]
            project.workspace["presets"] = presets
            self._save_unlocked(project)
            return project

    def save(self, project: ProjectRecord) -> None:
        """Merge AI metadata from a snapshot without overwriting live project state.

        This legacy entry point is used by on-demand AI analysis. The caller may
        hold a snapshot that predates concurrent uploads, title/preset changes or
        active-asset changes. Only AI dictionaries for still-existing assets are
        merged; project structure and workspace always come from the live file.
        """

        with self._lock, self._project_lock(project.id):
            current = self._get_unlocked(project.id)
            incoming_by_id = {asset.id: asset for asset in project.assets}
            for current_asset in current.assets:
                incoming = incoming_by_id.get(current_asset.id)
                if incoming is None:
                    continue
                immutable_fields = (
                    "stored_name",
                    "preview_name",
                    "sha256",
                    "source_asset_id",
                )
                if any(
                    getattr(current_asset, field) != getattr(incoming, field)
                    for field in immutable_fields
                ):
                    raise ProjectStoreError(
                        "Снимок AI-анализа не совпадает с текущей версией файла"
                    )
                current_asset.ai = _merge_ai(current_asset.ai, incoming.ai)
            self._save_unlocked(current)

    def add_assets(self, project_id: str, assets: list[AssetRecord]) -> ProjectRecord:
        """Explicit upload/import transaction; creates the project when absent."""

        with self._lock, self._project_lock(project_id):
            project = self._get_or_create_unlocked(project_id)
            self._validate_new_assets(project, assets)
            project.assets.extend(assets)
            if assets:
                project.workspace["active_asset_id"] = assets[-1].id
                project.workspace["active_revision"] = int(
                    project.workspace.get("active_revision", 0)
                ) + 1
            self._save_unlocked(project)
            return project

    def commit_assets_existing(
        self,
        project_id: str,
        assets: list[AssetRecord],
        *,
        active_asset_id: str | None = None,
    ) -> ProjectRecord:
        """Atomically append a validated multi-source batch to an existing project."""

        if not assets:
            raise ProjectStoreError("Нет файлов для сохранения")
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            self._validate_new_assets(project, assets)
            selected = active_asset_id or assets[-1].id
            if selected not in {asset.id for asset in assets}:
                raise ProjectStoreError(
                    "Активный результат отсутствует в атомарном наборе"
                )
            project.assets.extend(assets)
            project.workspace["active_asset_id"] = selected
            project.workspace["active_revision"] = int(
                project.workspace.get("active_revision", 0)
            ) + 1
            self._save_unlocked(project)
            return project

    def commit_derived_assets(
        self,
        project_id: str,
        source_asset_id: str,
        assets: list[AssetRecord],
        *,
        active_asset_id: str | None = None,
    ) -> ProjectRecord:
        """Atomically verify lineage, add all results and select one active result."""

        if not assets:
            raise ProjectStoreError("Нет производных файлов для сохранения")
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            if not any(asset.id == source_asset_id for asset in project.assets):
                raise ProjectStoreError(
                    "Исходный файл производного результата отсутствует в проекте"
                )
            for asset in assets:
                if asset.source_asset_id != source_asset_id:
                    raise ProjectStoreError(
                        "Производный файл ссылается на другой исходный файл"
                    )
                input_asset_id = asset.parameters.get("input_asset_id")
                if input_asset_id is not None and input_asset_id != source_asset_id:
                    raise ProjectStoreError(
                        "Lineage результата не совпадает с зафиксированным входным файлом"
                    )
            self._validate_new_assets(project, assets)
            selected = active_asset_id or assets[-1].id
            if selected not in {asset.id for asset in assets}:
                raise ProjectStoreError(
                    "Активный результат отсутствует в атомарном наборе"
                )
            project.assets.extend(assets)
            project.workspace["active_asset_id"] = selected
            project.workspace["active_revision"] = int(
                project.workspace.get("active_revision", 0)
            ) + 1
            self._save_unlocked(project)
            return project

    def set_active_asset(self, project_id: str, asset_id: str) -> ProjectRecord:
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            if not any(asset.id == asset_id for asset in project.assets):
                raise ProjectStoreError("Активный файл не найден в проекте")
            project.workspace["active_asset_id"] = asset_id
            project.workspace["active_revision"] = int(
                project.workspace.get("active_revision", 0)
            ) + 1
            self._save_unlocked(project)
            return project

    def clear_assets(self, project_id: str) -> tuple[ProjectRecord, list[AssetRecord]]:
        with self._lock, self._project_lock(project_id):
            project = self._get_unlocked(project_id)
            removed = list(project.assets)
            project.assets = []
            project.workspace.pop("active_asset_id", None)
            project.workspace["active_revision"] = int(
                project.workspace.get("active_revision", 0)
            ) + 1
            self._save_unlocked(project)
            return project, removed

    def find_asset(self, asset_id: str) -> tuple[ProjectRecord, AssetRecord] | None:
        if not asset_id.isalnum() or not (8 <= len(asset_id) <= 64):
            return None
        with self._lock:
            for project_file in sorted(self.directory.glob("*.json")):
                project_id = project_file.stem
                try:
                    with self._project_lock(project_id):
                        project = self._read(project_file)
                except ProjectStoreError:
                    continue
                for asset in project.assets:
                    if asset.id == asset_id:
                        return project, asset
        return None

    def referenced_storage_names(
        self, exclude_project_id: str | None = None
    ) -> set[str]:
        names: set[str] = set()
        with self._lock:
            for project_file in sorted(self.directory.glob("*.json")):
                project_id = project_file.stem
                try:
                    with self._project_lock(project_id):
                        project = self._read(project_file)
                except ProjectStoreError:
                    continue
                if exclude_project_id and project.id == exclude_project_id:
                    continue
                for asset in project.assets:
                    names.add(asset.stored_name)
                    names.add(asset.preview_name)
        return names
