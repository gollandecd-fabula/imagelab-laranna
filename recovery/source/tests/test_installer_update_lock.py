from __future__ import annotations

import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_health_exposes_exact_build_and_install_identity() -> None:
    payload = client.get('/api/health').json()
    assert payload['app'] == 'ImageLab by LarannA'
    from app.config import settings
    assert payload['version'] == settings.app_version
    assert payload['build_id'] == settings.build_id
    assert payload['install_id'] == settings.install_id
    assert payload['scope'] == 'IUL_M6_UPDATE_LOCK_CANDIDATE'


def test_settings_take_install_id_from_launcher_environment(monkeypatch) -> None:
    monkeypatch.setenv('IMAGELAB_INSTALL_ID', 'test-install-identity')
    import app.config as config
    reloaded = importlib.reload(config)
    try:
        assert reloaded.settings.install_id == 'test-install-identity'
    finally:
        monkeypatch.delenv('IMAGELAB_INSTALL_ID', raising=False)
        importlib.reload(config)


def test_bootstrap_requires_version_build_and_install_identity() -> None:
    source = (ROOT / 'bootstrap.py').read_text('utf-8')
    assert 'IMAGELAB_EXPECTED_VERSION' in source
    assert 'IMAGELAB_EXPECTED_BUILD_ID' in source
    assert 'IMAGELAB_EXPECTED_INSTALL_ID' in source
    assert '"build_id": settings.build_id' in source
    assert '"install_id": settings.install_id' in source
    assert '_browser_url' in source


def test_launcher_verifies_install_manifest_and_waits_for_exact_health() -> None:
    source = (ROOT / 'windows_installer' / 'launcher' / 'main.go').read_text('utf-8')
    for token in (
        'install-manifest.json',
        'CriticalFiles',
        'sha256File',
        'IMAGELAB_EXPECTED_VERSION',
        'IMAGELAB_EXPECTED_BUILD_ID',
        'IMAGELAB_EXPECTED_INSTALL_ID',
        'IMAGELAB_INSTALL_ID',
        'waitForExactHealth',
        'health.InstallID == manifest.InstallID',
        '75 * time.Second',
    ):
        assert token in source
    assert 'cmd.Start()' in source
    assert 'cmd.Wait()' in source


def test_installer_uses_staging_atomic_promotion_and_rollback() -> None:
    source = (ROOT / 'windows_installer' / 'installer' / 'main.go').read_text('utf-8')
    for token in (
        '.staging-',
        '.backup',
        'promoteAtomic',
        'rollbackPromotion',
        'renameWithRetry',
        'verifyInstallManifest(stagingDir',
        'verifyInstallManifest(installDir',
        'runtimeWorks',
        'installed Python runtime failed its isolated startup check',
        'previous installation restored',
    ):
        assert token in source
    assert 'extractBytes(payload, stagingDir)' in source
    assert 'extractBytes(payload, installDir)' not in source


def test_installer_stops_health_identified_servers_and_private_runtime_processes() -> None:
    source = (ROOT / 'windows_installer' / 'installer' / 'main.go').read_text('utf-8')
    for token in (
        'probeImageLab',
        'listenerPIDs',
        'Get-NetTCPConnection',
        'netstat.exe',
        'taskkill.exe',
        'ExecutablePath.StartsWith',
        'предыдущий сервер ImageLab',
    ):
        assert token in source


def test_installer_success_requires_exact_new_install_instance() -> None:
    source = (ROOT / 'windows_installer' / 'installer' / 'main.go').read_text('utf-8')
    for token in (
        'randomInstallID',
        'waitForExactHealth',
        'health.Version == appVersion',
        'health.BuildID == buildID',
        'health.InstallID == installID',
        'health.Status == "ok"',
        '90 * time.Second',
        'Новая установка подтверждена',
    ):
        assert token in source
    launch_pos = source.index('command.Start()')
    health_pos = source.index('waitForExactHealth(installID)')
    success_pos = source.index('Установка завершена: version=')
    assert launch_pos < health_pos < success_pos


def test_frontend_shows_version_and_install_identity() -> None:
    html = (ROOT / 'app' / 'static' / 'index.html').read_text('utf-8')
    js = (ROOT / 'app' / 'static' / 'app.js').read_text('utf-8')
    assert '1.4.1-update-lock' in html
    assert 'runtime.install_id' in js
    assert 'runtime.build_id' in js
    assert "cache:'no-store'" in js
