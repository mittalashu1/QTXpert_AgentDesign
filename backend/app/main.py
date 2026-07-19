"""FastAPI application entrypoint."""
import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RateLimitMiddleware
from app.api.routes import auth, export, health, requirements, settings, test_cases
from app.config import get_settings

settings_obj = get_settings()

logging.basicConfig(level=settings_obj.LOG_LEVEL)
logger = logging.getLogger("qtxpert")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings_obj.APP_NAME,
        version="0.1.0",
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
    app.include_router(test_cases.router, prefix=prefix)
    app.include_router(export.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(health.router, prefix=prefix)

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

    return app


app = create_app()
