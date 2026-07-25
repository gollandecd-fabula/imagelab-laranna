from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_honor_installed_data_and_static_environment(tmp_path: Path) -> None:
    data_dir = tmp_path / "user-data"
    static_dir = tmp_path / "installed-app" / "app" / "static"
    static_dir.mkdir(parents=True)
    script = """
import json
from app.config import settings
print(json.dumps({
    'data_dir': str(settings.data_dir),
    'upload_dir': str(settings.upload_dir),
    'preview_dir': str(settings.preview_dir),
    'project_dir': str(settings.project_dir),
    'static_dir': str(settings.static_dir),
}))
"""
    env = os.environ.copy()
    env["IMAGELAB_DATA_DIR"] = str(data_dir)
    env["IMAGELAB_STATIC_DIR"] = str(static_dir)
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["data_dir"]) == data_dir.resolve()
    assert Path(payload["upload_dir"]) == (data_dir / "uploads").resolve()
    assert Path(payload["preview_dir"]) == (data_dir / "previews").resolve()
    assert Path(payload["project_dir"]) == (data_dir / "projects").resolve()
    assert Path(payload["static_dir"]) == static_dir.resolve()


def test_windows_installer_verifies_python_and_uses_private_runtime() -> None:
    source = (ROOT / "windows_installer" / "installer" / "main.go").read_text("utf-8")
    assert 'pythonSHA256' in source
    assert 'c54d9b9bbb8a36e6489363ddd01139707fd781d72f1f9e90c7ec65d0061368e0' in source
    assert "downloadVerified" in source
    assert "get-pip.py" not in source
    assert "Include_pip=1" in source
    assert "TargetDir=" in source
    assert "--only-binary=:all:" in source
    assert "--no-deps" in source
    assert '"-m", "pip", "check"' in source
    assert "importlib.metadata" in source
    assert "from app.main import app" in source


def test_requirements_are_exactly_pinned() -> None:
    lines = [line.strip() for line in (ROOT / "requirements.txt").read_text("utf-8").splitlines() if line.strip()]
    assert lines
    assert all("==" in line and not any(token in line for token in (">", "<", "~=")) for line in lines)


def test_windows_launcher_reports_startup_failures_and_logs_output() -> None:
    source = (ROOT / "windows_installer" / "launcher" / "main.go").read_text("utf-8")
    assert "MessageBoxW" in source
    assert "launcher.log" in source
    assert "cmd.Stdout = logFile" in source
    assert "cmd.Stderr = logFile" in source
    assert "if err := cmd.Start(); err != nil" in source
    assert "_ = cmd.Start()" not in source
    assert '"PYTHONNOUSERSITE"' in source
    assert '"1"' in source[source.index('"PYTHONNOUSERSITE"'):source.index('"PYTHONNOUSERSITE"') + 120]


def test_windows_installer_does_not_ignore_shortcut_or_launch_errors() -> None:
    source = (ROOT / "windows_installer" / "installer" / "main.go").read_text("utf-8")
    assert "desktop shortcut:" in source
    assert "start menu shortcut:" in source
    assert "launch ImageLab:" in source
    assert "_ = exec.Command(launcher).Start()" not in source


def test_uninstaller_reports_start_failures_and_preserves_user_data() -> None:
    source = (ROOT / "windows_installer" / "uninstaller" / "main.go").read_text("utf-8")
    assert "if err := cmd.Start(); err != nil" in source
    assert "Пользовательские проекты сохраняются" in source
    assert 'ImageLab by LarannA", "data"' not in source
