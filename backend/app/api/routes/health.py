from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session

router = APIRouter(tags=["health"])

@router.get("/health/live")
async def health_live():
    """Return a dependency-free liveness response for the process probe."""
    return {"status": "ok"}




@router.get("/health")
async def health(db: Annotated[AsyncSession, Depends(get_db_session)]):
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_status = f"error: {exc}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
    }
