from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import require_roles
from app.database.models.config_and_audit import ApiConfiguration
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.llm.base import LLMMessage, LLMProviderError
from app.llm.factory import get_llm_provider

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiConfigurationIn(BaseModel):
    name: str
    llm_provider: str
    llm_model: str
    is_active: bool = True


class ApiConfigurationOut(ApiConfigurationIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


class ProviderTestRequest(BaseModel):
    provider: str


class ProviderTestResult(BaseModel):
    provider: str
    healthy: bool
    detail: str = ""


@router.get("", response_model=List[ApiConfigurationOut])
async def list_configurations(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    result = await db.execute(select(ApiConfiguration))
    rows = result.scalars().all()
    return [
        ApiConfigurationOut(
            id=str(row.id),
            name=row.name,
            llm_provider=row.llm_provider,
            llm_model=row.llm_model,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.post("", response_model=ApiConfigurationOut, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    payload: ApiConfigurationIn,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    config = ApiConfiguration(**payload.model_dump())
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return ApiConfigurationOut(
        id=str(config.id),
        name=config.name,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        is_active=config.is_active,
    )


@router.post("/test-provider", response_model=ProviderTestResult)
async def test_provider(
    payload: ProviderTestRequest,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    try:
        provider = get_llm_provider(payload.provider)
        # Call complete() directly (not health_check()) so any Azure/OpenAI
        # error message actually propagates back to the UI instead of being
        # swallowed into a bare True/False by health_check()'s broad except.
        await provider.complete(
            [LLMMessage(role="user", content="ping")],
            max_tokens=5,
        )
        return ProviderTestResult(provider=payload.provider, healthy=True)
    except LLMProviderError as exc:
        return ProviderTestResult(provider=payload.provider, healthy=False, detail=str(exc))
