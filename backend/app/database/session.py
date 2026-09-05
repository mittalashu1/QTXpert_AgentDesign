"""Async SQLAlchemy engine / session management.

Neon can close an idle connection while a Render instance is sleeping or
recovering. Session cleanup is therefore deliberately best-effort: a timeout
while rolling back or closing must not replace the original HTTP/database
error with an unhandled exception from FastAPI's dependency finalizer.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class ResilientAsyncSession(AsyncSession):
    """Async session whose context-manager cleanup is bounded.

    A number of background services use ``async with AsyncSessionLocal()``
    directly rather than the FastAPI dependency. Keep those paths safe too:
    closing a dead Neon connection is best-effort and must not become a new
    unhandled exception after the request/worker has already handled the
    database failure.
    """

    async def close(self) -> None:
        try:
            await asyncio.wait_for(
                super().close(),
                timeout=get_settings().DB_CLOSE_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - provider/network specific
            logger.warning("Database session close skipped after connection failure: %s", exc)
            _invalidate_sync_session(self)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def _build_engine() -> AsyncEngine:
    return create_async_engine(
        settings.POSTGRES_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
        connect_args={
            "timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
            "command_timeout": settings.DB_COMMAND_TIMEOUT_SECONDS,
        },
        pool_pre_ping=True,
        future=True,
    )


engine: AsyncEngine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=ResilientAsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await _safe_rollback(session)
        raise
    finally:
        await _safe_close(session)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for non-request contexts (agents, scripts, celery)."""
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await _safe_rollback(session)
        raise
    finally:
        await _safe_close(session)


async def _safe_rollback(session: AsyncSession) -> None:
    """Rollback without masking the exception that caused request failure."""
    try:
        await asyncio.wait_for(
            session.rollback(),
            timeout=settings.DB_CLOSE_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - provider/network specific
        logger.warning("Database rollback skipped after connection failure: %s", exc)
        _invalidate_sync_session(session)


async def _safe_close(session: AsyncSession) -> None:
    """Close a session within a small budget and invalidate dead connections."""
    try:
        # ResilientAsyncSession already wraps its override; call the base
        # implementation here to keep the timeout single-layered. The fallback
        # keeps this helper useful with simple fakes in unit tests.
        close = (
            AsyncSession.close(session)
            if isinstance(session, ResilientAsyncSession)
            else session.close()
        )
        await asyncio.wait_for(
            close,
            timeout=settings.DB_CLOSE_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - provider/network specific
        logger.warning("Database session close skipped after connection failure: %s", exc)
        _invalidate_sync_session(session)


def _invalidate_sync_session(session: AsyncSession) -> None:
    """Invalidate a broken connection without another network round trip."""
    try:
        session.sync_session.invalidate()
    except Exception:  # pragma: no cover - defensive SQLAlchemy compatibility
        logger.debug("Unable to invalidate failed database session", exc_info=True)
