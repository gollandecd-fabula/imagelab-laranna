from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable

import numpy as np

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app.ai.feedback import AIFeedbackError
from app.ai.registry import AIModelError
from app.ai.runtime import get_ai_engine
from app.config import settings
from app.models import (
    ActiveAssetRequest,
    AIFeedbackRequest,
    CheckItem,
    AIRollbackRequest,
    AITrainRequest,
    ExportRequest,
    ExportResponse,
    ProcessRequest,
    ProcessResponse,
    ProjectRecord,
    ProjectReportResponse,
    QaResponse,
    UploadResponse,
)
from app.services.export_service import ExportError, build_project_bundle, export_asset
from app.services.file_inspector import UploadValidationError, inspect_upload
from app.services.image_processing import ProcessingError
from app.services.project_store import ProjectStore, ProjectStoreError
from app.services.qa_service import build_project_report, build_qa_response
from app.services.repair_service import record_continual_learning, run_processing_with_repair


class RequestBodyLimitMiddleware:
    """Bound chunked and Content-Length requests before request parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        limit = 220 * 1024 * 1024 if path.endswith("/upload") else 4 * 1024 * 1024
        total = 0
        spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            while True:
                message = await receive()
                message_type = message.get("type")
                if message_type == "http.disconnect":
                    return
                if message_type != "http.request":
                    continue
                body = message.get("body", b"")
                total += len(body)
                if total > limit:
                    response = JSONResponse(status_code=413, content={"detail": "Запрос превышает безопасный лимит"})
                    await response(scope, receive, send)
                    return
                spool.write(body)
                if not message.get("more_body", False):
                    break
            spool.seek(0)
            replay_finished = False

            async def replay_receive():
                nonlocal replay_finished
                if replay_finished:
                    return {"type": "http.request", "body": b"", "more_body": False}
                chunk = spool.read(1024 * 1024)
                more = bool(chunk) and spool.tell() < total
                if not more:
                    replay_finished = True
                return {"type": "http.request", "body": chunk, "more_body": more}

            await self.app(scope, replay_receive, send)
        finally:
            spool.close()


for directory in (
    settings.data_dir,
    settings.upload_dir,
    settings.preview_dir,
    settings.project_dir,
    settings.ai_feedback_dir,
    settings.ai_audit_dir,
    settings.ai_promoted_model_dir,
):
    directory.mkdir(parents=True, exist_ok=True)

store = ProjectStore()
store.get_or_create(settings.default_project_id)

app = FastAPI(title=settings.app_name, version=settings.app_version, docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.middleware("http")
async def request_size_and_security_headers(request: Request, call_next):
    raw_host = request.headers.get("host", "").strip()
    if raw_host.startswith("[") and "]" in raw_host:
        host = raw_host[1:raw_host.index("]")].lower()
    else:
        host = raw_host.rsplit(":", 1)[0].lower() if raw_host.count(":") == 1 else raw_host.lower()
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse(status_code=421, content={"detail": "Недопустимый Host для локального приложения"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        request_host = request.headers.get("host", "").strip()
        allowed_origins = {
            f"http://{request_host}", f"https://{request_host}",
            f"http://127.0.0.1:{settings.port}", f"http://localhost:{settings.port}",
            "http://testserver", "https://testserver",
        }
        if origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Межсайтовый запрос к локальному API заблокирован"})
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            return JSONResponse(status_code=403, content={"detail": "Межсайтовый запрос к локальному API заблокирован"})
    content_length = request.headers.get("content-length")
    limit = 220 * 1024 * 1024 if request.url.path.endswith("/upload") else 4 * 1024 * 1024
    if content_length:
        try:
            parsed_length = int(content_length)
            if parsed_length < 0:
                return JSONResponse(status_code=400, content={"detail": "Content-Length не может быть отрицательным"})
            if parsed_length > limit:
                return JSONResponse(status_code=413, content={"detail": "Запрос превышает безопасный лимит"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Некорректный Content-Length"})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _find_asset(asset_id: str) -> ProjectRecord | None:
    found = store.find_asset(asset_id)
    return found[0] if found else None


def _get_asset(asset_id: str):
    found = store.find_asset(asset_id)
    if not found:
        raise HTTPException(status_code=404, detail="Файл не найден")
    return found


def _iter_feature_vectors(value: Any):
    if isinstance(value, dict):
        details = value.get("details")
        if isinstance(details, dict) and isinstance(details.get("features"), list):
            yield details["features"]
        for nested in value.values():
            yield from _iter_feature_vectors(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_feature_vectors(nested)




def _asset_descends_from(project: ProjectRecord, candidate, ancestor_id: str) -> bool:
    by_id = {item.id: item for item in project.assets}
    current = candidate
    visited: set[str] = set()
    for _ in range(len(by_id) + 1):
        if current.id == ancestor_id or current.source_asset_id == ancestor_id:
            return True
        parent_id = current.source_asset_id
        if not parent_id or parent_id in visited or parent_id not in by_id:
            return False
        visited.add(parent_id)
        current = by_id[parent_id]
    return False

def _feedback_modules_for_asset(asset) -> set[str]:
    mapping = {
        None: {"upload"}, "enhance": {"improve"}, "reconstruct": {"improve"}, "color": {"improve"},
        "extract_print": {"extract"}, "select": {"selection"}, "background": {"cleanup"},
        "cleanup": {"cleanup"}, "halftone": {"halftone"}, "vectorize": {"vector"},
        "geometry": {"geometry"}, "export": {"export"}, "master_clean": {"cleanup"},
        "master_card": {"geometry"}, "master_dtf": {"extract", "export"},
    }
    result = set(mapping.get(asset.operation, set()))
    if any(record.get("task") == "visual_preflight" for record in _iter_ai_dicts(asset.ai)):
        result.add("qa")
    return result


def _iter_ai_dicts(value: Any):
    if isinstance(value, dict):
        if value.get("model_id") and value.get("model_version"):
            yield value
        for nested in value.values():
            yield from _iter_ai_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_ai_dicts(nested)


def _asset_image(asset) -> Image.Image:
    if asset.format == "SVG":
        raise HTTPException(status_code=422, detail="AI-анализ SVG в растровом контуре недоступен")
    path = settings.upload_dir / asset.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    with Image.open(path) as image:
        return image.convert("RGBA")


def _remove_asset_files(asset) -> None:
    for directory, name in ((settings.upload_dir, asset.stored_name), (settings.preview_dir, asset.preview_name)):
        path = directory / name
        try:
            resolved = path.resolve()
            resolved.relative_to(directory.resolve())
        except (OSError, ValueError):
            continue
        try:
            resolved.unlink(missing_ok=True)
        except OSError:
            pass


@app.get("/api/health")
def health() -> dict[str, object]:
    try:
        ai = get_ai_engine().health()
        ai_status = ai["status"]
    except Exception as exc:
        ai = {"status": "failed", "error": type(exc).__name__}
        ai_status = "failed"
    return {
        "status": "ok" if ai_status == "ready" else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "scope": "IUL_M6_UPDATE_LOCK_CANDIDATE",
        "build_id": settings.build_id,
        "install_id": settings.install_id,
        "host_policy": "localhost_only",
        "ai": ai,
    }


@app.get("/api/ai/health")
def ai_health() -> dict[str, object]:
    try:
        return get_ai_engine().health()
    except AIModelError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/ai/audit")
def ai_audit(limit: int = 100) -> dict[str, object]:
    limit = max(1, min(int(limit), 1000))
    records = get_ai_engine().audit.recent(limit)
    return {"count": len(records), "records": records}


@app.post("/api/ai/feedback")
def ai_feedback(request: AIFeedbackRequest) -> dict[str, object]:
    try:
        if not request.asset_id:
            raise AIFeedbackError("Feedback должен быть связан с фактическим файлом проекта")
        project, asset = _get_asset(request.asset_id)
        allowed_modules = _feedback_modules_for_asset(asset)
        if request.module not in allowed_modules:
            raise AIFeedbackError(f"Этот файл не содержит evidence для модуля {request.module}")
        submitted = np.asarray(request.features, dtype=np.float64)
        matched = False
        for vector in _iter_feature_vectors(asset.ai):
            candidate = np.asarray(vector, dtype=np.float64)
            if candidate.shape == submitted.shape and np.isfinite(candidate).all() and np.allclose(candidate, submitted, rtol=1e-6, atol=1e-7):
                matched = True
                break
        if not matched:
            raise AIFeedbackError("Вектор feedback не совпадает с сохранённым AI-evidence файла")
        if request.correction_asset_id:
            correction_project, correction_asset = _get_asset(request.correction_asset_id)
            if correction_project.id != project.id or not _asset_descends_from(project, correction_asset, asset.id):
                raise AIFeedbackError("Исправленный файл должен быть производным от оцениваемого файла в том же проекте")
        item = get_ai_engine().feedback.add(request.module, request.model_dump(exclude={"module"}))
        return {"status": "stored", "feedback": item}
    except AIFeedbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/ai/train")
def ai_train(request: AITrainRequest) -> dict[str, object]:
    try:
        result = get_ai_engine().feedback.train(request.module)
        return {"status": "promoted" if result["promoted"] else "candidate_rejected", "model": result}
    except AIFeedbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/ai/rollback")
def ai_rollback(request: AIRollbackRequest) -> dict[str, object]:
    try:
        return {"status": "rolled_back", "model": get_ai_engine().feedback.rollback(request.module)}
    except AIFeedbackError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}", response_model=ProjectRecord)
def get_project(project_id: str) -> ProjectRecord:
    try:
        return store.get_or_create(project_id)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/active", response_model=ProjectRecord)
def set_project_active_asset(project_id: str, request: ActiveAssetRequest) -> ProjectRecord:
    try:
        return store.set_active_asset(project_id, request.asset_id)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/qa", response_model=QaResponse)
def project_qa(project_id: str, asset_id: str | None = None) -> QaResponse:
    try:
        project = store.get_or_create(project_id)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asset = None
    if asset_id:
        asset = next((item for item in project.assets if item.id == asset_id), None)
        if asset is None:
            raise HTTPException(status_code=404, detail="Файл не найден в проекте")
    return build_qa_response(project, asset)


@app.get("/api/projects/{project_id}/report", response_model=ProjectReportResponse)
def project_report(project_id: str, asset_id: str | None = None) -> ProjectReportResponse:
    try:
        project = store.get_or_create(project_id)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asset = None
    if asset_id:
        asset = next((item for item in project.assets if item.id == asset_id), None)
        if asset is None:
            raise HTTPException(status_code=404, detail="Файл не найден в проекте")
    return build_project_report(project, asset)


@app.get("/api/projects/{project_id}/bundle")
def project_bundle(project_id: str) -> Response:
    try:
        project = store.get_or_create(project_id)
        payload, filename = build_project_bundle(project)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=payload, media_type="application/zip", headers=headers)


@app.post("/api/projects/{project_id}/upload", response_model=UploadResponse)
async def upload_files(project_id: str, files: list[UploadFile] = File(...)) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Файлы не выбраны")
    if len(files) > 20:
        raise HTTPException(status_code=413, detail="За один раз можно загрузить не более 20 файлов")
    uploaded = []
    created_assets = []
    total_bytes = 0
    try:
        engine = get_ai_engine()
        for item in files:
            data = await item.read(settings.max_upload_bytes + 1)
            total_bytes += len(data)
            if len(data) > settings.max_upload_bytes:
                raise UploadValidationError("Файл превышает лимит 50 МБ")
            if total_bytes > 200 * 1024 * 1024:
                raise UploadValidationError("Суммарный размер загрузки превышает 200 МБ")
            asset = inspect_upload(data, item.filename or "image")
            created_assets.append(asset)
            if asset.format != "SVG":
                with Image.open(settings.upload_dir / asset.stored_name) as source:
                    analysis = engine.analyze(source.convert("RGBA"), module="upload")
                asset.ai = {"upload_analysis": analysis}
                asset.checks.append(CheckItem(
                    code="ai_upload", label="AI-анализ выполнен", passed=True,
                    detail=f"{analysis['details']['content']} · {analysis['confidence']:.2f}",
                ))
            else:
                asset.ai = {"upload_analysis": {"status": "vector_input", "note": "SVG проходит AI-анализ после растеризации или векторного препроцессинга"}}
            uploaded.append(asset)
        project = store.add_assets(project_id, uploaded)
        return UploadResponse(project=project, uploaded=uploaded)
    except (UploadValidationError, AIModelError) as exc:
        for asset in created_assets:
            for directory, name in ((settings.upload_dir, asset.stored_name), (settings.preview_dir, asset.preview_name)):
                path = directory / name
                if path.exists():
                    path.unlink()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, ProjectStoreError) as exc:
        for asset in created_assets:
            for directory, name in ((settings.upload_dir, asset.stored_name), (settings.preview_dir, asset.preview_name)):
                path = directory / name
                if path.exists():
                    path.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/process", response_model=ProcessResponse)
def process_project_asset(project_id: str, request: ProcessRequest) -> ProcessResponse:
    try:
        project = store.get_or_create(project_id)
        source = next((item for item in project.assets if item.id == request.asset_id), None)
        if source is None:
            raise HTTPException(status_code=404, detail="Исходный файл не найден в проекте")
        # Make the processing source explicit and server-authoritative. This also
        # repairs a stale browser state before the operation starts.
        if project.workspace.get("active_asset_id") != source.id:
            project = store.set_active_asset(project_id, source.id)
        result, attempts, repair = run_processing_with_repair(source, request.operation, request.parameters)
        try:
            # Keep every version for auditability and commit the complete lineage
            # atomically. A crash or concurrent request must never expose only a
            # subset of attempts or a stale active result.
            ordered = [item for item in attempts if item.id != result.id] + [result]
            project = store.add_assets(project_id, ordered)
        except Exception:
            for item in attempts:
                _remove_asset_files(item)
            raise
        learning = record_continual_learning(attempts, request.operation) if bool(request.parameters.get("learn_from_result", True)) else {"module": request.operation, "status": "disabled_for_request"}
        repair["learning"] = learning
        return ProcessResponse(project=project, source_asset_id=source.id, result=result, attempts=attempts, repair=repair, learning=learning)
    except (ProcessingError, AIModelError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/export", response_model=ExportResponse)
def export_project_asset(project_id: str, request: ExportRequest) -> ExportResponse:
    try:
        project = store.get_or_create(project_id)
        source = next((item for item in project.assets if item.id == request.asset_id), None)
        if source is None:
            raise HTTPException(status_code=404, detail="Исходный файл не найден в проекте")
        if project.workspace.get("active_asset_id") != source.id:
            project = store.set_active_asset(project_id, source.id)
        result = export_asset(source, request.format, request.parameters)
        try:
            project = store.add_assets(project_id, [result])
        except Exception:
            _remove_asset_files(result)
            raise
        learning = record_continual_learning([result], "export") if bool(request.parameters.get("learn_from_result", True)) else {"module": "export", "status": "disabled_for_request"}
        return ExportResponse(project=project, source_asset_id=source.id, result=result, learning=learning)
    except (ExportError, AIModelError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}/assets", response_model=ProjectRecord)
def clear_project_assets(project_id: str) -> ProjectRecord:
    try:
        project, removed = store.clear_assets(project_id)
    except (ValueError, ProjectStoreError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    still_referenced = store.referenced_storage_names(exclude_project_id=project_id)
    for asset in removed:
        for directory, name in ((settings.upload_dir, asset.stored_name), (settings.preview_dir, asset.preview_name)):
            if name in still_referenced:
                continue
            path = directory / name
            if path.exists():
                path.unlink()
    return project


@app.post("/api/assets/{asset_id}/ai/analyze")
def analyze_asset(asset_id: str, module: str = "information") -> dict[str, object]:
    project, asset = _get_asset(asset_id)
    image = _asset_image(asset)
    engine = get_ai_engine()
    normalized = module.strip().lower()
    if normalized in {"upload", "information"}:
        analysis = engine.analyze(image, module="upload")
    elif normalized == "improve":
        analysis = engine.recommend_restoration(image, module="improve")
    elif normalized == "extract":
        _, analysis = engine.segment_print(image, threshold=0.48, feather=0.0, module="extract")
    elif normalized == "selection":
        _, analysis = engine.segment_subject(image, threshold=0.50, feather=0.0, module="selection")
    elif normalized == "cleanup":
        _, analysis = engine.segment_subject(image, threshold=0.50, feather=0.0, module="cleanup")
    elif normalized == "halftone":
        analysis = engine.recommend_halftone(image, module="halftone")
    elif normalized == "vector":
        analysis = engine.recommend_vector(image, module="vector")
    elif normalized == "geometry":
        analysis = engine.recommend_size(image, module="geometry")
    elif normalized == "export":
        analysis = engine.recommend_export(image, module="export")
    elif normalized == "qa":
        analysis = engine.preflight(image, asset.operation or "upload", module="qa")
    else:
        raise HTTPException(status_code=422, detail="Неизвестный AI-модуль")
    asset.ai = {**asset.ai, "manual_analysis": analysis, f"manual_analysis_{normalized}": analysis}
    store.save(project)
    return analysis


@app.get("/api/assets/{asset_id}/ai/explain")
def explain_asset(asset_id: str) -> dict[str, object]:
    _, asset = _get_asset(asset_id)
    image = _asset_image(asset)
    return get_ai_engine().explain(image, asset.operation)


@app.get("/api/assets/{asset_id}/preview")
def asset_preview(asset_id: str) -> FileResponse:
    _, asset = _get_asset(asset_id)
    if asset.format == "SVG":
        path = settings.upload_dir / asset.stored_name
        return FileResponse(path, media_type="image/svg+xml", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})
    path = settings.preview_dir / asset.preview_name
    return FileResponse(path, media_type="image/png")


@app.get("/api/assets/{asset_id}/file")
def asset_file(asset_id: str) -> FileResponse:
    _, asset = _get_asset(asset_id)
    path = settings.upload_dir / asset.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")


# Wrap the fully configured FastAPI application so the byte limiter runs before
# BaseHTTPMiddleware and request parsers, including for chunked bodies.
app = RequestBodyLimitMiddleware(app)
