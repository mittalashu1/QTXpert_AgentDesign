from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.database.models.user import User
from app.database.repositories.generation_run_repository import GenerationRunRepository
from app.database.session import get_db_session
from app.exports.registry import get_exporter
from app.schemas.test_case import ExportRequest

router = APIRouter(tags=["export"])


@router.post("/export")
async def export_test_cases(
    payload: ExportRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo = GenerationRunRepository(db)
    run = await repo.get(payload.generation_run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found")

    try:
        exporter = get_exporter(payload.format)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    result = exporter.export(run)
    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
