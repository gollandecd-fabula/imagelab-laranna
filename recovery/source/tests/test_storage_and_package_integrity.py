from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

import app.services.export_service as export_module
from app.config import settings
from app.models import ProjectRecord
from app.services.export_service import build_cardlab_package, export_asset
from app.services.file_inspector import inspect_upload


def _transparent_png() -> bytes:
    image = Image.new("RGBA", (64, 48), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 8, 54, 40), fill=(200, 30, 50, 255))
    buffer = io.BytesIO(); image.save(buffer, "PNG", dpi=(300, 300)); return buffer.getvalue()


class _ExportEngine:
    def recommend_export(self, *_args, **_kwargs):
        return {"details": {"format": "WEBP"}}
    def preflight(self, *_args, **_kwargs):
        return {"details": {"passed": True}}


def test_webp_preserves_embedded_ppi(monkeypatch) -> None:
    asset = inspect_upload(_transparent_png(), "ppi-source.png")
    monkeypatch.setattr(export_module, "get_ai_engine", lambda: _ExportEngine())
    result = export_asset(asset, "WEBP", {"ppi": 240, "quality": 90, "keep_alpha": True, "ai_auto": False})
    try:
        assert abs(float(result.ppi_x) - 240) < 0.1
        assert result.ppi_origin in {"embedded", "embedded_exif"}
        with Image.open(settings.upload_dir / result.stored_name) as reopened:
            exif = reopened.getexif()
            assert abs(float(exif[282]) - 240) < 0.1
            assert abs(float(exif[283]) - 240) < 0.1
    finally:
        for item in (asset, result):
            (settings.upload_dir / item.stored_name).unlink(missing_ok=True)
            (settings.preview_dir / item.preview_name).unlink(missing_ok=True)


def test_cardlab_package_is_deterministic_and_self_verifying() -> None:
    asset = inspect_upload(_transparent_png(), "cardlab.png")
    project = ProjectRecord(id="CARDLAB-001", title="CardLab", created_at="2026-07-24T00:00:00+00:00", updated_at="2026-07-24T00:00:00+00:00", assets=[asset])
    try:
        first, first_name = build_cardlab_package(project, asset)
        second, second_name = build_cardlab_package(project, asset)
        assert first == second and first_name == second_name
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            names = set(archive.namelist())
            assert {"manifest.json", "lineage.json", "qa-boundary.json"} <= names
            assert f"print/{asset.stored_name}" in names
            manifest = json.loads(archive.read("manifest.json"))
            for name, record in manifest["files"].items():
                payload = archive.read(name)
                assert hashlib.sha256(payload).hexdigest() == record["sha256"]
                assert len(payload) == record["size_bytes"]
            boundary = json.loads(archive.read("qa-boundary.json"))
            assert "installed Windows L4/L5" in boundary["not_verified"]
    finally:
        (settings.upload_dir / asset.stored_name).unlink(missing_ok=True)
        (settings.preview_dir / asset.preview_name).unlink(missing_ok=True)


def test_installer_harness_waits_only_for_installer_pid_with_timeout() -> None:
    common = (Path(__file__).resolve().parents[1] / "release_gate" / "common.ps1").read_text(encoding="utf-8")

    assert "Start-Process -FilePath $InstallerPath" in common
    assert "-Wait -PassThru" not in common
    assert "$process.WaitForExit($installerTimeoutMilliseconds)" in common
    assert "$installerTimeoutMilliseconds = 30 * 60 * 1000" in common
    assert "Stop-Process -Id $process.Id -Force" in common
    assert "Installer process did not exit within 30 minutes" in common


def test_clean_install_harness_materializes_isolated_gate_runtime_before_installer() -> None:
    source = (Path(__file__).resolve().parents[1] / "release_gate" / "run_clean_install_gate.ps1").read_text(encoding="utf-8")

    resolve = '$sourceGatePython = (& python -c "import sys; print(sys.executable)").Trim()'
    copy_runtime = '& robocopy.exe $sourceGateRoot $gateRuntimeRoot /E /COPY:DAT /DCOPY:DAT'
    install = '$exitCode = Invoke-Installer -InstallerPath $InstallerPath'
    post_install_check = 'throw "Copied release gate Python disappeared after installation"'

    assert resolve in source
    assert copy_runtime in source
    assert source.index(resolve) < source.index(copy_runtime) < source.index(install)
    assert "$robocopyExitCode -gt 7" in source
    assert "$gatePython = Join-Path $gateRuntimeRoot 'python.exe'" in source
    assert "$gatePythonSha = Get-Sha256 $gatePython" in source
    assert source.index(install) < source.index(post_install_check)
    assert "Copied release gate Python changed during installation" in source
    assert "Copied release gate Python failed after installation" in source
    assert source.count('& $gatePython -c "import sys, PIL; import playwright.sync_api; print(sys.executable)"') == 2
    assert r'& $gatePython "$PSScriptRoot\ui_gate.py"' in source
    assert r'& $gatePython "$PSScriptRoot\validate_outputs.py"' in source
    assert r'python "$PSScriptRoot\ui_gate.py"' not in source
    assert r'python "$PSScriptRoot\validate_outputs.py"' not in source
    assert 'release_gate_python_source = $sourceGatePython' in source
    assert 'release_gate_python_sha256 = $gatePythonSha' in source
    assert 'release_gate_runtime_isolated = $true' in source
    assert 'Remove-Item -Recurse -Force -LiteralPath $gateRuntimeRoot' in source


def test_clean_install_harness_does_not_reuse_source_toolcache_python_after_installer() -> None:
    source = (Path(__file__).resolve().parents[1] / "release_gate" / "run_clean_install_gate.ps1").read_text(encoding="utf-8")

    install = '$exitCode = Invoke-Installer -InstallerPath $InstallerPath'
    install_index = source.index(install)
    post_install = source[install_index:]
    assert '& $sourceGatePython ' not in post_install
    assert '& python ' not in post_install
    assert '& $gatePython "$PSScriptRoot\\ui_gate.py"' in post_install
    assert '& $gatePython "$PSScriptRoot\\validate_outputs.py"' in post_install
    assert 'Get-Sha256 $gatePython' in post_install


def test_ui_gate_validates_visible_version_install_and_build_title_contract() -> None:
    source = (Path(__file__).resolve().parents[1] / "release_gate" / "ui_gate.py").read_text(encoding="utf-8")

    assert "arg=[args.expected_version, args.expected_build_id, args.expected_install_id]" in source
    assert "text.includes(version)" in source
    assert "text.includes(String(install).slice(0, 8))" in source
    assert "title.includes(build)" in source
    assert "title.includes(install)" in source
    assert "chip.classList.contains('ready')" in source
    assert "textContent.includes(build)" not in source
