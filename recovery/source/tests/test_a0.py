from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from app.services.project_store import ProjectStore


client = TestClient(app)
PROJECT = "TEST-A0"


def make_png() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGBA", (100, 200), (20, 80, 180, 128))
    image.save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def cleanup() -> None:
    response = client.delete(f"/api/projects/{PROJECT}/assets")
    assert response.status_code == 200
    project_path = settings.project_dir / f"{PROJECT}.json"
    if project_path.exists():
        project_path.unlink()


def test_health_and_dark_sidebar_ui() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["scope"] == "IUL_M6_UPDATE_LOCK_CANDIDATE"
    assert health.json()["ai"]["status"] == "ready"

    page = client.get("/")
    assert page.status_code == 200
    assert "ImageLab by LarannA" in page.text
    assert "Достать принт" in page.text
    assert 'class="sidebar"' in page.text
    assert 'class="info-sidebar"' in page.text
    assert "ZIP проекта" in page.text


def test_png_upload_metadata_preview_and_persistence() -> None:
    cleanup()
    response = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("sample.png", make_png(), "image/png"))])
    assert response.status_code == 200, response.text
    asset = response.json()["uploaded"][0]
    assert asset["format"] == "PNG"
    assert asset["width_px"] == 100
    assert asset["height_px"] == 200
    assert 299 <= asset["ppi_x"] <= 301
    assert 8.3 <= asset["print_width_mm"] <= 8.6
    assert 16.7 <= asset["print_height_mm"] <= 17.1
    assert asset["has_alpha"] is True
    assert all(check["passed"] for check in asset["checks"])

    preview = client.get(asset["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")

    reloaded = ProjectStore(settings.project_dir).get_or_create(PROJECT)
    assert len(reloaded.assets) == 1
    assert reloaded.assets[0].sha256 == asset["sha256"]
    cleanup()


def test_safe_svg_is_accepted_and_malicious_svg_is_rejected() -> None:
    cleanup()
    safe_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm" viewBox="0 0 400 200"><rect width="400" height="200" fill="#123456"/></svg>'
    accepted = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("safe.svg", safe_svg, "image/svg+xml"))])
    assert accepted.status_code == 200, accepted.text
    asset = accepted.json()["uploaded"][0]
    assert asset["format"] == "SVG"
    assert asset["print_width_mm"] == 40.0
    assert asset["print_height_mm"] == 20.0
    preview = client.get(asset["preview_url"])
    assert preview.status_code == 200
    assert "sandbox" in preview.headers.get("content-security-policy", "")

    malicious = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    rejected = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("bad.svg", malicious, "image/svg+xml"))])
    assert rejected.status_code == 422
    assert "Небезопасный SVG" in rejected.json()["detail"]
    cleanup()


def test_invalid_and_empty_files_are_rejected() -> None:
    cleanup()
    bad = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("fake.png", b"not an image", "image/png"))])
    assert bad.status_code == 422
    empty = client.post(f"/api/projects/{PROJECT}/upload", files=[("files", ("empty.png", b"", "image/png"))])
    assert empty.status_code == 422
    cleanup()


def test_project_id_path_traversal_is_rejected() -> None:
    response = client.get("/api/projects/..%2Fescape")
    assert response.status_code in {400, 404}
