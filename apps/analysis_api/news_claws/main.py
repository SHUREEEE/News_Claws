from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .adapters.llm import LLMProviderError
from .catalog import bootstrap_catalog
from .config import Settings, get_settings
from .database import get_db, session_factory, upgrade_database
from .domain.llm import LLMContractError
from .domain.security import UnsafeUrlError
from .models import (
    AuditLog,
    Entity,
    Industry,
    Notification,
    PipelineJob,
    Report,
    Source,
    Subscription,
)
from .notifications import (
    create_subscription,
    dispatch_pending_notifications,
    update_subscription,
)
from .scheduler import collection_loop
from .schemas import (
    EventLockRequest,
    FeedbackCreate,
    IngestionRequest,
    ManualIngestionRequest,
    MergeEventsRequest,
    ReanalyzeRequest,
    SourceCreate,
    SourceUpdate,
    SplitEventRequest,
    SubscriptionCreate,
    SubscriptionUpdate,
)
from .services import (
    create_source,
    event_detail,
    ingest_manual_url,
    list_events,
    merge_events,
    pull_sources,
    reanalyze_event,
    seed_demo,
    set_event_lock,
    split_event,
    submit_feedback,
    system_summary,
    test_source,
    update_source,
)

logger = logging.getLogger("news_claws")
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
collection_lock = asyncio.Lock()
mimetypes.add_type("application/javascript", ".js")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s service=analysis-api %(message)s",
    )
    upgrade_database()
    with session_factory()() as session:
        bootstrap_catalog(
            session,
            settings.config_dir,
            include_demo=settings.seed_demo,
        )
        if settings.seed_demo:
            seeded = seed_demo(session, settings)
            if seeded:
                logger.info("seeded_demo_events count=%s", len(seeded))

    scheduler_stop = asyncio.Event()
    scheduler_task = (
        asyncio.create_task(
            collection_loop(settings, scheduler_stop, collection_lock),
            name="news-claws-collection-scheduler",
        )
        if settings.scheduler_enabled
        else None
    )
    try:
        yield
    finally:
        scheduler_stop.set()
        if scheduler_task is not None:
            await scheduler_task


app = FastAPI(
    title="News Claws Analysis API",
    version="0.1.1",
    description="Evidence-first news clustering, verification and impact analysis",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")


def settings_dependency() -> Settings:
    return get_settings()


def _host_is_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    normalized = host.rstrip(".").lower()
    return any(
        item == "*"
        or normalized == item
        or (item.startswith("*.") and normalized.endswith(item[1:]))
        for item in allowed_hosts
    )


def _problem(status_code: int, code: str, message: str, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Request failed",
            "status": status_code,
            "code": code,
            "message": message,
            "trace_id": trace_id,
            "retryable": False,
        },
    )


@app.middleware("http")
async def production_guard(request: Request, call_next):
    settings = get_settings()
    request_id_header = request.headers.get("x-request-id", "")
    request_id = (
        request_id_header
        if request_id_header
        and len(request_id_header) <= 64
        and all(char.isalnum() or char in "-_." for char in request_id_header)
        else secrets.token_hex(16)
    )
    request.state.request_id = request_id
    request.state.actor = "anonymous"

    host = request.url.hostname or ""
    if not _host_is_allowed(host, settings.allowed_hosts):
        response = _problem(400, "HOST_NOT_ALLOWED", "Request host is not allowed", request_id)
    else:
        content_length = request.headers.get("content-length")
        try:
            declared_size = int(content_length) if content_length else 0
        except ValueError:
            declared_size = -1
        if declared_size < 0:
            response = _problem(
                400,
                "CONTENT_LENGTH_INVALID",
                "Content-Length must be a non-negative integer",
                request_id,
            )
        elif declared_size > settings.max_request_bytes:
            response = _problem(
                413, "REQUEST_TOO_LARGE", "Request body exceeds the configured limit", request_id
            )
        else:
            response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    if settings.app_env == "prod":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(
        "/api/v1/"
    ):
        client = request.client.host if request.client else "unknown"
        client_hash = hashlib.sha256(f"{settings.admin_token}:{client}".encode()).hexdigest()
        route = request.scope.get("route")
        action = getattr(route, "name", None) or f"{request.method} {request.url.path}"
        try:
            with session_factory()() as audit_session:
                audit_session.add(
                    AuditLog(
                        request_id=request_id,
                        actor=request.state.actor,
                        action=action,
                        method=request.method,
                        path=request.url.path,
                        status_code=response.status_code,
                        client_hash=client_hash,
                    )
                )
                audit_session.commit()
        except Exception:
            logger.exception("audit_log_write_failed request_id=%s", request_id)

    return response


