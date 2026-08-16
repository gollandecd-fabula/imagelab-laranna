from __future__ import annotations

from dataclasses import replace
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.config import settings as base_settings
from app.services import export_service, file_inspector, qa_service
from app.services.export_service import ExportError, export_asset
from app.services.file_inspector import inspect_upload


def _runtime_settings(tmp_path: Path):
    return replace(
        base_settings,
        data_dir=tmp_path,
        upload_dir=tmp_path / "uploads",
        preview_dir=tmp_path / "previews",
        project_dir=tmp_path / "projects",
        ai_feedback_dir=tmp_path / "ai_feedback",
        ai_audit_dir=tmp_path / "ai_audit",
        ai_promoted_model_dir=tmp_path / "ai_models",
    )


@pytest.fixture()
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime = _runtime_settings(tmp_path)
    runtime.upload_dir.mkdir(parents=True)
    runtime.preview_dir.mkdir(parents=True)
    monkeypatch.setattr(export_service, "settings", runtime)
    monkeypatch.setattr(file_inspector, "settings", runtime)
    monkeypatch.setattr(qa_service, "settings", runtime)
    return runtime


def _png_source(*, transparent: bool = True) -> bytes:
    image = Image.new("RGBA", (80, 64), (0, 0, 0, 0 if transparent else 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 10, 66, 54), fill=(205, 65, 35, 210 if transparent else 255))
    draw.ellipse((26, 18, 52, 44), fill=(35, 120, 220, 255))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _source_asset(*, transparent: bool = True):
    asset = inspect_upload(_png_source(transparent=transparent), "f09-source.png")
    # Raster source Technical QA requires recorded model evidence; this is provenance,
    # not a processing-engine verdict and does not replace the independent QA layers.
    asset.ai = {"source_evidence": {"model_id": "qa_anomaly", "model_version": "1.0.0"}}
    return asset


def _params(fmt: str, *, folder: str = "Order-001", logo_variant: str = "original") -> dict:
    return {
        "filename": f"f09-{fmt.lower()}",
        "folder": folder,
        "ppi": 300,
        "quality": 92,
        "transparency": "flatten" if fmt == "JPG" else "preserve",
        "color_profile": "srgb",
        "metadata_policy": "minimal",
        "logo_variant": logo_variant,
        "ai_auto": False,
    }


@pytest.mark.parametrize("fmt", ["PNG", "PNG_DTF", "JPG", "WEBP"])
def test_f09_raster_formats_write_controlled_output_manifest_and_binary_reread(isolated_runtime, fmt: str) -> None:
    source = _source_asset(transparent=True)
    result = export_asset(source, fmt, _params(fmt))

    assert result.operation == "export"
    assert result.source_asset_id == source.id
    assert result.parameters["format"] == fmt
    assert result.parameters["input_asset_id"] == source.id
    assert result.parameters["folder"] == "Order-001"
    assert result.parameters["color_profile"] == "srgb"
    assert result.parameters["metadata_policy"] == "minimal"
    assert result.ai["export_contract"]["binary_reread"]["status"] == "PASS"
    assert result.ai["export_contract"]["result_qa"]["effective_gate"]["passed"] is True

    export_root = isolated_runtime.data_dir / "exports"
    output = export_root / result.parameters["export_target"]
    manifest_path = export_root / result.parameters["export_manifest"]
    assert output.is_file() and manifest_path.is_file()
    assert output.read_bytes() == (isolated_runtime.upload_dir / result.stored_name).read_bytes()

    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["source_sha256"] == source.sha256
    assert manifest["result_sha256"] == result.sha256
    assert manifest["operation"] == "export"
    assert manifest["engine"]["model_id"] == "export_recommender"
    assert manifest["engine"]["model_version"] == "1.0.0"
    assert manifest["parameters"]["format"] == fmt
    assert manifest["qa"]["pre_create_source"]["effective_gate"]["passed"] is True
    assert manifest["qa"]["export_production_preflight"]["status"] == "PASS"
    assert manifest["qa"]["binary_reread"]["status"] == "PASS"
    assert manifest["qa"]["post_create_result"]["effective_gate"]["passed"] is True

    if fmt == "PNG_DTF":
        with Image.open(output) as opened:
            alpha_values = set(np.unique(np.asarray(opened.convert("RGBA").getchannel("A"))).tolist())
        assert alpha_values == {0, 255}
        assert result.ai["export_contract"]["binary_reread"]["checks"]["dtf_binary_alpha"] is True


