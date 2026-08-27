"""Authentication and administrator-managed user lifecycle endpoints."""
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user, require_roles
from app.auth.jwt import create_token, decode_token
from app.auth.security import hash_password, verify_password
from app.config import Settings, get_settings
from app.database.models.config_and_audit import AuditLog
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.schemas.auth import (
    AdminBootstrap, PasswordChange, PasswordReset, TokenPair,
    TokenRefreshRequest, UserCreate, UserLogin, UserOut, UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(db: AsyncSession, actor: User | None, action: str, target: User, request: Request, detail: dict | None = None) -> None:
    db.add(AuditLog(
        user_id=actor.id if actor else None, action=action, resource_type="user",
        resource_id=str(target.id), detail=detail, ip_address=_client_ip(request),
    ))


async def _get_user_or_404(db: AsyncSession, user_id: UUID) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _ensure_not_removing_last_admin(db: AsyncSession, target: User, role: UserRole | None, is_active: bool | None) -> None:
    remains_active_admin = (role or target.role) == UserRole.ADMIN and (is_active if is_active is not None else target.is_active)
    if target.role != UserRole.ADMIN or not target.is_active or remains_active_admin:
        return
    count = (await db.execute(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))).scalars().all()
    if len(count) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot deactivate or demote the last active administrator")


@router.post("/bootstrap-admin", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def bootstrap_admin(
    payload: AdminBootstrap, request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Create exactly the first administrator, guarded by a deployment secret."""
    if not settings.ADMIN_BOOTSTRAP_TOKEN or not hmac.compare_digest(payload.bootstrap_token, settings.ADMIN_BOOTSTRAP_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin bootstrap is not authorized")
    existing_admin = (await db.execute(select(User.id).where(User.role == UserRole.ADMIN))).first()
    if existing_admin:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An administrator already exists")
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None:
        user = User(email=payload.email, full_name=payload.full_name, hashed_password=hash_password(payload.password), role=UserRole.ADMIN)
        db.add(user)
        await db.flush()
        action = "admin_bootstrapped"
    else:
        user.full_name = payload.full_name
        user.hashed_password = hash_password(payload.password)
        user.role = UserRole.ADMIN
        user.is_active = True
        user.token_version += 1
        action = "existing_user_bootstrapped_as_admin"
    _audit(db, None, action, user, request, {"email": user.email})
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/register", status_code=status.HTTP_403_FORBIDDEN)
async def register_disabled():
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Public registration is disabled. Contact an administrator.")


@router.post("/login", response_model=TokenPair)
async def login(payload: UserLogin, db: Annotated[AsyncSession, Depends(get_db_session)], settings: Annotated[Settings, Depends(get_settings)]):
    normalized_email = str(payload.email).strip().lower()
    user = (await db.execute(select(User).where(func.lower(User.email) == normalized_email))).scalar_one_or_none()
    if user is None or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return TokenPair(access_token=create_token(settings, str(user.id), "access", user.token_version), refresh_token=create_token(settings, str(user.id), "refresh", user.token_version))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: Annotated[User, Depends(get_current_user)]):
    return None


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: TokenRefreshRequest, db: Annotated[AsyncSession, Depends(get_db_session)], settings: Annotated[Settings, Depends(get_settings)]):
    claims = decode_token(settings, payload.refresh_token, expected_type="refresh")
    try:
        user = await _get_user_or_404(db, UUID(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject claim") from exc
    if not user.is_active or claims.get("ver", 0) != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
    return TokenPair(access_token=create_token(settings, str(user.id), "access", user.token_version), refresh_token=create_token(settings, str(user.id), "refresh", user.token_version))


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(payload: PasswordChange, request: Request, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    if not user.hashed_password or not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if verify_password(payload.new_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must differ from the current password")
    user.hashed_password, user.token_version = hash_password(payload.new_password), user.token_version + 1
    _audit(db, user, "password_changed", user, request)
    await db.commit()


@router.get("/users", response_model=list[UserOut])
async def list_users(admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))], db: Annotated[AsyncSession, Depends(get_db_session)]):
    return (await db.execute(select(User).order_by(User.email))).scalars().all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, request: Request, admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))], db: Annotated[AsyncSession, Depends(get_db_session)]):
    if (await db.execute(select(User.id).where(User.email == payload.email))).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(email=payload.email, full_name=payload.full_name, hashed_password=hash_password(payload.password), role=payload.role)
    db.add(user)
    await db.flush()
    _audit(db, admin, "user_created", user, request, {"email": user.email, "role": user.role.value})
    await db.commit(); await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: UUID, payload: UserUpdate, request: Request, admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))], db: Annotated[AsyncSession, Depends(get_db_session)]):
    target = await _get_user_or_404(db, user_id)
    if target.id == admin.id and (payload.role is not None or payload.is_active is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Administrators cannot change their own role or active status")
    await _ensure_not_removing_last_admin(db, target, payload.role, payload.is_active)
    changed = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        if getattr(target, field) != value:
            changed[field] = value.value if isinstance(value, UserRole) else value
            setattr(target, field, value)
    if changed:
        if "role" in changed or "is_active" in changed:
            target.token_version += 1
        _audit(db, admin, "user_updated", target, request, changed)
        await db.commit(); await db.refresh(target)
    return target


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(user_id: UUID, payload: PasswordReset, request: Request, admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))], db: Annotated[AsyncSession, Depends(get_db_session)]):
    target = await _get_user_or_404(db, user_id)
    target.hashed_password, target.token_version = hash_password(payload.new_password), target.token_version + 1
    _audit(db, admin, "password_reset_by_admin", target, request)
    await db.commit()