def require_admin(
    request: Request,
    settings: Annotated[Settings, Depends(settings_dependency)],
    authorization: Annotated[str | None, Header()] = None,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> str:
    candidate = x_admin_token or ""
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
    if not candidate or not secrets.compare_digest(candidate, settings.admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid administrator token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.actor = "admin"
    return "admin"


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        media_type="application/problem+json",
        headers=exc.headers,
        content={
            "type": "about:blank",
            "title": "Request failed",
            "status": exc.status_code,
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
            "trace_id": getattr(request.state, "request_id", "local"),
            "retryable": exc.status_code >= 500,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        media_type="application/problem+json",
        content={
            "type": "about:blank",
            "title": "Validation failed",
            "status": 422,
            "code": "VALIDATION_ERROR",
            "message": "Request data did not match the API contract",
            "errors": jsonable_encoder(exc.errors()),
            "trace_id": getattr(request.state, "request_id", "local"),
            "retryable": False,
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok", "service": "analysis-api"}


@app.get("/health/ready")
def health_ready(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    session.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "trendradar": "enabled" if settings.trendradar_enabled else "disabled",
        "search": settings.search_provider,
        "analysis": f"{settings.llm_provider}:{settings.llm_model}",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
    q: str | None = None,
    verification: str | None = None,
    region: str | None = None,
    language: str | None = None,
    source_id: str | None = None,
    industry_id: str | None = None,
    company_id: str | None = None,
    direction: str | None = None,
    strength: str | None = None,
    dataset: str = "all",
) -> HTMLResponse:
    demo = True if dataset == "demo" else False if dataset == "live" else None
    events = list_events(
        session,
        query=q,
        verification_status=verification,
        region=region,
        language=language,
        source_id=source_id,
        industry_id=industry_id,
        company_id=company_id,
        direction=direction,
        strength=strength,
        demo=demo,
    )
    source_options = list(
        session.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.name))
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page": "events",
            "events": events,
            "summary": system_summary(session, settings),
            "source_options": source_options,
            "industry_options": list(session.scalars(select(Industry).order_by(Industry.name))),
            "region_options": sorted({source.region for source in source_options}),
            "language_options": sorted({source.language for source in source_options}),
            "filters": {
                "q": q or "",
                "verification": verification or "",
                "region": region or "",
                "language": language or "",
                "source_id": source_id or "",
                "industry_id": industry_id or "",
                "company_id": company_id or "",
                "direction": direction or "",
                "strength": strength or "",
                "dataset": dataset,
            },
        },
    )


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(
    event_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    try:
        detail = event_detail(session, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name="event_detail.html",
        context={"page": "events", **detail},
    )


@app.get("/sources", response_class=HTMLResponse)
def sources_page(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    sources = list(session.scalars(select(Source).order_by(Source.is_demo.desc(), Source.name)))
    return templates.TemplateResponse(
        request=request,
        name="sources.html",
        context={"page": "sources", "sources": sources},
    )


@app.get("/system", response_class=HTMLResponse)
def system_page(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> HTMLResponse:
    jobs = list(
        session.scalars(select(PipelineJob).order_by(PipelineJob.updated_at.desc()).limit(20))
    )
    return templates.TemplateResponse(
        request=request,
        name="system.html",
        context={"page": "system", "summary": system_summary(session, settings), "jobs": jobs},
    )


@app.get("/subscriptions", response_class=HTMLResponse)
def subscriptions_page(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    industries = list(session.scalars(select(Industry).order_by(Industry.name)))
    return templates.TemplateResponse(
        request=request,
        name="subscriptions.html",
        context={"page": "subscriptions", "industries": industries},
    )


def source_payload(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "owner": source.owner,
        "region": source.region,
        "language": source.language,
        "source_type": source.source_type,
        "tier": source.tier,
        "official": source.official,
        "method": source.method,
        "entry_url": source.entry_url,
        "fallback_url": source.fallback_url,
        "schedule": source.schedule,
        "timezone": source.timezone,
        "content_policy": source.content_policy,
        "parser": source.parser,
        "compliance_notes": source.compliance_notes,
        "contact_owner": source.contact_owner,
        "enabled": source.enabled,
        "is_demo": source.is_demo,
        "last_success_at": source.last_success_at,
        "consecutive_failures": source.consecutive_failures,
        "last_error": source.last_error,
    }


@app.get("/api/v1/sources", dependencies=[Depends(require_admin)])
def api_sources(
    session: Annotated[Session, Depends(get_db)],
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    query = select(Source).order_by(Source.name)
    if enabled is not None:
        query = query.where(Source.enabled.is_(enabled))
    return [source_payload(source) for source in session.scalars(query)]


@app.post("/api/v1/sources", status_code=201, dependencies=[Depends(require_admin)])
def api_create_source(
    payload: SourceCreate,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        source = create_source(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return source_payload(source)


@app.patch("/api/v1/sources/{source_id}", dependencies=[Depends(require_admin)])
def api_update_source(
    source_id: str,
    payload: SourceUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        return source_payload(update_source(session, source, payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/sources/{source_id}/test", dependencies=[Depends(require_admin)])
async def api_test_source(
    source_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        return await test_source(session, source, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Source test failed: {exc}") from exc


@app.post("/api/v1/ingestion/pull", dependencies=[Depends(require_admin)])
async def api_pull(
    payload: IngestionRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    async with collection_lock:
        results = await pull_sources(
            session, settings, payload.source_ids, payload.max_items_per_source
        )
    return {"results": results, "source_count": len(results)}


@app.post("/api/v1/ingestion/url", status_code=201, dependencies=[Depends(require_admin)])
async def api_ingest_url(
    payload: ManualIngestionRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    source = session.get(Source, payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.is_demo:
        raise HTTPException(status_code=400, detail="Manual URLs require a non-demo source")
    try:
        return await ingest_manual_url(session, source, payload.url, settings)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Manual URL ingestion failed: {exc}") from exc


@app.get("/api/v1/events", dependencies=[Depends(require_admin)])
def api_events(
    session: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    verification: str | None = None,
    region: str | None = None,
    language: str | None = None,
    source_id: str | None = None,
    industry_id: str | None = None,
    company_id: str | None = None,
    direction: str | None = Query(
        default=None,
        pattern="^(positive|negative|mixed|neutral|unknown)$",
    ),
    strength: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    dataset: str = Query(default="all", pattern="^(all|demo|live)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    demo = True if dataset == "demo" else False if dataset == "live" else None
    items = list_events(
        session,
        query=q,
        verification_status=verification,
        region=region,
        language=language,
        source_id=source_id,
        industry_id=industry_id,
        company_id=company_id,
        direction=direction,
        strength=strength,
        demo=demo,
        limit=limit,
    )
    return {"items": items, "next_cursor": None}


@app.get("/api/v1/events/{event_id}", dependencies=[Depends(require_admin)])
def api_event_detail(
    event_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return jsonable_encoder(event_detail(session, event_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/events/{event_id}/reanalyze", dependencies=[Depends(require_admin)])
async def api_reanalyze(
    event_id: str,
    payload: ReanalyzeRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    try:
        report = await reanalyze_event(session, event_id, settings)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMContractError as exc:
        raise HTTPException(status_code=502, detail=f"Model analysis failed: {exc.code}") from exc
    except (LLMProviderError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail="Model provider is unavailable") from exc
    return {"event_id": event_id, "report_id": report.id, "version": report.version}


@app.patch("/api/v1/events/{event_id}/lock", dependencies=[Depends(require_admin)])
def api_set_event_lock(
    event_id: str,
    payload: EventLockRequest,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        event = set_event_lock(
            session,
            event_id,
            locked=payload.locked,
            reason=payload.reason,
            actor=payload.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": event.id, "locked": event.locked}


@app.post("/api/v1/events/merge", dependencies=[Depends(require_admin)])
async def api_merge_events(
    payload: MergeEventsRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, str | None]:
    try:
        result = await merge_events(session, payload.event_ids, payload.reason, settings)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "event_id": result.event_id,
        "analysis_status": result.analysis_status,
        "analysis_error": result.analysis_error,
    }


@app.post("/api/v1/events/{event_id}/split", dependencies=[Depends(require_admin)])
async def api_split_event(
    event_id: str,
    payload: SplitEventRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, str | None]:
    try:
        result = await split_event(session, event_id, payload.article_ids, payload.reason, settings)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "event_id": result.event_id,
        "analysis_status": result.analysis_status,
        "analysis_error": result.analysis_error,
    }


@app.get("/api/v1/reports/{report_id}", dependencies=[Depends(require_admin)])
def api_report(
    report_id: str,
    session: Annotated[Session, Depends(get_db)],
    format: str = Query(default="json", pattern="^(json|markdown|html)$"),
) -> Response:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if format == "markdown":
        return PlainTextResponse(report.content_markdown, media_type="text/markdown; charset=utf-8")
    if format == "html":
        return HTMLResponse(report.content_html)
    return JSONResponse(report.content_json)


@app.post("/api/v1/feedback", status_code=201, dependencies=[Depends(require_admin)])
def api_feedback(
    payload: FeedbackCreate,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    feedback = submit_feedback(session, payload)
    return {"id": feedback.id, "created_at": feedback.created_at}


@app.get("/api/v1/audit-logs", dependencies=[Depends(require_admin)])
def api_audit_logs(
    session: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    entries = list(
        session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    )
    return {"items": jsonable_encoder(entries), "next_cursor": None}


@app.get("/api/v1/subscriptions", dependencies=[Depends(require_admin)])
def api_subscriptions(
    session: Annotated[Session, Depends(get_db)],
    enabled: bool | None = None,
) -> dict[str, Any]:
    query = select(Subscription).order_by(Subscription.created_at.desc())
    if enabled is not None:
        query = query.where(Subscription.enabled.is_(enabled))
    return {"items": jsonable_encoder(list(session.scalars(query)))}


@app.get("/api/v1/catalog/companies", dependencies=[Depends(require_admin)])
def api_company_catalog(
    session: Annotated[Session, Depends(get_db)],
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    companies = list(
        session.scalars(
            select(Entity)
            .where(
                Entity.entity_type == "company",
                Entity.canonical_name.ilike(f"%{q}%"),
            )
            .order_by(Entity.canonical_name)
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": company.id,
                "name": company.canonical_name,
                "country": company.country,
                "identifiers": company.identifiers_json,
            }
            for company in companies
        ]
    }


@app.post("/api/v1/subscriptions", status_code=201, dependencies=[Depends(require_admin)])
def api_create_subscription(
    payload: SubscriptionCreate,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return jsonable_encoder(create_subscription(session, payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/v1/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
def api_update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        return jsonable_encoder(update_subscription(session, subscription, payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(
    "/api/v1/subscriptions/{subscription_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def api_disable_subscription(
    subscription_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> Response:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.enabled = False
    session.commit()
    return Response(status_code=204)


@app.get("/api/v1/notifications", dependencies=[Depends(require_admin)])
def api_notifications(
    session: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    notifications = list(
        session.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(limit))
    )
    return {"items": jsonable_encoder(notifications), "next_cursor": None}


@app.post("/api/v1/notifications/dispatch", dependencies=[Depends(require_admin)])
def api_dispatch_notifications(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> dict[str, Any]:
    return dispatch_pending_notifications(session, settings)


@app.get("/api/v1/jobs", dependencies=[Depends(require_admin)])
def api_jobs(
    session: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    jobs = list(
        session.scalars(select(PipelineJob).order_by(PipelineJob.updated_at.desc()).limit(limit))
    )
    return {"items": jsonable_encoder(jobs), "next_cursor": None}
