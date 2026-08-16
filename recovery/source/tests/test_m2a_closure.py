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


# v1.4.4 F01 Improve: advisory Restore recommendation must never become a
# hidden restoration mutation.
def test_f01_improve_is_conservative_and_restore_is_advisory_only(monkeypatch) -> None:
    import io
    import numpy as np
    from PIL import Image
    from app.config import settings
    from app.services import m2a_processing
    from app.services.file_inspector import inspect_upload

    class AdvisoryEngine:
        def __init__(self, profile: str) -> None:
            self.profile = profile
            self.recommend_calls = 0
            self.restore_calls = 0

        def recommend_restoration(self, image, *, module="improve"):
            self.recommend_calls += 1
            return {
                "task": "restoration_profile",
                "model_id": "test-restoration-profile",
                "model_version": "1",
                "confidence": 0.9,
                "details": {"profile": self.profile, "features": [0.0]},
            }

        def restore(self, *args, **kwargs):
            self.restore_calls += 1
            raise AssertionError("F01 Improve must not call the restoration mutation")

    image = Image.new("RGBA", (24, 18), (0, 0, 0, 0))
    for y in range(2, 16):
        for x in range(3, 21):
            image.putpixel((x, y), ((x * 9) % 255, (y * 13) % 255, ((x + y) * 7) % 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    source = inspect_upload(buffer.getvalue(), "f01-source.png")
    result = None
    engine = AdvisoryEngine("denoise")
    monkeypatch.setattr(m2a_processing, "get_ai_engine", lambda: engine)
    try:
        result = m2a_processing.process_image(
            source,
            "enhance",
            {
                "preset": "custom",
                "brightness": 1.0,
                "contrast": 1.0,
                "saturation": 1.0,
                "sharpness": 1.0,
                "denoise": 0,
                "ai_auto": True,
                "ppi": source.ppi_x or 300,
            },
        )
        assert engine.restore_calls == 0
        assert engine.recommend_calls == 1
        assert result.operation == "enhance"
        advisory = result.ai["improve_advisory"]
        assert advisory["applied_restoration"] is False
        assert advisory["recommend_restore"] is True
        assert advisory["recommended_action"] == "reconstruct"

        with Image.open(settings.upload_dir / source.stored_name) as opened:
            original = np.asarray(opened.convert("RGBA"))
        with Image.open(settings.upload_dir / result.stored_name) as opened:
            improved = np.asarray(opened.convert("RGBA"))
        assert np.array_equal(improved, original)
    finally:
        for asset in (result, source):
            if asset is None:
                continue
            for path in (
                settings.upload_dir / asset.stored_name,
                settings.preview_dir / asset.preview_name,
            ):
                if path.exists():
                    path.unlink()


def test_f01_improve_advisory_can_be_disabled(monkeypatch) -> None:
    import io
    from PIL import Image
    from app.config import settings
    from app.services import m2a_processing
    from app.services.file_inspector import inspect_upload

    class NoRestoreEngine:
        recommend_calls = 0
        restore_calls = 0

        def recommend_restoration(self, image, *, module="improve"):
            self.recommend_calls += 1
            raise AssertionError("disabled advisory must not invoke analysis")

        def restore(self, *args, **kwargs):
            self.restore_calls += 1
            raise AssertionError("F01 Improve must not call restoration")

    image = Image.new("RGBA", (20, 16), (90, 120, 150, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    source = inspect_upload(buffer.getvalue(), "f01-no-ai.png")
    result = None
    engine = NoRestoreEngine()
    monkeypatch.setattr(m2a_processing, "get_ai_engine", lambda: engine)
    try:
        result = m2a_processing.process_image(
            source,
            "enhance",
            {"preset": "custom", "contrast": 1, "saturation": 1, "sharpness": 1, "denoise": 0, "ai_auto": False},
        )
        assert engine.recommend_calls == 0
        assert engine.restore_calls == 0
        assert result.ai["improve_advisory"]["enabled"] is False
        assert result.ai["improve_advisory"]["applied_restoration"] is False
    finally:
        for asset in (result, source):
            if asset is None:
                continue
            for path in (
                settings.upload_dir / asset.stored_name,
                settings.preview_dir / asset.preview_name,
            ):
                if path.exists():
                    path.unlink()


def test_f01_ui_restore_recommendation_never_auto_navigates() -> None:
    from pathlib import Path
    script = (Path(__file__).parents[1] / "app/static/m2a-ui-parts/22-f01-improve-contract.js.part").read_text("utf-8")
    assert "AI-анализ качества" in script
    assert "переход выполняется только вручную" in script
    assert "applied_restoration: false" in script
    assert "primaryButtons.get('restore')?.click()" not in script
