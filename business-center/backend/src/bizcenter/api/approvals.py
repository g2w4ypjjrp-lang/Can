from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error

router = APIRouter(prefix="/api", tags=["approvals"])

_COLS = """id, platform, action, reason, expected_outcome, risk_level, cost_amount, cost_currency,
           before_state, after_state, status, decided_by, decided_at, decision_note,
           expires_at, created_at"""


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
    from ..executor import ACTIONS, payload_hash, validate_payload
    if body.action not in ACTIONS:
        raise HTTPException(422, "Desteklenmeyen işlem")
    is_etsy = body.action.startswith("etsy")
    payload = {("listing_id" if is_etsy else "video_id"): int(body.target_id) if is_etsy and body.target_id.isdigit()
               else body.target_id, "changes": body.changes}
    try:
        validate_payload(body.action, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with db.user_tx(user) as conn:
        ok = await (await conn.execute("select app.has_role(%s, array['owner','admin']) as ok", (org_id,))).fetchone()
        if not ok or not ok["ok"]:
            raise HTTPException(403, "Yönetici yetkisi gerekli")
        if is_etsy:
            cur = await (await conn.execute("select title, description, tags from etsy_listings where organization_id=%s"
                                            " and etsy_listing_id=%s", (org_id, payload["listing_id"]))).fetchone()
        else:
            cur = await (await conn.execute("select title, description, tags from youtube_videos where organization_id=%s"
                                            " and youtube_video_id=%s", (org_id, payload["video_id"]))).fetchone()
        if cur is None:
            raise HTTPException(404, "Hedef bulunamadı (önce senkronlayın)")
        before = {k: cur[k] for k in body.changes}
    # approvals tablosu istemci rolüne kapalıdır; kayıt servis bağlantısıyla, kullanıcı adına açılır.
    async with db.pool.connection() as conn:
        row = await (await conn.execute(
            """insert into approvals(organization_id, platform, action, reason, expected_outcome, risk_level,
                   before_state, after_state, payload, payload_hash, expires_at)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now() + make_interval(hours => %s)) returning id""",
            (org_id, ACTIONS[body.action]["platform"], body.action, body.reason, body.expected_outcome,
             ACTIONS[body.action]["risk"], Jsonb(before), Jsonb(body.changes), Jsonb(payload),
             payload_hash(body.action, payload), body.expires_hours))).fetchone()
        await conn.execute("insert into audit_logs(organization_id, actor_user_id, action, target_type, target_id)"
                           " values (%s,%s,'approval.proposed','approval',%s)", (org_id, user.id, str(row["id"])))
        await conn.commit()
    return {"id": row["id"], "status": "pending"}


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
