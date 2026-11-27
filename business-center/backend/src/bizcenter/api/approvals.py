from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error

router = APIRouter(prefix="/api", tags=["approvals"])

_COLS = """id, platform, action, reason, expected_outcome, risk_level, cost_amount, cost_currency,
           before_state, after_state, status, decided_by, decided_at, decision_note,
           expires_at, created_at"""


class Decision(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)


@router.get("/organizations/{org_id}/approvals")
async def list_approvals(
    org_id: UUID,
    status: Literal["pending", "approved", "rejected", "expired", "executed", "failed"] | None = None,
    user: CurrentUser = Depends(current_user), db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            f"select {_COLS} from approvals where organization_id = %s"  # noqa: S608
            " and (%s::text is null or status = %s) order by created_at desc limit 200",
            (org_id, status, status))
        return await cur.fetchall()


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: UUID, body: Decision, user: CurrentUser = Depends(current_user),
                 db: Database = Depends(get_db)) -> dict[str, Any]:
    """Karar veritabanındaki app.decide_approval ile verilir: rol, süre ve durum orada doğrulanır."""
    try:
        async with db.user_tx(user) as conn:
            cur = await conn.execute(
                f"select {_COLS} from app.decide_approval(%s, %s, %s)",  # noqa: S608
                (approval_id, body.approve, body.note))
            row = await cur.fetchone()
    except Exception as exc:
        raise db_error(exc) from exc
    if row is None:
        raise HTTPException(500, "Beklenmeyen boş sonuç")
    return row
