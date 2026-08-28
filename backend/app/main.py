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
    settings,
    test_cases,
    uploads,
    usage,
)
from app.config import get_settings
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
        # Do not block HTTP startup while a large APK is restored from the durable
        # Upload Repository. The recovery task schedules bounded analysis workers.
        app.state.autopilot_recovery = asyncio.create_task(
            recover_interrupted_autopilot_jobs(settings_obj)
        )

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

