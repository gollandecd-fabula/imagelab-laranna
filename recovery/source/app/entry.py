from __future__ import annotations

from pathlib import Path

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.main import app as core_app


class UIHardeningEntry:
    """Serve the audited UI shell while delegating API/static requests unchanged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.index_path = Path(settings.static_dir) / "index.html"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and scope.get("method") in {"GET", "HEAD"} and scope.get("path") == "/":
            html = self.index_path.read_text("utf-8")
            html = html.replace(
                "</head>",
                '<link rel="stylesheet" href="/static/m1-hardening.css?v=m1"></head>',
                1,
            )
            html = html.replace(
                "</body>",
                '<script src="/static/m1-hardening.js?v=m1"></script></body>',
                1,
            )
            response = HTMLResponse(
                html,
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "X-Frame-Options": "DENY",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
                    "Content-Security-Policy": (
                        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
                        "script-src 'self'; connect-src 'self'; object-src 'none'; "
                        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                    ),
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app = UIHardeningEntry(core_app)
