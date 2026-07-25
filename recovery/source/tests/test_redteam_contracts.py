from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from release_gate.finalize_unit_matrix import EXPECTED

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_health_scope_is_derived_from_exact_build_identity() -> None:
    payload = client.get("/api/health").json()
    assert payload["scope"] == f"IMAGELAB_{settings.build_id}"
    assert payload["version"] == settings.app_version
    assert payload["build_id"] == settings.build_id


def test_missing_project_rename_and_preset_are_fail_closed() -> None:
    project_id = "MISSING-REDTEAM-001"
    path = settings.project_dir / f"{project_id}.json"
    path.unlink(missing_ok=True)
    rename = client.patch(
        f"/api/projects/{project_id}/title", json={"title": "Не создавать"}
    )
    preset = client.put(
        f"/api/projects/{project_id}/presets",
        json={"name": "X", "module": "cleanup", "parameters": {}},
    )
    assert rename.status_code == 404
    assert preset.status_code == 404
    assert not path.exists()


def test_check_only_diverts_every_frontend_mutation() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text("utf-8")
    js = (ROOT / "app" / "static" / "app.js").read_text("utf-8")
    assert "Автопараметры" in html
    assert "Полный автомат" not in html + js
    assert "Только проверка" in html
    for function_name in (
        "processSelected",
        "applyCleanupFlow",
        "exportSelected",
    ):
        start = js.index(f"async function {function_name}")
        body = js[start : start + 240]
        assert "divertCheckOnly" in body
    clear_handler = js[js.index("$('#clearButton').addEventListener") :]
    assert "divertCheckOnly('Очистка проекта')" in clear_handler[:350]
    assert "/batch-process" in (ROOT / "app" / "main.py").read_text("utf-8")


def test_ai_autoparams_cannot_overwrite_explicit_halftone_values() -> None:
    source = (ROOT / "app" / "services" / "image_processing.py").read_text(
        "utf-8"
    )
    halftone = source[
        source.index('if normalized == "halftone"') : source.index(
            'if normalized == "vectorize"'
        )
    ]
    for key in ("raster", "size_mm", "density"):
        assert f'if not _provided(params.get("{key}"))' in halftone


def test_exact_twenty_seven_file_release_matrix_is_fail_closed() -> None:
    assert len(EXPECTED) == 27
    assert EXPECTED["upload-surface-hardening"] == (
        "tests/test_upload_surface_hardening.py"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "zero-trust-release.yml"
    ).read_text("utf-8")
    assert "ubuntu-latest" not in workflow
    assert "windows-latest" not in workflow
    assert "python-version: '3.13.14'" in workflow
    for case_id, test_file in EXPECTED.items():
        expected_line = f"          - {{ id: {case_id}, file: {test_file} }}"
        assert workflow.splitlines().count(expected_line) == 1
