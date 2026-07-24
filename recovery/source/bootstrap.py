from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from app.config import settings


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
BASE_PORT = int(os.environ.get("IMAGELAB_PORT", settings.port))
MAX_PORT_ATTEMPTS = 10

os.chdir(ROOT)
os.environ.setdefault("IMAGELAB_STATIC_DIR", str(ROOT / "app" / "static"))


def _url(port: int) -> str:
    return f"http://{HOST}:{port}"


def _browser_url(port: int) -> str:
    query = urllib.parse.urlencode(
        {
            "version": settings.app_version,
            "build": settings.build_id,
            "install": settings.install_id,
        }
    )
    return f"{_url(port)}/?{query}"


def _health_identity(port: int, timeout: float = 0.6, *, require_current_identity: bool = True) -> dict[str, object] | None:
    try:
        request = urllib.request.Request(
            f"{_url(port)}/api/health",
            headers={"Host": f"{HOST}:{port}", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(128 * 1024).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("app") != settings.app_name:
                return None
            if require_current_identity:
                expected = {
                    "version": settings.app_version,
                    "build_id": settings.build_id,
                    "install_id": settings.install_id,
                }
                if any(payload.get(key) != value for key, value in expected.items()):
                    return None
            return payload
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, urllib.error.URLError):
        return None


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _select_port() -> tuple[int, bool]:
    ports = list(range(BASE_PORT, BASE_PORT + MAX_PORT_ATTEMPTS))
    # Reuse only the exact installation instance. Matching only the semantic
    # version is insufficient because an older process can survive an update.
    for port in ports:
        if _health_identity(port, require_current_identity=True) is not None:
            return port, True
    for port in ports:
        if _port_is_free(port):
            return port, False
    stale = []
    for port in ports:
        payload = _health_identity(port, require_current_identity=False)
        if payload is not None:
            stale.append(
                f"{port}:{payload.get('version', 'unknown')}/"
                f"{payload.get('build_id', 'unknown')}/"
                f"{payload.get('install_id', 'unknown')}"
            )
    detail = f"; обнаружены другие процессы ImageLab: {', '.join(stale)}" if stale else ""
    raise RuntimeError(
        f"Нет свободного локального порта в диапазоне {BASE_PORT}–{BASE_PORT + MAX_PORT_ATTEMPTS - 1}{detail}"
    )


def _open_when_ready(port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        payload = _health_identity(port, timeout=0.8, require_current_identity=True)
        if payload is not None and payload.get("status") == "ok":
            webbrowser.open(_browser_url(port))
            return
        time.sleep(0.25)


def _verify_launcher_identity() -> None:
    expected = {
        "IMAGELAB_EXPECTED_VERSION": settings.app_version,
        "IMAGELAB_EXPECTED_BUILD_ID": settings.build_id,
        "IMAGELAB_EXPECTED_INSTALL_ID": settings.install_id,
    }
    mismatches = []
    for env_name, actual in expected.items():
        supplied = os.environ.get(env_name, "").strip()
        if supplied and supplied != actual:
            mismatches.append(f"{env_name}={supplied!r}, payload={actual!r}")
    if mismatches:
        raise RuntimeError("Launcher/payload identity mismatch: " + "; ".join(mismatches))


def main() -> None:
    _verify_launcher_identity()
    port, already_running = _select_port()
    external_browser = os.environ.get("IMAGELAB_EXTERNAL_BROWSER", "0") == "1"
    if already_running:
        if not external_browser:
            webbrowser.open(_browser_url(port))
        return
    if not external_browser:
        threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
