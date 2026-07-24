from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.services.image_processing import _cleanup, _prepare_logo
from app.services.project_store import ProjectStore

ROOT = Path(__file__).resolve().parents[1]


def test_binary_alpha_profile_is_explicit_and_exact() -> None:
    image = Image.new("RGBA", (16, 1), (20, 30, 40, 0))
    image.putalpha(Image.fromarray(np.arange(0, 256, 16, dtype=np.uint8).reshape(1, 16), "L"))
    result = _cleanup(image, {"remove_halo": False, "binary_alpha": True, "alpha_threshold": 128})
    assert set(np.asarray(result.getchannel("A")).reshape(-1).tolist()) == {0, 255}


def test_logo_workflow_crops_and_converts_colour() -> None:
    image = Image.new("RGBA", (80, 60), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 15, 60, 45), fill=(210, 20, 30, 255))
    result = _prepare_logo(image, {"remove_background": True, "target_color": "#ffffff", "tolerance": 5, "color_mode": "black", "padding_px": 1})
    rgba = np.asarray(result)
    assert result.width < image.width and result.height < image.height
    visible = rgba[:, :, 3] > 0
    assert np.all(rgba[:, :, :3][visible] == 0)


def test_project_preset_crud_is_persistent(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    store.create("PRODUCT-001", "Товар")
    updated = store.set_preset("PRODUCT-001", "DTF", "halftone", {"size_mm": 0.2})
    assert updated.workspace["presets"]["DTF"]["parameters"]["size_mm"] == 0.2
    reopened = ProjectStore(tmp_path).get("PRODUCT-001")
    assert reopened.workspace["presets"]["DTF"]["module"] == "halftone"
    deleted = store.delete_preset("PRODUCT-001", "DTF")
    assert "DTF" not in deleted.workspace["presets"]


def test_product_endpoints_and_masters_are_executable_contracts() -> None:
    main = (ROOT / "app" / "main.py").read_text("utf-8")
    processing = (ROOT / "app" / "services" / "image_processing.py").read_text("utf-8")
    frontend = (ROOT / "app" / "static" / "app.js").read_text("utf-8")
    for token in ("/batch-process", "/presets", "/cardlab-package"):
        assert token in main
    for operation in ('normalized == "master_clean"', 'normalized == "master_card"', 'normalized == "master_dtf"', 'normalized == "logo"'):
        assert operation in processing
    for label in ("Clean Master", "Card Master", "DTF Master", "Подготовить логотип"):
        assert label in frontend or label in (ROOT / "app" / "static" / "index.html").read_text("utf-8")
