from __future__ import annotations

from pathlib import Path

from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.main import app as core_app, store
from app.m2a_api import register_m2a_routes


# app.main exports the request-size wrapper; its ``app`` attribute is the
# configured FastAPI instance. Register M2A routes on that instance so the
# existing host/origin/body-limit security chain remains authoritative.
register_m2a_routes(getattr(core_app, "app", core_app), store)

_RUNTIME_TRAINING_PATHS = frozenset({"/api/ai/train", "/api/ai/rollback"})
_RUNTIME_TRAINING_UI_TOKENS = (
    "/api/ai/train",
    "/api/ai/rollback",
    "aiTrainButton",
    "aiRollbackButton",
    "aiTrainModule",
    "trainAIModule",
    "rollbackAIModule",
)


def _remove_runtime_training_html(html: str) -> str:
    start_marker = '        <strong class="section-caption">Обратная связь и обучение</strong>'
    end_marker = (
        '        <small class="ai-boundary">Новая модель активируется только после validation '
        'benchmark. Результаты не улучшаются бесконтрольно после каждого клика.</small>'
    )
    start = html.find(start_marker)
    end = html.find(end_marker, start if start >= 0 else 0)
    if start >= 0 and end >= 0:
        end += len(end_marker)
        replacement = (
            '        <strong class="section-caption">Обратная связь для офлайн-оценки</strong>\n'
            '        <div class="feedback-row"><button class="feedback-button accept" '
            'id="aiAccept" type="button">✓ Принять</button><button class="feedback-button '
            'reject" id="aiReject" type="button">✕ Отклонить</button></div>\n'
            '        <small class="ai-boundary">Обратная связь сохраняется для отдельно '
            'контролируемой офлайн-оценки. Обучение и откат модели в пользовательском runtime '
            'отключены.</small>'
        )
        html = html[:start] + replacement + html[end:]
    forbidden = [token for token in _RUNTIME_TRAINING_UI_TOKENS if token in html]
    if forbidden:
        raise RuntimeError(f"runtime training controls remain in served HTML: {forbidden}")
    return html


def _remove_runtime_training_javascript(javascript: str) -> str:
    start = javascript.find("\nasync function trainAIModule() {")
    end = javascript.find("\n\nasync function api(", start if start >= 0 else 0)
    if start >= 0 and end >= 0:
        javascript = javascript[:start] + "\n" + javascript[end + 2 :]
    javascript = javascript.replace(",'aiTrainButton','aiRollbackButton'", "")
    javascript = javascript.replace(
        "  const trainingModule = feedbackModuleMap[module] || 'upload';\n"
        "  if ($('#aiTrainModule')) { $('#aiTrainModule').value = trainingModule; "
        "$('#aiTrainModule').disabled = true; }\n",
        "",
    )
    javascript = javascript.replace(
        "$('#aiTrainButton').addEventListener('click',trainAIModule);\n"
        "$('#aiRollbackButton').addEventListener('click',rollbackAIModule);\n",
        "",
    )
    forbidden = [token for token in _RUNTIME_TRAINING_UI_TOKENS if token in javascript]
    if forbidden:
        raise RuntimeError(f"runtime training controls remain in served JavaScript: {forbidden}")
    return javascript


class UIHardeningEntry:
    """Serve the audited UI shell while delegating allowed API/static requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.index_path = Path(settings.static_dir) / "index.html"
        self.app_javascript_path = Path(settings.static_dir) / "app.js"
        self.m2a_parts_dir = Path(settings.static_dir) / "m2a-ui-parts"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_http = scope.get("type") == "http"
        method = scope.get("method")
        path = scope.get("path")
        is_safe_read = is_http and method in {"GET", "HEAD"}

        # User runtime may collect feedback for separately controlled offline
        # evaluation, but it must never expose model training or rollback paths.
        if is_http and path in _RUNTIME_TRAINING_PATHS:
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        if is_safe_read and path == "/static/app.js":
            javascript = _remove_runtime_training_javascript(
                self.app_javascript_path.read_text("utf-8")
            )
            await Response(
                javascript,
                media_type="application/javascript",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )(scope, receive, send)
            return
        if is_safe_read and path == "/static/m2a-ui.js":
            javascript = "".join(
                item.read_text("utf-8")
                for item in sorted(self.m2a_parts_dir.glob("*.js.part"))
            )
            await Response(
                javascript,
                media_type="application/javascript",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )(scope, receive, send)
            return
        if is_safe_read and path == "/":
            html = _remove_runtime_training_html(self.index_path.read_text("utf-8"))
            html = html.replace(
                "</head>",
                '<link rel="stylesheet" href="/static/m1-hardening.css?v=m1">'
                '<link rel="stylesheet" href="/static/m2a-ui.css?v=m2a">'
                '<link rel="stylesheet" href="/static/m2a-completeness.css?v=m2a"></head>',
                1,
            )
            html = html.replace(
                "</body>",
                '<script src="/static/m1-hardening.js?v=m1"></script>'
                '<script src="/static/m2a-ui.js?v=m2a"></script></body>',
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
