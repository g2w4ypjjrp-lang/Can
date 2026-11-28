from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error

router = APIRouter(prefix="/api", tags=["approvals"])

_COLS = """id, platform, action, reason, expected_outcome, risk_level, cost_amount, cost_currency,
           before_state, after_state, status, decided_by, decided_at, decision_note,
           expires_at, created_at, task_id,
           (select name from agents g where g.id = requested_by_agent_id) as requested_by_agent"""


class Proposal(BaseModel):
    action: str = Field(max_length=60)
    target_id: str = Field(min_length=1, max_length=64)   # Etsy listing_id veya YouTube video_id
    changes: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)
    expected_outcome: str = Field(min_length=3, max_length=2000)
    expires_hours: int = Field(default=48, ge=1, le=168)


@router.post("/organizations/{org_id}/approvals", status_code=201)
async def propose(org_id: UUID, body: Proposal, user: CurrentUser = Depends(current_user),
                  db: Database = Depends(get_db)) -> dict[str, Any]:
    """Kritik bir değişikliği onaya sunar. Mevcut durum (öncesi) veritabanından okunur, istemciden alınmaz."""
    from ..executor import ProposalError, create_proposal
    async with db.user_tx(user) as conn:
        ok = await (await conn.execute("select app.has_role(%s, array['owner','admin']) as ok", (org_id,))).fetchone()
        if not ok or not ok["ok"]:
            raise HTTPException(403, "Yönetici yetkisi gerekli")
    try:
        aid = await create_proposal(db, org_id, body.action, body.target_id, body.changes, body.reason,
                                    body.expected_outcome, body.expires_hours, user_id=user.id)
    except ProposalError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return {"id": aid, "status": "pending"}


class DraftListing(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    description: str = Field(min_length=1, max_length=20000)
    price: float = Field(ge=0.2, le=50000)
    quantity: int = Field(default=999, ge=1, le=999)
    taxonomy_id: int = Field(gt=0)
    tags: list[str] = Field(default_factory=list, max_length=13)
    who_made: str = "i_did"
    reason: str = Field(default="Yeni ürün", max_length=2000)


@router.post("/organizations/{org_id}/approvals/etsy-draft", status_code=201)
async def propose_draft(org_id: UUID, body: DraftListing, user: CurrentUser = Depends(current_user),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
    from ..executor import ProposalError, create_proposal
    async with db.user_tx(user) as conn:
        ok = await (await conn.execute("select app.has_role(%s, array['owner','admin']) as ok", (org_id,))).fetchone()
        if not ok or not ok["ok"]:
            raise HTTPException(403, "Yönetici yetkisi gerekli")
    draft = body.model_dump(exclude={"reason"}) | {"when_made": "made_to_order"}
    try:
        aid = await create_proposal(db, org_id, "etsy.listing.create_draft", "", draft, body.reason,
                                    "Etsy'de taslak listeleme oluşur (yayınlanmaz)", user_id=user.id)
    except ProposalError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return {"id": aid, "status": "pending"}


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
async def decide(approval_id: UUID, body: Decision, request: Request, user: CurrentUser = Depends(current_user),
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
    if row["status"] == "approved":
        # Yürütme onaydan sonra; tüm doğrulamalar Executor içinde yeniden yapılır.
        from ..executor import Executor
        ex = Executor(db, request.app.state.settings, getattr(request.app.state, "http_transport", None))
        row["status"] = await ex.run(approval_id)
    return row
