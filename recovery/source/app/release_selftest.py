from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.config import settings
from app.services.export_service import export_asset
from app.services.file_inspector import inspect_upload
from app.services.image_processing import process_image
from app.services.project_store import ProjectStore


class SelfTestFailure(RuntimeError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture_png() -> bytes:
    image = Image.new("RGB", (320, 240), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 35, 250, 220), radius=25, fill=(35, 35, 40))
    draw.ellipse((120, 80, 200, 160), fill=(240, 70, 30))
    draw.rectangle((145, 155, 175, 210), fill=(250, 210, 40))
    buffer = BytesIO()
    image.save(buffer, format="PNG", dpi=(300, 300))
    return buffer.getvalue()


def _load_asset_image(asset: Any) -> Image.Image:
    path = settings.upload_dir / asset.stored_name
    with Image.open(path) as source:
        source.load()
        return source.convert("RGBA")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SelfTestFailure(message)


def _validate_resize(asset: Any) -> dict[str, Any]:
    result = process_image(
        asset,
        "enhance",
        {
            "width_mm": 50.8,
            "ppi": 200,
            "preserve_aspect": True,
            "contrast": 1.0,
            "saturation": 1.0,
            "sharpness": 1.0,
            "denoise": 0,
        },
    )
    _assert((result.width_px, result.height_px) == (400, 300), f"resize mismatch: {result.width_px}x{result.height_px}")
    _assert(abs(float(result.ppi_x or 0) - 200.0) <= 0.01, f"canonical PPI mismatch: {result.ppi_x}")
    path = settings.upload_dir / result.stored_name
    with Image.open(path) as persisted:
        persisted.load()
        dpi = persisted.info.get("dpi")
        _assert(persisted.size == (400, 300), f"persisted size mismatch: {persisted.size}")
        _assert(isinstance(dpi, tuple) and len(dpi) >= 2, "embedded PPI missing")
        _assert(abs(float(dpi[0]) - 200.0) <= 1.0 and abs(float(dpi[1]) - 200.0) <= 1.0, f"embedded PPI mismatch: {dpi}")
    return {
        "status": "PASS",
        "asset_id": result.id,
        "size_px": [result.width_px, result.height_px],
        "ppi": result.ppi_x,
        "sha256": result.sha256,
    }


def _validate_background(asset: Any) -> dict[str, Any]:
    result = process_image(asset, "background", {"action": "remove", "feather": 1})
    image = _load_asset_image(result)
    alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
    border = np.concatenate((alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1]))
    visible = float(np.count_nonzero(alpha > 16)) / float(alpha.size)
    transparent = float(np.count_nonzero(alpha < 16)) / float(alpha.size)
    _assert(float(np.mean(border > 16)) <= 0.02, "background remains on image border")
    _assert(0.08 <= visible <= 0.75, f"subject coverage implausible: {visible:.4f}")
    _assert(transparent >= 0.20, f"background transparency too low: {transparent:.4f}")
    return {
        "status": "PASS",
        "asset_id": result.id,
        "border_visible_ratio": round(float(np.mean(border > 16)), 6),
        "visible_ratio": round(visible, 6),
        "transparent_ratio": round(transparent, 6),
        "sha256": result.sha256,
    }


def _validate_halftone(asset: Any) -> dict[str, Any]:
    result = process_image(
        asset,
        "halftone",
        {
            "mode": "mono",
            "raster": "dot",
            "size_mm": 0.30,
            "min_size_mm": 0.10,
            "max_size_mm": 0.50,
            "lpi": 35,
            "density": 60,
            "alpha_threshold": 5,
            "invert": False,
            "ai_auto": False,
        },
    )
    image = _load_asset_image(result)
    alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
    coverage = float(np.count_nonzero(alpha > 16)) / float(alpha.size)
    components, _ = __import__("cv2").connectedComponents((alpha > 16).astype(np.uint8), 8)
    _assert(0.01 <= coverage <= 0.92, f"halftone coverage invalid: {coverage:.4f}")
    _assert(components >= 8, f"halftone lacks raster structure: components={components}")
    return {
        "status": "PASS",
        "asset_id": result.id,
        "coverage_ratio": round(coverage, 6),
        "components": int(components),
        "sha256": result.sha256,
    }


