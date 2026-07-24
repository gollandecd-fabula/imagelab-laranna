from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    app_name: str = "ImageLab by LarannA"
    app_version: str = "1.4.5-recovery-candidate"
    build_id: str = "REC-RT8-M6-20260724-02"
    install_id: str = os.environ.get("IMAGELAB_INSTALL_ID", "source-tree").strip() or "source-tree"
    host: str = "127.0.0.1"
    port: int = 8765
    default_project_id: str = "TS-001"
    workspace_ppi: float = 300.0
    max_upload_bytes: int = 50 * 1024 * 1024
    max_image_pixels: int = 120_000_000
    max_processing_pixels: int = 40_000_000
    max_vector_pixels: int = 4_000_000
    max_halftone_cells: int = 500_000
    data_dir: Path = _env_path("IMAGELAB_DATA_DIR", BASE_DIR / "data")
    upload_dir: Path = data_dir / "uploads"
    preview_dir: Path = data_dir / "previews"
    project_dir: Path = data_dir / "projects"
    static_dir: Path = _env_path("IMAGELAB_STATIC_DIR", BASE_DIR / "app" / "static")
    ai_model_dir: Path = _env_path("IMAGELAB_AI_MODEL_DIR", BASE_DIR / "models")
    ai_feedback_dir: Path = data_dir / "ai_feedback"
    ai_audit_dir: Path = data_dir / "ai_audit"
    ai_promoted_model_dir: Path = data_dir / "ai_models"


settings = Settings()
