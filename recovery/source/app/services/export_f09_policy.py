from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms

from app.config import settings
from app.models import AssetRecord

EXPORT_FORMATS = {"PNG", "PNG_DTF", "JPG", "WEBP", "SVG"}

class ExportError(ValueError):
    pass


def _safe_export_stem(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    raw = Path(raw).stem
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "_", raw).strip("._-")
    return safe[:100] or fallback


def _asset_source_path(asset: AssetRecord) -> Path:
    path = (settings.upload_dir / asset.stored_name).resolve()
    try:
        path.relative_to(settings.upload_dir.resolve())
    except ValueError as exc:
        raise ExportError("Некорректный путь исходного файла") from exc
    if not path.exists():
        raise ExportError("Исходный файл не найден")
    return path


def _load_image(asset: AssetRecord) -> tuple[Image.Image, bytes | None]:
    path = _asset_source_path(asset)
    if asset.format == "SVG":
        raise ExportError("Для растрового экспорта выберите растровый файл или сначала выполните векторизацию")
    try:
        with Image.open(path) as source:
            source.load()
            icc = source.info.get("icc_profile")
            return source.convert("RGBA"), bytes(icc) if isinstance(icc, (bytes, bytearray)) else None
    except OSError as exc:
        raise ExportError("Исходный файл повреждён") from exc


def _finite_float(value: Any, label: str, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ExportError(f"{label} должно быть числом") from exc
    if not math.isfinite(parsed) or not low <= parsed <= high:
        raise ExportError(f"{label} должно быть от {low:g} до {high:g}")
    return parsed


def _choice(value: Any, *, label: str, allowed: set[str], default: str) -> str:
    normalized = str(value if value is not None else default).strip().lower()
    if normalized not in allowed:
        raise ExportError(f"{label}: допустимо {', '.join(sorted(allowed))}")
    return normalized


def _safe_export_folder(value: Any) -> Path:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return Path()
    candidate = Path(raw)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ExportError("Папка экспорта должна быть относительной и не содержать переходов '..'")
    safe_parts: list[str] = []
    for part in candidate.parts:
        safe = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "_", part).strip("._-")
        if not safe or safe != part or len(safe) > 80:
            raise ExportError("Папка экспорта содержит недопустимое имя")
        safe_parts.append(safe)
    return Path(*safe_parts)


def _export_root() -> Path:
    root = (settings.data_dir / "exports").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _target_paths(folder: Path, filename: str) -> tuple[Path, Path, str, str]:
    root = _export_root()
    target_dir = (root / folder).resolve()
    try:
        target_dir.relative_to(root)
    except ValueError as exc:
        raise ExportError("Папка экспорта выходит за пределы разрешённого каталога") from exc
    target_dir.mkdir(parents=True, exist_ok=True)
    output = (target_dir / filename).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise ExportError("Некорректный путь результата экспорта") from exc
    manifest = output.with_name(output.name + ".manifest.json")
    return output, manifest, output.relative_to(root).as_posix(), manifest.relative_to(root).as_posix()


def _required_layers_pass(qa: dict[str, Any]) -> bool:
    layers = qa.get("layers") if isinstance(qa, dict) else None
    if not isinstance(layers, dict):
        return False
    required = [layer for layer in layers.values() if isinstance(layer, dict) and layer.get("required") is True]
    return bool(required) and all(layer.get("status") == "PASS" for layer in required)


