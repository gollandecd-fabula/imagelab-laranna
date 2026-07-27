from __future__ import annotations

from pathlib import Path

from starlette.responses import HTMLResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.main import app as core_app

class UIHardeningEntry:
    """Serve the audited UI shell while delegating API/static requests unchanged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.index_path = Path(settings.static_dir) / "index.html"
        self.m2a_parts_dir = Path(settings.static_dir) / "m2a-ui-parts"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_safe_read = scope.get("type") == "http" and scope.get("method") in {"GET", "HEAD"}
        if is_safe_read and scope.get("path") == "/static/m2a-ui.js":
            javascript = "".join(path.read_text("utf-8") for path in sorted(self.m2a_parts_dir.glob("*.js.part")))
            await Response(
                javascript,
                media_type="application/javascript",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )(scope, receive, send)
            return
        if is_safe_read and scope.get("path") == "/":
            html = self.index_path.read_text("utf-8")
            html = html.replace(
                "</head>",
                '<link rel="stylesheet" href="/static/m1-hardening.css?v=m1"><link rel="stylesheet" href="/static/m2a-ui.css?v=m2a"></head>',
                1,
            )
            html = html.replace(
                "</body>",
                '<script src="/static/m1-hardening.js?v=m1"></script><script src="/static/m2a-ui.js?v=m2a"></script></body>',
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
