from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.auth.jwt import create_token, decode_token
from app.auth.security import hash_password, verify_password
from app.config import Settings, get_settings
from app.database.models.user import User
from app.database.session import get_db_session
from app.schemas.auth import TokenPair, TokenRefreshRequest, UserCreate, UserLogin, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
async def login(
    payload: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not user.hashed_password or not verify_password(
        payload.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    return TokenPair(
        access_token=create_token(settings, str(user.id), "access"),
        refresh_token=create_token(settings, str(user.id), "refresh"),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: Annotated[User, Depends(get_current_user)]):
    # Stateless JWT: logout is enforced client-side by discarding tokens.
    # A denylist keyed by `jti` in Redis can be added here if immediate
    # server-side revocation becomes a requirement.
    return None


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    payload: TokenRefreshRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    claims = decode_token(settings, payload.refresh_token, expected_type="refresh")
    subject = claims["sub"]
    return TokenPair(
        access_token=create_token(settings, subject, "access"),
        refresh_token=create_token(settings, subject, "refresh"),
    )


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return user