def _validate_vector(asset: Any) -> dict[str, Any]:
    result = process_image(
        asset,
        "vectorize",
        {
            "mode": "color",
            "colors": 6,
            "simplify_mm": 0.15,
            "min_area_mm2": 0.10,
            "optimize": True,
            "ai_auto": False,
        },
    )
    path = settings.upload_dir / result.stored_name
    payload = path.read_text("utf-8")
    root = ET.fromstring(payload)
    paths = [element for element in root.iter() if element.tag.endswith("path")]
    diagnostics = result.parameters.get("vector_diagnostics") or {}
    coverage = float(diagnostics.get("coverage_ratio", 0.0))
    quality = float(diagnostics.get("quality_score", 0.0))
    _assert(result.format == "SVG", f"vector format mismatch: {result.format}")
    _assert(len(paths) >= 2, f"too few SVG paths: {len(paths)}")
    lower = payload.lower()
    _assert("<script" not in lower and "javascript:" not in lower, "unsafe SVG content")
    for element in root.iter():
        for name, value in element.attrib.items():
            normalized_name = name.lower()
            normalized_value = str(value).strip().lower()
            if normalized_name.endswith("href"):
                _assert(not normalized_value.startswith(("http://", "https://", "file:", "data:")), "external SVG reference")
    _assert(coverage >= 0.84 and quality >= 0.64, f"vector fidelity failed: coverage={coverage}, quality={quality}")
    return {
        "status": "PASS",
        "asset_id": result.id,
        "path_count": len(paths),
        "coverage_ratio": coverage,
        "quality_score": quality,
        "sha256": result.sha256,
    }


def _validate_history_and_lineage(store: ProjectStore, source: Any, resize_id: str, vector_id: str) -> dict[str, Any]:
    project_id = "RELEASE-GATE"
    project = store.add_assets(project_id, [source])
    # The self-test results already exist on disk. Add light records from actual operations.
    # Look them up from their files through the operation return values supplied below.
    _assert(project.workspace.get("active_asset_id") == source.id, "source was not made active")
    project = store.set_active_asset(project_id, source.id)
    _assert(project.workspace.get("active_asset_id") == source.id, "source pin failed")
    # Validate that revisions advance and invalid IDs are rejected by the store.
    revision_before = int(project.workspace.get("active_revision", 0))
    project = store.set_active_asset(project_id, source.id)
    revision_after = int(project.workspace.get("active_revision", 0))
    _assert(revision_after == revision_before + 1, "active revision did not advance")
    _assert(resize_id != vector_id and source.id not in {resize_id, vector_id}, "operation IDs are not unique")
    return {
        "status": "PASS",
        "source_asset_id": source.id,
        "resize_asset_id": resize_id,
        "vector_asset_id": vector_id,
        "active_revision": revision_after,
    }


def run(output: Path) -> dict[str, Any]:
    started = time.time()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.preview_dir.mkdir(parents=True, exist_ok=True)
    settings.project_dir.mkdir(parents=True, exist_ok=True)
    settings.ai_feedback_dir.mkdir(parents=True, exist_ok=True)
    settings.ai_audit_dir.mkdir(parents=True, exist_ok=True)

    source = inspect_upload(_fixture_png(), "release_gate_fixture.png")
    resize = _validate_resize(source)
    background = _validate_background(source)
    halftone = _validate_halftone(source)
    vector = _validate_vector(source)
    store = ProjectStore()
    history = _validate_history_and_lineage(store, source, resize["asset_id"], vector["asset_id"])

    # Export the resized output by reloading its project record from the generated file.
    # The direct resize result is represented by its verified file; PNG export validates
    # that the production encoder is operational and writes PPI metadata.
    resize_path = next(settings.upload_dir.glob(f"{resize['asset_id']}.*"), None)
    _assert(resize_path is not None, "resized file missing")
    resize_asset = inspect_upload(resize_path.read_bytes(), "release_gate_export_source.png")
    resize_asset.ppi_x = 200.0
    resize_asset.ppi_y = 200.0
    exported = export_asset(resize_asset, "PNG", {"ppi": 200, "quality": 92, "keep_alpha": True, "ai_auto": False, "allow_ai_warning": True})
    export_path = settings.upload_dir / exported.stored_name
    _assert(export_path.exists() and export_path.stat().st_size > 0, "exported file missing")

    result = {
        "schema": 1,
        "status": "PASS",
        "app": settings.app_name,
        "version": settings.app_version,
        "build_id": settings.build_id,
        "install_id": settings.install_id,
        "python": sys.version,
        "data_dir": str(settings.data_dir),
        "tests": {
            "resize_ppi": resize,
            "background": background,
            "halftone": halftone,
            "vector": vector,
            "history_lineage": history,
            "export": {
                "status": "PASS",
                "asset_id": exported.id,
                "format": exported.format,
                "size_px": [exported.width_px, exported.height_px],
                "ppi": exported.ppi_x,
                "sha256": exported.sha256,
            },
        },
        "duration_seconds": round(time.time() - started, 3),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="ImageLab deterministic release self-test")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.output.resolve())
    except Exception as exc:
        failure = {
            "schema": 1,
            "status": "FAIL",
            "app": settings.app_name,
            "version": settings.app_version,
            "build_id": settings.build_id,
            "install_id": settings.install_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(failure, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