def _pre_create_source_gate(qa: dict[str, Any]) -> dict[str, Any]:
    """Bind F09 to independent QA while keeping model provenance non-authoritative.

    QA-9.1 intentionally keeps processing/model evidence separate from deterministic
    file and visual oracles. For F09, absence of a prior AI model record on an otherwise
    valid uploaded source cannot become the sole reason to block an encoder operation.
    Every other defect in every required layer remains fail-closed.
    """
    layers = qa.get("layers") if isinstance(qa, dict) else None
    if not isinstance(layers, dict):
        return {"passed": False, "layers": {}, "reason": "qa_layers_missing"}
    effective: dict[str, Any] = {}
    passed = True
    for name, layer in layers.items():
        if not isinstance(layer, dict):
            continue
        required = layer.get("required") is True
        defects = list(layer.get("defects", []))
        advisory = [code for code in defects if name == "technical" and code == "ai_evidence"]
        blocking = [code for code in defects if code not in advisory]
        layer_passed = (not required) or not blocking
        if required and not layer_passed:
            passed = False
        effective[name] = {
            "required": required,
            "raw_status": str(layer.get("status", "UNVERIFIED")),
            "effective_status": "PASS" if layer_passed else "FAIL",
            "blocking_defects": blocking,
            "advisory_nonblocking": advisory,
            "oracles": list(layer.get("oracles", [])),
        }
    return {"passed": passed and bool(effective), "layers": effective, "reason": "independent_qa_layers"}


def _qa_summary(qa: dict[str, Any]) -> dict[str, Any]:
    layers = qa.get("layers", {}) if isinstance(qa, dict) else {}
    return {
        "passed": bool(qa.get("passed")) if isinstance(qa, dict) else False,
        "quality_score": qa.get("quality_score") if isinstance(qa, dict) else None,
        "layers": {
            name: {
                "required": bool(layer.get("required")),
                "status": str(layer.get("status", "UNVERIFIED")),
                "defects": list(layer.get("defects", [])),
                "oracles": list(layer.get("oracles", [])),
            }
            for name, layer in layers.items()
            if isinstance(layer, dict)
        },
    }


def _apply_logo_variant(image: Image.Image, mode: str) -> Image.Image:
    if mode == "original":
        return image
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    visible = rgba[:, :, 3] > 0
    if not np.any(visible):
        raise ExportError("Logo variant невозможен: видимая область пуста")
    value = 0 if mode == "black" else 96
    rgba[:, :, :3][visible] = value
    return Image.fromarray(rgba, "RGBA")


def _srgb_profile_bytes() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _apply_color_profile(image: Image.Image, source_icc: bytes | None, policy: str) -> tuple[Image.Image, bytes | None, str]:
    if policy == "strip":
        return image, None, "stripped"
    if policy == "preserve":
        return image, source_icc, "preserved" if source_icc else "source_untagged"
    target_icc = _srgb_profile_bytes()
    if source_icc:
        try:
            source_profile = ImageCms.ImageCmsProfile(io.BytesIO(source_icc))
            target_profile = ImageCms.ImageCmsProfile(io.BytesIO(target_icc))
            alpha = image.getchannel("A")
            converted = ImageCms.profileToProfile(image.convert("RGB"), source_profile, target_profile, outputMode="RGB")
            converted.putalpha(alpha)
            return converted, target_icc, "converted_to_srgb"
        except Exception as exc:
            raise ExportError("Не удалось безопасно преобразовать цветовой профиль в sRGB") from exc
    return image, target_icc, "untagged_assumed_srgb_and_tagged"


def _export_preflight(image: Image.Image, normalized: str, *, transparency: str, logo_variant: str) -> dict[str, Any]:
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
    visible_ratio = float(np.mean(alpha > 16))
    has_transparency = bool(np.any(alpha < 255))
    checks = {
        "nonempty_dimensions": image.width > 0 and image.height > 0,
        "visible_content": visible_ratio > 0.001,
        "format_transparency_compatible": not (normalized == "JPG" and transparency == "preserve"),
        "svg_logo_variant_compatible": not (normalized == "SVG" and logo_variant != "original"),
    }
    if normalized == "PNG_DTF":
        checks.update({
            "dtf_requires_transparency_policy": transparency == "preserve",
            "dtf_transparent_background": has_transparency and visible_ratio <= 0.985,
            "dtf_visible_print_area": 0.001 <= visible_ratio <= 0.985,
        })
    passed = all(checks.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "checks": checks,
        "visible_ratio": round(visible_ratio, 8),
        "source_has_transparency": has_transparency,
        "oracle": "deterministic_export_preflight",
    }

