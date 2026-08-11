from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.ai.runtime import get_ai_engine
from app.config import settings
from app.services.project_store import ProjectStore, ProjectStoreError

_ALLOWED_WORKSPACE_SECTIONS = {
    "settings",
    "size_controller",
    "masks",
    "batch_reports",
    "qa_reports",
    "autopilot",
}
_ALLOWED_PRESET_MODULES = {
    "improve",
    "extract",
    "selection",
    "background",
    "cleanup",
    "color",
    "palette",
    "halftone",
    "vector",
    "geometry",
    "dtf",
    "masters",
    "logo",
    "export",
    "cardlab",
}
_SECRET_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|authorization)", re.I)
_MAX_WORKSPACE_BYTES = 256 * 1024
_MAX_DEPTH = 8
_MAX_ITEMS = 500
_MAX_STRING = 4096


class M2AWorkspacePayload(BaseModel):
    value: Any


class M2APresetPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    module: str = Field(min_length=1, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)


def _validate_safe_value(value: Any, *, depth: int = 0, path: str = "value") -> None:
    if depth > _MAX_DEPTH:
        raise ValueError(f"Слишком глубокая структура: {path}")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Некорректное число: {path}")
        return
    if isinstance(value, str):
        if len(value) > _MAX_STRING:
            raise ValueError(f"Слишком длинная строка: {path}")
        if value.startswith("data:image/"):
            raise ValueError("Содержимое изображения нельзя сохранять в workspace")
        return
    if isinstance(value, list):
        if len(value) > _MAX_ITEMS:
            raise ValueError(f"Слишком много элементов: {path}")
        for index, item in enumerate(value):
            _validate_safe_value(item, depth=depth + 1, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        if len(value) > _MAX_ITEMS:
            raise ValueError(f"Слишком много полей: {path}")
        for raw_key, item in value.items():
            key = str(raw_key)
            if not key or len(key) > 96:
                raise ValueError(f"Некорректный ключ: {path}")
            if _SECRET_KEY.search(key):
                raise ValueError(f"Секретные данные запрещены в workspace: {key}")
            _validate_safe_value(item, depth=depth + 1, path=f"{path}.{key}")
        return
    raise ValueError(f"Неподдерживаемый тип данных: {path}")


def _bounded_json(value: Any) -> None:
    _validate_safe_value(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_WORKSPACE_BYTES:
        raise ValueError("Workspace превышает безопасный лимит 256 КБ")


def _workspace_view(workspace: dict[str, Any]) -> dict[str, Any]:
    return {key: workspace.get(key) for key in sorted(_ALLOWED_WORKSPACE_SECTIONS) if key in workspace}


def _write_workspace_section(store: ProjectStore, project_id: str, section: str, value: Any):
    if section not in _ALLOWED_WORKSPACE_SECTIONS:
        raise ProjectStoreError("Раздел workspace не разрешён в M2A")
    _bounded_json(value)
    with store._lock, store._project_lock(project_id):
        project = store._get_unlocked(project_id)
        if section == "masks":
            known = {asset.id for asset in project.assets}
            unknown = [key for key in value if key not in known] if isinstance(value, dict) else ["invalid"]
            if unknown:
                raise ProjectStoreError("Маска относится к отсутствующему файлу проекта")
        project.workspace[section] = value
        store._save_unlocked(project)
        return project


def _sanitize_models(raw_models: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(raw_models, list):
        return result
    allowed = ("model_id", "id", "version", "status", "provider", "runtime", "health")
    for item in raw_models[:100]:
        if isinstance(item, dict):
            clean = {key: item.get(key) for key in allowed if item.get(key) is not None}
            if clean:
                result.append(clean)
        elif isinstance(item, (str, int, float)):
            result.append({"id": str(item)[:160]})
    return result


def _diagnostics_payload() -> dict[str, Any]:
    disk = shutil.disk_usage(settings.data_dir)
    try:
        ai_health = get_ai_engine().health()
    except Exception as exc:
        ai_health = {"status": "failed", "error": type(exc).__name__, "models": []}
    providers = ai_health.get("providers")
    if not isinstance(providers, list):
        runtime = ai_health.get("runtime")
        providers = [runtime] if runtime else []
    return {
        "schema": 1,
        "scope": "M2A_UI_DIAGNOSTICS",
        "release_status": "RELEASE_BLOCKED",
        "application": {
            "name": settings.app_name,
            "version": settings.app_version,
            "build_id": settings.build_id,
            "host_policy": "localhost_only",
        },
        "system": {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "cpu_logical": os.cpu_count(),
            "gpu": "not_detected_or_not_configured",
        },
        "runtime": {
            "status": ai_health.get("status", "unknown"),
            "providers": [str(item)[:160] for item in providers[:20]],
            "models": _sanitize_models(ai_health.get("models")),
        },
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "privacy": {
            "image_content_included": False,
            "secrets_included": False,
            "absolute_paths_included": False,
            "cloud_upload_default": False,
        },
    }


def register_m2a_routes(app: FastAPI, store: ProjectStore) -> None:
    """Install the authorised M2A-only persistence and diagnostics surface once."""
    if getattr(app.state, "m2a_routes_installed", False):
        return
    app.state.m2a_routes_installed = True

    original_set_preset = store.set_preset

    def guarded_set_preset(project_id: str, name: str, module: str, parameters: dict):
        normalized_module = module.strip().lower()
        if normalized_module not in _ALLOWED_PRESET_MODULES:
            raise ProjectStoreError("Модуль профиля не разрешён в M2A")
        _bounded_json(parameters)
        return original_set_preset(project_id, name, normalized_module, parameters)

    store.set_preset = guarded_set_preset

    @app.get("/api/m2a/projects/{project_id}/workspace")
    def get_m2a_workspace(project_id: str) -> dict[str, Any]:
        try:
            project = store.get(project_id)
            return {"project_id": project.id, "workspace": _workspace_view(project.workspace)}
        except (ValueError, ProjectStoreError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/m2a/projects/{project_id}/workspace/{section}")
    def put_m2a_workspace(project_id: str, section: str, payload: M2AWorkspacePayload) -> dict[str, Any]:
        try:
            project = _write_workspace_section(store, project_id, section, payload.value)
            return {"project": project.model_dump(), "section": section, "status": "saved"}
        except (ValueError, ProjectStoreError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/m2a/projects/{project_id}/presets")
    def put_m2a_preset(project_id: str, payload: M2APresetPayload) -> dict[str, Any]:
        try:
            normalized_module = payload.module.strip().lower()
            if normalized_module not in _ALLOWED_PRESET_MODULES:
                raise ProjectStoreError("Модуль профиля не разрешён в M2A")
            _bounded_json(payload.parameters)
            project = store.set_preset(project_id, payload.name.strip(), normalized_module, payload.parameters)
            return {"project": project.model_dump(), "status": "saved"}
        except (ValueError, ProjectStoreError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/m2a/diagnostics")
    def get_m2a_diagnostics() -> dict[str, Any]:
        return _diagnostics_payload()

    @app.get("/api/m2a/diagnostics-report")
    def download_m2a_diagnostics() -> JSONResponse:
        return JSONResponse(
            _diagnostics_payload(),
            headers={"Content-Disposition": 'attachment; filename="ImageLab-M2A-diagnostics.json"'},
        )
