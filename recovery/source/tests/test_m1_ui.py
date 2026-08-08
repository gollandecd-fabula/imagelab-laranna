from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_dark_sidebar_structure_is_present() -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'class="sidebar"' in html
    assert 'class="workspace"' in html
    assert 'class="info-sidebar"' in html
    for module in ["upload", "improve", "extract", "selection", "cleanup", "halftone", "vector", "geometry", "export"]:
        assert f'data-module="{module}"' in html
        assert f'data-pane="{module}"' in html
    assert "Достать принт" in html
    assert "Извлечение принта с изделия" in html
    assert "ВАРИАНТ 2" not in html


def test_dark_interface_controls_are_real_and_not_placeholders() -> None:
    html = client.get("/").text
    expected = [
        'id="applyExtractPrint"',
        'id="extractSensitivity"',
        'id="extractRegionControls"',
        'id="extractPerspectiveEnabled"',
        'id="applyCleanup"',
        'id="applyHalftone"',
        'id="applyVectorize"',
        'id="applyGeometry"',
        'id="applyExport"',
    ]
    for marker in expected:
        assert marker in html
    assert "будет доступ" not in html.lower()
    assert "placeholder" not in html.lower()


def test_frontend_wires_print_extraction_operation() -> None:
    script = client.get("/static/app.js?v=0.7.0-m1b-dark-sidebar")
    assert script.status_code == 200
    js = script.text
    assert "extract_print" in js
    assert "applyExtractPrint" in js
    assert "[data-extract-mode]" in js
    assert "processSelected('extract_print'" in js


def test_ai_controls_are_present_in_every_section() -> None:
    html = client.get("/").text
    for module in ["upload", "improve", "extract", "selection", "cleanup", "halftone", "vector", "geometry", "export"]:
        assert f'data-ai-scope="{module}"' in html
        assert f'data-ai-analyze="{module}"' in html
    for marker in [
        'id="aiHealthChip"', 'id="aiContent"', 'id="aiAnalyzeSelected"',
        'id="aiExplainSelected"', 'id="aiAccept"', 'id="aiReject"',
        'id="aiTrainButton"', 'id="aiRollbackButton"',
        'id="halftoneAiAuto"', 'id="vectorAiAuto"', 'id="geometryAiCrop"', 'id="exportAiAuto"',
    ]:
        assert marker in html


def test_frontend_wires_ai_runtime_feedback_training_and_rollback() -> None:
    js = client.get("/static/app.js?v=1.0.0-ai-m6").text
    for marker in [
        "/api/ai/health", "/api/ai/feedback", "/api/ai/train", "/api/ai/rollback",
        "/ai/analyze", "/ai/explain", "collectAIRecords", "renderAI",
    ]:
        assert marker in js
