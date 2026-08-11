from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.entry import app

client = TestClient(app)


def _project_id() -> str:
    return f"M2A-CLOSURE-{uuid.uuid4().hex[:12]}"


def _cleanup(project_id: str) -> None:
    try:
        client.delete(f"/api/projects/{project_id}/assets")
    except Exception:
        pass
    path = settings.project_dir / f"{project_id}.json"
    path.unlink(missing_ok=True)
    path.with_suffix(".lock").unlink(missing_ok=True)


def test_preset_module_enum_rejects_unknown_without_mutating_project() -> None:
    project_id = _project_id()
    try:
        created = client.post(f"/api/projects/{project_id}", json={"title": "closure enum"})
        assert created.status_code == 200, created.text

        allowed = client.put(
            f"/api/m2a/projects/{project_id}/presets",
            json={"name": "safe", "module": "GEOMETRY", "parameters": {"qa_policy": "mandatory"}},
        )
        assert allowed.status_code == 200, allowed.text
        presets_before = allowed.json()["project"]["workspace"]["presets"]
        assert presets_before["safe"]["module"] == "geometry"

        rejected = client.put(
            f"/api/m2a/projects/{project_id}/presets",
            json={"name": "forbidden", "module": "model-manager", "parameters": {}},
        )
        assert rejected.status_code == 422, rejected.text
        assert "Модуль профиля не разрешён" in rejected.text

        current = client.get(f"/api/projects/{project_id}")
        assert current.status_code == 200, current.text
        assert current.json()["workspace"]["presets"] == presets_before
        assert "forbidden" not in current.json()["workspace"]["presets"]
    finally:
        _cleanup(project_id)
