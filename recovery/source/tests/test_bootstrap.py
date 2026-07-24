from __future__ import annotations

import bootstrap
from app.config import settings


def current_payload() -> dict[str, str]:
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "build_id": settings.build_id,
        "install_id": settings.install_id,
    }


def test_bootstrap_reuses_only_exact_current_installation(monkeypatch) -> None:
    def health(port: int, timeout: float = 0.6, *, require_current_identity: bool = True):
        if port != bootstrap.BASE_PORT:
            return None
        payload = current_payload()
        return payload if not require_current_identity or payload == current_payload() else None

    monkeypatch.setattr(bootstrap, "_health_identity", health)
    assert bootstrap._select_port() == (bootstrap.BASE_PORT, True)


def test_bootstrap_skips_occupied_unrelated_port(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_health_identity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bootstrap, "_port_is_free", lambda port: port == bootstrap.BASE_PORT + 1)
    assert bootstrap._select_port() == (bootstrap.BASE_PORT + 1, False)


def test_bootstrap_reuses_current_installation_on_secondary_managed_port(monkeypatch) -> None:
    def health(port: int, timeout: float = 0.6, *, require_current_identity: bool = True):
        if port == bootstrap.BASE_PORT + 1:
            return current_payload()
        return None

    monkeypatch.setattr(bootstrap, "_health_identity", health)
    monkeypatch.setattr(bootstrap, "_port_is_free", lambda port: port >= bootstrap.BASE_PORT + 2)
    assert bootstrap._select_port() == (bootstrap.BASE_PORT + 1, True)


def test_bootstrap_never_reuses_stale_version(monkeypatch) -> None:
    def health(port: int, timeout: float = 0.6, *, require_current_identity: bool = True):
        if port != bootstrap.BASE_PORT:
            return None
        payload = {**current_payload(), "version": "1.3.1-core-fix-candidate"}
        return None if require_current_identity else payload

    monkeypatch.setattr(bootstrap, "_health_identity", health)
    monkeypatch.setattr(bootstrap, "_port_is_free", lambda port: port == bootstrap.BASE_PORT + 1)
    assert bootstrap._select_port() == (bootstrap.BASE_PORT + 1, False)


def test_bootstrap_never_reuses_same_build_from_another_installation(monkeypatch) -> None:
    def health(port: int, timeout: float = 0.6, *, require_current_identity: bool = True):
        if port != bootstrap.BASE_PORT:
            return None
        payload = {**current_payload(), "install_id": "another-installation"}
        return None if require_current_identity else payload

    monkeypatch.setattr(bootstrap, "_health_identity", health)
    monkeypatch.setattr(bootstrap, "_port_is_free", lambda port: port == bootstrap.BASE_PORT + 1)
    assert bootstrap._select_port() == (bootstrap.BASE_PORT + 1, False)
