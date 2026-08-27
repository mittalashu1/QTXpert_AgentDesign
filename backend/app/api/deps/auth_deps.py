"""Reusable FastAPI dependencies for authentication and authorization."""
import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token
from app.config import Settings, get_settings
from app.database.models.user import User, UserRole
from app.database.session import get_db_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logger = logging.getLogger(__name__)


def _degraded_session_user(user_id: UUID, token_version: object) -> User:
    """Build a non-persistent identity for the emergency Autopilot mode.

    The JWT signature still has to validate before this helper is reached.  We
    deliberately grant only the ordinary QA engineer role and never use this
    identity for administrator/project-management routes.
    """
    try:
        version = int(token_version or 0)
    except (TypeError, ValueError):
        version = 0
    return User(
        id=user_id,
        email=f"autopilot-degraded-{user_id}@qtxpert.local",
        full_name="Autopilot degraded session",
        role=UserRole.QA_ENGINEER,
        is_active=True,
        token_version=version,
    )


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    payload = decode_token(settings, token, expected_type="access")
    user_id = payload.get("sub")
    try:
        parsed_user_id = UUID(user_id)
        result = await db.execute(select(User).where(User.id == parsed_user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject claim"
        ) from exc
    except Exception as exc:  # pragma: no cover - exercised by an unavailable provider
        try:
            await db.rollback()
        except Exception:
            pass
        degraded_paths = (
            f"{settings.API_V1_PREFIX}/autopilot",
            f"{settings.API_V1_PREFIX}/auth/me",
        )
        if settings.AUTOPILOT_DEGRADED_MODE_ENABLED and any(
            request.url.path == path or request.url.path.startswith(f"{path}/")
            for path in degraded_paths
        ):
            logger.warning(
                "Authentication database unavailable; accepting signed JWT in "
                "degraded Autopilot mode: %s",
                exc,
            )
            return _degraded_session_user(parsed_user_id, payload.get("ver", 0))
        logger.warning("Authentication database unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is temporarily unavailable because the database "
                "provider rejected the connection. Check the database plan/quota and retry."
            ),
        ) from exc
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid"
        )
    return user


def require_roles(*allowed_roles: UserRole):
    """Dependency factory enforcing role-based access control on a route."""

    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in allowed_roles]}",
            )
        return user

    return _check
