from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db
from ..errors import db_error

router = APIRouter(prefix="/api", tags=["tasks"])

ACTIVE = ("queued", "running", "waiting_qc", "waiting_approval")


class TaskCreate(BaseModel):
    command: str = Field(min_length=3, max_length=4000)


@router.post("/organizations/{org_id}/tasks", status_code=201)
async def create_task(org_id: UUID, body: TaskCreate, request: Request,
                      user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    settings = request.app.state.settings
    cmd = body.command.strip()
    try:
        async with db.user_tx(user) as conn:
            cur = await conn.execute(
                "select app.has_role(%s, array['owner','admin']) as ok,"
                " (select count(*) from tasks where organization_id=%s and parent_task_id is null"
                "  and status = any(%s)) as active", (org_id, org_id, list(ACTIVE)))
            row = await cur.fetchone()
            if not row or not row["ok"]:
                raise HTTPException(403, "Görev vermek için yönetici yetkisi gerekli")
            if row["active"] >= settings.max_active_tasks_per_org:
                raise HTTPException(429, f"Aynı anda en fazla {settings.max_active_tasks_per_org} görev çalışabilir")
            cur = await conn.execute(
                "insert into tasks(organization_id, title, command, created_by) values (%s,%s,%s,%s)"
                " returning id, status, created_at", (org_id, cmd[:120], cmd, user.id))
            task = await cur.fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        raise db_error(exc) from exc
    if task is None:
        raise HTTPException(500, "Görev oluşturulamadı")
    request.app.state.dispatcher.enqueue(task["id"])
    return task


@router.get("/organizations/{org_id}/tasks")
async def list_tasks(org_id: UUID, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            """select t.id, t.title, t.status, t.error, t.created_at, t.completed_at,
                      a.name as current_agent, t.result->>'total_cost_usd' as cost_usd
                 from tasks t left join agents a on a.id = t.assigned_agent_id
                where t.organization_id = %s and t.parent_task_id is null
                order by t.created_at desc limit 100""", (org_id,))
        return await cur.fetchall()


@router.get("/tasks/{task_id}")
async def get_task(task_id: UUID, user: CurrentUser = Depends(current_user),
                   db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            """select t.id, t.organization_id, t.title, t.command, t.status, t.result, t.error,
                      t.created_at, t.completed_at, a.name as current_agent
                 from tasks t left join agents a on a.id = t.assigned_agent_id where t.id = %s""", (task_id,))
        task = await cur.fetchone()
        if task is None:
            raise HTTPException(404, "Görev bulunamadı")
        cur = await conn.execute(
            """select s.position, s.description, s.status, s.output, a.name as agent, a.code as agent_code
                 from task_steps s left join agents a on a.id = s.agent_id
                where s.task_id = %s order by s.position""", (task_id,))
        task["steps"] = await cur.fetchall()
        cur = await conn.execute(
            """select r.id, a.name as agent, r.status, r.model, r.input_tokens, r.output_tokens,
                      r.cost_usd, r.error, r.started_at, r.finished_at
                 from agent_runs r join agents a on a.id = r.agent_id
                where r.task_id = %s order by r.started_at""", (task_id,))
        task["runs"] = await cur.fetchall()
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: UUID, user: CurrentUser = Depends(current_user),
                      db: Database = Depends(get_db)) -> dict[str, str]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            "update tasks set status='cancelled', updated_at=now() where id=%s"
            " and status in ('queued','running') returning id", (task_id,))
        if await cur.fetchone() is None:
            raise HTTPException(409, "Görev iptal edilemez (bulunamadı, yetki yok veya bitmiş)")
    return {"status": "cancelled"}


@router.get("/organizations/{org_id}/agent-runs")
async def agent_runs(org_id: UUID, user: CurrentUser = Depends(current_user),
                     db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    async with db.user_tx(user) as conn:
        cur = await conn.execute(
            """select r.id, r.task_id, a.name as agent, r.status, r.model, r.input_tokens,
                      r.output_tokens, r.cost_usd, r.error, r.started_at, r.finished_at
                 from agent_runs r join agents a on a.id = r.agent_id
                where r.organization_id = %s order by r.started_at desc limit 200""", (org_id,))
        return await cur.fetchall()
