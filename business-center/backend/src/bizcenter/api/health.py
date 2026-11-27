from fastapi import APIRouter, Depends, HTTPException

from ..db import Database
from ..deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: Database = Depends(get_db)) -> dict[str, str]:
    try:
        await db.ping()
    except Exception as exc:
        raise HTTPException(503, "Veritabanına ulaşılamıyor") from exc
    return {"status": "ready"}
