from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.entry import app
from app.models import PresetRequest

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def text(path: str) -> str:
    return (ROOT / path).read_text("utf-8")


def m2a_source() -> str:
    return "".join(path.read_text("utf-8") for path in sorted((ROOT / "app/static/m2a-ui-parts").glob("*.js.part")))


def test_entry_serves_m2a_layers_without_inline_script() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert '/static/m2a-ui.css?v=m2a' in body
    assert '/static/m2a-ui.js?v=m2a' in body
    assert '<script>' not in body


def test_m2a_surface_contains_approved_navigation_and_controls() -> None:
    js = m2a_source()
    css = text("app/static/m2a-ui.css")
    for module in (
        "projects", "presets", "batch", "background", "color", "palette",
        "dtf", "masters", "logo", "cardlab", "settings",
    ):
        assert f"'{module}'" in js or f'"{module}"' in js
    for marker in (
        "m2a-chain", "m2aResample", "m2aCanvasTop", "m2aRequestedActual",
        "data-preview-mode", "m2aZoomValue", "m2a-mobile-nav",
    ):
        assert marker in js or marker in css
    surface = text("app/static/index.html") + js
    assert 'data-size-unit' not in surface
    assert 'value="cm"' not in surface
    assert 'value="in"' not in surface
    assert 'value="inch"' not in surface


def test_active_project_is_not_hardwired_to_ts001() -> None:
    base_js = text("app/static/app.js")
    m2a_js = m2a_source()
    assert "const PROJECT_ID = 'TS-001'" in base_js
    assert "storage.get('imagelab.activeProjectId') || PROJECT_ID" in m2a_js
    assert "const memoryStorage = new Map()" in m2a_js
    assert "try { window.localStorage.setItem" in m2a_js
    assert "input.replace(from, to)" in m2a_js
    assert "PROJECT_ID=id" not in m2a_js


def test_approved_preset_modules_are_accepted_and_unknown_is_rejected() -> None:
    approved = {
        "improve", "extract", "selection", "background", "cleanup", "color", "palette",
        "halftone", "vector", "geometry", "dtf", "masters", "logo", "export", "cardlab",
    }
    for module in approved:
        request = PresetRequest(name=f"preset-{module}", module=module, parameters={})
        assert request.module == module
    with pytest.raises(ValidationError):
        PresetRequest(name="bad", module="text-to-image", parameters={})
