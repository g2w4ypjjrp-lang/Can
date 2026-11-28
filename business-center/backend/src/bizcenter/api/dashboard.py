"""Dashboard metrikleri.

Kural: veri yoksa sayı uydurulmaz. Her metrik `status` taşır:
  ok            -> gerçek veriden hesaplandı
  no_data       -> entegrasyon var ama ilgili veri henüz yok
  not_connected -> ilgili platform bağlı değil
Para tutarları para birimi başına ayrı verilir; kur dönüşümü yapılmaz.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


def metric(value: Any, status: str, **extra: Any) -> dict[str, Any]:
    return {"value": value if status == "ok" else None, "status": status, **extra}


async def _one(conn: AsyncConnection, sql: str, *args: Any) -> dict[str, Any]:
    cur = await conn.execute(sql, args)
    row = await cur.fetchone()
    return row or {}


async def _all(conn: AsyncConnection, sql: str, *args: Any) -> list[dict[str, Any]]:
    cur = await conn.execute(sql, args)
    return await cur.fetchall()


def money(rows: list[dict[str, Any]], connected: bool) -> dict[str, Any]:
    if not connected:
        return metric(None, "not_connected")
    rows = [r for r in rows if r["amount"] is not None]
    if not rows:
        return metric(None, "no_data")
    return metric([{"currency": r["currency"], "amount": str(r["amount"])} for r in rows], "ok")


@router.get("/organizations/{org_id}/dashboard")
async def dashboard(org_id: UUID, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        if not (await _one(conn, "select app.is_member(%s) as ok", org_id)).get("ok"):
            raise HTTPException(404, "Organizasyon bulunamadı")

        integ = {r["provider"]: r["status"] for r in await _all(
            conn, "select provider, status from integrations where organization_id = %s", org_id)}
        yt = integ.get("youtube") == "connected"
        etsy = integ.get("etsy") == "connected"

        ch = await _one(conn, """select sum(view_count)::bigint as views, sum(subscriber_count)::bigint as subs,
                                        max(stats_fetched_at) as as_of
                                   from youtube_channels where organization_id = %s
                                    and stats_fetched_at is not null""", org_id)
        has_ch = ch.get("as_of") is not None
        yt_rev = await _all(conn, """select currency, sum(estimated_revenue) as amount
                                       from youtube_analytics
                                      where organization_id = %s and video_id is null
                                        and day >= current_date - 30 and currency is not null
                                      group by currency""", org_id)
        orders = await _one(conn, """select count(*) as n, max(synced_at) as as_of from etsy_orders
                                      where organization_id = %s
                                        and ordered_at >= now() - interval '30 days'""", org_id)
        any_orders = (await _one(conn, "select exists(select 1 from etsy_orders where organization_id=%s) as e",
                                 org_id)).get("e")
        etsy_rev = await _all(conn, """select currency, sum(grandtotal_amount) as amount from etsy_orders
                                        where organization_id = %s and currency is not null
                                          and ordered_at >= now() - interval '30 days'
                                        group by currency""", org_id)
        profit = await _one(conn, """select figures, currency, period_start, period_end, missing_data
                                       from profit_reports
                                      where organization_id = %s and scope = 'etsy' and verified
                                      order by period_end desc limit 1""", org_id)
        expenses = await _all(conn, """select currency, sum(amount) as amount from expenses
                                        where organization_id = %s
                                          and occurred_on >= current_date - 30
                                        group by currency""", org_id)
        counts = await _one(conn, """select
              (select count(*) from approvals where organization_id = %s
                  and status = 'pending' and expires_at > now()) as pending_approvals,
              (select count(*) from agents where organization_id = %s and enabled) as agents,
              (select count(distinct assigned_agent_id) from tasks where organization_id = %s
                  and status = 'running') as working_agents,
              (select count(*) from tasks where organization_id = %s
                  and status in ('queued','running','waiting_qc','waiting_approval')) as active_tasks,
              (select count(*) from tasks where organization_id = %s and status = 'failed'
                  and updated_at >= now() - interval '30 days') as failed_tasks""",
                              org_id, org_id, org_id, org_id, org_id)
        recent = await _all(conn, """select id, title, completed_at from tasks
                                      where organization_id = %s and status = 'completed'
                                      order by completed_at desc nulls last limit 5""", org_id)

    if profit:
        net = metric({"currency": profit["currency"], "amount": profit["figures"].get("net_profit"),
                      "period_start": profit["period_start"], "period_end": profit["period_end"],
                      "missing_data": profit["missing_data"]}, "ok")
    else:
        net = metric(None, "no_data" if etsy else "not_connected",
                     note="Doğrulanmış kâr raporu yok")

    return {
        "integrations": {p: integ.get(p, "disconnected") for p in ("youtube", "etsy", "printify")},
        "youtube": {
            "total_views": metric(ch.get("views"), "ok" if yt and has_ch else
                                  ("no_data" if yt else "not_connected"), as_of=ch.get("as_of")),
            "subscribers": metric(ch.get("subs"), "ok" if yt and has_ch else
                                  ("no_data" if yt else "not_connected"), as_of=ch.get("as_of")),
            "estimated_revenue_30d": money(yt_rev, yt),
        },
        "etsy": {
            "orders_30d": metric(orders.get("n"), "ok" if etsy and any_orders else
                                 ("no_data" if etsy else "not_connected"), as_of=orders.get("as_of")),
            "sales_revenue_30d": money(etsy_rev, etsy),
            "net_profit": net,
        },
        "expenses_30d": money(expenses, True),
        "operations": {k: counts[k] for k in
                       ("pending_approvals", "agents", "working_agents", "active_tasks", "failed_tasks")},
        "recent_completed_tasks": recent,
    }
