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


def test_runtime_training_and_rollback_routes_are_absent() -> None:
    train = client.post("/api/ai/train", json={"module": "improve"})
    rollback = client.post("/api/ai/rollback", json={"module": "improve"})
    assert train.status_code == 404, train.text
    assert rollback.status_code == 404, rollback.text


def test_continual_learning_records_feedback_without_training(monkeypatch) -> None:
    from types import SimpleNamespace

    import app.services.repair_service as repair_service

    class Feedback:
        def __init__(self) -> None:
            self.rows = [object() for _ in range(7)]
            self.train_calls = 0

        def list(self, module: str):
            return list(self.rows)

        def add(self, module: str, payload: dict) -> None:
            self.rows.append(payload)

        def train(self, module: str):
            self.train_calls += 1
            raise AssertionError("runtime training must never be called under v1.4.4")

    feedback = Feedback()
    engine = SimpleNamespace(feedback=feedback)
    monkeypatch.setattr(repair_service, "get_ai_engine", lambda: engine)
    monkeypatch.setattr(
        repair_service,
        "evaluate_asset_record",
        lambda asset: {
            "passed": True,
            "quality_score": 95.0,
            "defects": [],
            "critical_defects": [],
            "warnings": [],
            "checks": [],
        },
    )
    asset = SimpleNamespace(
        id="SEC006-ASSET",
        ai={"details": {"features": [0.1, 0.2, 0.3]}},
        parameters={},
    )

    result = repair_service.record_continual_learning([asset], "enhance")

    assert result["stored"] == 1
    assert result["dataset_rows"] == 8
    assert result["training"] == {
        "status": "not_triggered",
        "reason": "runtime_training_promotion_forbidden_v1_4_4",
    }
    assert feedback.train_calls == 0
