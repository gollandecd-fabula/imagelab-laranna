from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_RESERVED_PROJECT_IDS = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}


def sanitize_original_filename(value: str) -> str:
    """Return one display/download filename without path or header control data."""
    raw = str(value or "").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or len(name) > 255:
        raise ValueError("Некорректное имя исходного файла")
    if _CONTROL_CHARACTERS.search(name):
        raise ValueError("Имя исходного файла содержит управляющие символы")
    return name


def validate_asset_identifier(value: str, *, label: str = "файла") -> str:
    if not value.isalnum() or not (8 <= len(value) <= 64):
        raise ValueError(f"Некорректный идентификатор {label}")
    return value


def validate_project_identifier(value: str) -> str:
    """Validate one cross-platform project identifier before any filesystem use."""
    if not value or len(value) > 64 or any(not (ch.isalnum() or ch in {"-", "_"}) for ch in value):
        raise ValueError("Некорректный идентификатор проекта")
    if value.upper() in _WINDOWS_RESERVED_PROJECT_IDS:
        raise ValueError("Идентификатор проекта зарезервирован операционной системой")
    return value


class CheckItem(BaseModel):
    code: str
    label: str
    passed: bool
    detail: str | None = None


class AssetRecord(BaseModel):
    id: str
    original_name: str
    stored_name: str
    preview_name: str
    size_bytes: int
    sha256: str
    mime_type: str
    format: str
    width_px: int | None = None
    height_px: int | None = None
    ppi_x: float | None = None
    ppi_y: float | None = None
    ppi_origin: str
    print_width_mm: float | None = None
    print_height_mm: float | None = None
    color_mode: str | None = None
    color_profile: str | None = None
    has_alpha: bool | None = None
    created_at: str
    preview_url: str
    checks: list[CheckItem] = Field(default_factory=list)
    source_asset_id: str | None = None
    operation: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    ai: dict[str, Any] = Field(default_factory=dict)
    download_url: str | None = None

    @field_validator("id", "source_asset_id")
    @classmethod
    def validate_asset_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_asset_identifier(value)

    @field_validator("stored_name", "preview_name")
    @classmethod
    def validate_storage_name(cls, value: str) -> str:
        if not value or len(value) > 160 or Path(value).name != value or any(ch in value for ch in ("/", "\\", "\x00")):
            raise ValueError("Некорректное имя хранимого файла")
        return value

    @field_validator("original_name")
    @classmethod
    def validate_original_name(cls, value: str) -> str:
        return sanitize_original_filename(value)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
            raise ValueError("Некорректный SHA-256 файла")
        return value.lower()

    @field_validator("size_bytes")
    @classmethod
    def validate_size(cls, value: int) -> int:
        if value < 0 or value > 1_000_000_000:
            raise ValueError("Некорректный размер файла")
        return value

    @field_validator("ppi_x", "ppi_y", "print_width_mm", "print_height_mm")
    @classmethod
    def validate_optional_number(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError("Некорректное числовое значение метаданных")
        return value


class ProjectRecord(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    assets: list[AssetRecord] = Field(default_factory=list)
    workspace: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        return validate_project_identifier(value)


class ProjectCreateRequest(BaseModel):
    title: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value or len(value) > 160:
            raise ValueError("Название проекта должно содержать от 1 до 160 символов")
        return value


class ProjectRenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 160:
            raise ValueError("Название проекта должно содержать от 1 до 160 символов")
        return value


class PresetRequest(BaseModel):
    name: str
    module: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 80:
            raise ValueError("Название профиля должно содержать от 1 до 80 символов")
        return value

    @field_validator("module")
    @classmethod
    def validate_module(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {"improve", "extract", "selection", "cleanup", "halftone", "vector", "geometry", "export"}
        if value not in allowed:
            raise ValueError("Неизвестный модуль профиля")
        return value


class BatchProcessRequest(BaseModel):
    asset_ids: list[str]
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, values: list[str]) -> list[str]:
        if not values or len(values) > 20:
            raise ValueError("Пакет должен содержать от 1 до 20 файлов")
        if len(set(values)) != len(values):
            raise ValueError("Пакет содержит повторяющиеся файлы")
        for value in values:
            validate_asset_identifier(value)
        return values

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {"enhance", "reconstruct", "color", "select", "background", "cleanup", "geometry", "halftone", "vectorize", "master_clean", "master_card", "master_dtf", "logo"}
        if value not in allowed:
            raise ValueError("Операция недоступна для пакетной обработки")
        return value


class ActiveAssetRequest(BaseModel):
    asset_id: str

    @field_validator("asset_id")
    @classmethod
    def validate_active_asset_id(cls, value: str) -> str:
        return validate_asset_identifier(value, label="активного файла")


class UploadResponse(BaseModel):
    project: ProjectRecord
    uploaded: list[AssetRecord]


class ProcessRequest(BaseModel):
    asset_id: str
    operation: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        return validate_asset_identifier(value)

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        value = value.strip().lower()
        if not value or len(value) > 64:
            raise ValueError("Некорректная операция")
        return value


class CleanupPipelineRequest(BaseModel):
    asset_id: str
    remove_background: bool = True
    background_parameters: dict[str, Any] = Field(default_factory=dict)
    run_cleanup: bool = True
    cleanup_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        return validate_asset_identifier(value)


class ProcessResponse(BaseModel):
    project: ProjectRecord
    source_asset_id: str
    result: AssetRecord
    attempts: list[AssetRecord] = Field(default_factory=list)
    repair: dict[str, Any] = Field(default_factory=dict)
    learning: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    asset_id: str
    format: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        return validate_asset_identifier(value)

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"PNG", "PNG_DTF", "JPG", "WEBP", "SVG"}:
            raise ValueError("Неподдерживаемый формат экспорта")
        return normalized


class ExportResponse(BaseModel):
    project: ProjectRecord
    source_asset_id: str
    result: AssetRecord
    learning: dict[str, Any] = Field(default_factory=dict)


class QaResponse(BaseModel):
    project_id: str
    asset_id: str | None = None
    overall_passed: bool
    checks: list[CheckItem] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ProjectReportResponse(BaseModel):
    project_id: str
    title: str
    assets_total: int
    generated_total: int
    formats: dict[str, int] = Field(default_factory=dict)
    operations: dict[str, int] = Field(default_factory=dict)
    latest_asset_id: str | None = None
    qa: QaResponse
    ai_summary: dict[str, Any] = Field(default_factory=dict)


class AIFeedbackRequest(BaseModel):
    module: str
    asset_id: str | None = None
    accepted: bool
    features: list[float]
    correction_asset_id: str | None = None
    note: str = ""
    operation: str | None = None
    quality_score: float | None = None
    evidence_codes: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AITrainRequest(BaseModel):
    module: str


class AIRollbackRequest(BaseModel):
    module: str
