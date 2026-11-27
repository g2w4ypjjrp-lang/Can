from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error

router = APIRouter(prefix="/api", tags=["organizations"])


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user),
             db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            """select o.id, o.name, o.base_currency, m.role
                 from organization_members m join organizations o on o.id = m.organization_id
                where m.user_id = %s order by o.created_at""", (user.id,))
        orgs = await cur.fetchall()
    return {"id": user.id, "email": user.email, "organizations": orgs}


@router.post("/organizations", status_code=201)
async def create_org(body: OrgCreate, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)) -> dict[str, UUID]:
    try:
        async with db.user_tx(user) as conn:
            cur = await conn.execute("select app.create_organization(%s) as id", (body.name.strip(),))
            row = await cur.fetchone()
    except Exception as exc:
        raise db_error(exc) from exc
    if row is None:
        raise HTTPException(500, "Beklenmeyen boş sonuç")
    return {"id": row["id"]}


@router.get("/organizations/{org_id}/agents")
async def agents(org_id: UUID, user: CurrentUser = Depends(current_user),
                 db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            """select a.id, a.code, a.name, a.description, a.enabled,
                      d.code as department, d.name as department_name,
                      (select count(*) from tasks t where t.assigned_agent_id = a.id
                         and t.status in ('queued','running')) as active_tasks
                 from agents a join departments d on d.id = a.department_id
                where a.organization_id = %s order by d.code, a.name""", (org_id,))
        return await cur.fetchall()
