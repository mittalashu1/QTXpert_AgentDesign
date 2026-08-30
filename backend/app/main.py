"""FastAPI application entrypoint."""
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RateLimitMiddleware
from app.api.routes import (
    auth,
    autopilot,
    document_intelligence,
    executions,
    execution_plans,
    export,
    health,
    requirements,
    retention,
    settings,
    test_cases,
    uploads,
    usage,
)
from app.config import get_settings
from app.database.session import AsyncSessionLocal
from app.services.data_retention import cleanup_generated_data
from app.services.autopilot_recovery import recover_interrupted_autopilot_jobs

settings_obj = get_settings()

logging.basicConfig(level=settings_obj.LOG_LEVEL)
# Androguard is very verbose at DEBUG and can flood production logs while parsing
# large APK resource tables. Keep application logs useful without affecting analysis.
logging.getLogger("androguard").setLevel(logging.WARNING)
logger = logging.getLogger("qtxpert")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings_obj.APP_NAME,
        version="0.4.0-document-intelligence",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings_obj.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware, settings=settings_obj)

    prefix = settings_obj.API_V1_PREFIX
    app.include_router(auth.router, prefix=prefix)
    app.include_router(requirements.router, prefix=prefix)
    app.include_router(retention.router, prefix=prefix)
    app.include_router(uploads.router, prefix=prefix)
    app.include_router(document_intelligence.router, prefix=prefix)
    app.include_router(test_cases.router, prefix=prefix)
    app.include_router(executions.router, prefix=prefix)
    app.include_router(execution_plans.router, prefix=prefix)
    app.include_router(autopilot.router, prefix=prefix)
    app.include_router(export.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)
    app.include_router(health.router, prefix=prefix)

    @app.on_event("startup")
    async def recover_autopilot_after_restart() -> None:
        # Recovery is opt-in. A large APK replay belongs on a worker/queue; doing
        # it automatically on the web instance can starve authentication during
        # Render deploys and trigger the 512 MiB memory limit.
        if not settings_obj.AUTOPILOT_RECOVERY_ENABLED:
            logger.info("Autopilot restart recovery disabled; skipping startup scan")
            app.state.autopilot_recovery = None
            return
        app.state.autopilot_recovery = asyncio.create_task(
            recover_interrupted_autopilot_jobs(settings_obj)
        )

    @app.on_event("startup")
    async def schedule_generated_data_retention() -> None:
        # Retention is intentionally opt-in and detached from HTTP startup.
        # The normal production path is the admin-confirmed endpoint or the
        # one-shot script; this hook is available only for an explicitly
        # configured single-instance deployment/cron replacement.
        if not (
            settings_obj.DATA_RETENTION_ENABLED
            and settings_obj.DATA_RETENTION_RUN_ON_STARTUP
        ):
            logger.info("Generated-data startup retention disabled; skipping cleanup")
            app.state.data_retention = None
            return

        async def _run_retention() -> None:
            try:
                async with AsyncSessionLocal() as session:
                    await cleanup_generated_data(session, settings_obj, dry_run=False)
            except Exception:
                logger.exception("Generated-data startup retention failed")

        app.state.data_retention = asyncio.create_task(_run_retention())

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected error occurred."},
        )

    @app.get("/")
    async def root():
        return {"service": settings_obj.APP_NAME, "status": "running"}

    @app.head("/")
    async def root_head():
        # Render may probe a web service with HEAD / when no explicit health
        # path is configured. FastAPI does not automatically register HEAD for
        # a GET route, so make that probe a clean 200 response.
        return None

    return app


app = create_app()