def test_f09_svg_passthrough_has_manifest_and_safe_reread(isolated_runtime) -> None:
    payload = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30" viewBox="0 0 40 30"><path d="M2 2h36v26H2z" fill="#334455"/></svg>'
    source = inspect_upload(payload, "vector-source.svg")
    result = export_asset(source, "SVG", {
        "filename": "vector-final",
        "folder": "Vectors",
        "ppi": 300,
        "quality": 100,
        "transparency": "preserve",
        "color_profile": "preserve",
        "metadata_policy": "minimal",
        "logo_variant": "original",
    })
    assert result.format == "SVG"
    assert result.parameters["format"] == "SVG"
    target = isolated_runtime.data_dir / "exports" / result.parameters["export_target"]
    assert target.read_bytes() == (isolated_runtime.upload_dir / source.stored_name).read_bytes()
    manifest = json.loads((isolated_runtime.data_dir / "exports" / result.parameters["export_manifest"]).read_text("utf-8"))
    assert manifest["engine"]["provider"] == "deterministic"
    assert manifest["qa"]["binary_reread"]["status"] == "PASS"


def test_f09_rejects_absolute_or_traversal_export_folder(isolated_runtime) -> None:
    source = _source_asset()
    for folder in ("../escape", "/absolute", "safe/../escape"):
        with pytest.raises(ExportError, match="Папка экспорта"):
            export_asset(source, "PNG", _params("PNG", folder=folder))


def test_f09_independent_source_qa_fail_closes_before_creation(isolated_runtime) -> None:
    source = inspect_upload(_png_source(), "tampered-source.png")
    source.sha256 = "0" * 64
    with pytest.raises(ExportError, match="независимым QA исходного файла"):
        export_asset(source, "PNG", _params("PNG"))
    assert not (isolated_runtime.data_dir / "exports" / "Order-001").exists()


def test_f09_missing_prior_ai_evidence_is_recorded_but_not_sole_blocker(isolated_runtime) -> None:
    source = inspect_upload(_png_source(), "deterministic-source.png")
    result = export_asset(source, "PNG", _params("PNG", folder="No-AI"))
    gate = result.ai["export_contract"]["source_qa"]["effective_gate"]
    assert gate["passed"] is True
    assert gate["layers"]["technical"]["advisory_nonblocking"] == ["ai_evidence"]


def test_f09_jpg_requires_explicit_flatten_policy(isolated_runtime) -> None:
    source = _source_asset()
    params = _params("JPG")
    params["transparency"] = "preserve"
    with pytest.raises(ExportError, match="production preflight"):
        export_asset(source, "JPG", params)


def test_f09_dtf_requires_transparent_background_and_binary_output(isolated_runtime) -> None:
    opaque = _source_asset(transparent=False)
    with pytest.raises(ExportError, match="прозрачного фона"):
        export_asset(opaque, "PNG_DTF", _params("PNG_DTF"))


def test_f09_logo_original_black_gray_are_contextual_export_variants(isolated_runtime) -> None:
    source = _source_asset()
    for mode, expected in (("black", 0), ("gray", 96)):
        result = export_asset(source, "PNG", _params("PNG", folder=f"Logo-{mode}", logo_variant=mode))
        target = isolated_runtime.data_dir / "exports" / result.parameters["export_target"]
        with Image.open(target) as opened:
            rgba = np.asarray(opened.convert("RGBA"))
        visible = rgba[:, :, 3] > 0
        assert np.all(rgba[:, :, :3][visible] == expected)
        assert result.parameters["logo_variant"] == mode


def test_f09_existing_masters_and_cardlab_handoff_remain_preserved() -> None:
    source = Path(__file__).resolve().parents[1]
    main = (source / "app/main.py").read_text("utf-8")
    ui = (source / "app/static/index.html").read_text("utf-8") + "\n" + "".join(
        path.read_text("utf-8") for path in sorted((source / "app/static/m2a-ui-parts").glob("*.js.part"))
    )
    service = (source / "app/services/export_service.py").read_text("utf-8")
    for token in ("/bundle", "/cardlab-package"):
        assert token in main
    for control in ("masterCleanButton", "masterCardButton", "masterDtfButton", "cardlabButton", "exportLogoMode"):
        assert control in ui
    assert "build_project_bundle" in service
    assert "build_cardlab_package" in service
