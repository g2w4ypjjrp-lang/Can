"""İş verisi görünümleri (yalnızca okuma): YouTube, Etsy, araştırma, üretim hattı, analitik, takvim."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user
from ..db import Database
from ..deps import get_db

router = APIRouter(prefix="/api/organizations/{org_id}", tags=["business"])


async def _all(conn: Any, sql: str, *args: Any) -> list[dict[str, Any]]:
    return await (await conn.execute(sql, args)).fetchall()


async def _one(conn: Any, sql: str, *args: Any) -> dict[str, Any] | None:
    return await (await conn.execute(sql, args)).fetchone()


@router.get("/youtube")
async def youtube(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        channel = await _one(conn, """select id, youtube_channel_id, title, subscriber_count, view_count, video_count,
                                             stats_fetched_at from youtube_channels where organization_id=%s
                                      order by stats_fetched_at desc nulls last limit 1""", org_id)
        videos = await _all(conn, """select youtube_video_id, title, privacy_status, lifecycle, published_at, tags
                                       from youtube_videos where organization_id=%s
                                      order by published_at desc nulls last limit 50""", org_id)
        totals = await _one(conn, """select sum(views)::bigint as views, sum(watch_time_minutes) as minutes,
                                            sum(subscribers_gained - subscribers_lost)::bigint as net_subs
                                       from youtube_analytics where organization_id=%s and video_id is null
                                        and day >= current_date - 30""", org_id)
    return {"channel": channel, "videos": videos, "last30": totals}


@router.get("/etsy")
async def etsy(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        shop = await _one(conn, "select etsy_shop_id, name, currency from etsy_shops where organization_id=%s limit 1", org_id)
        listings = await _all(conn, """select etsy_listing_id, title, price_amount, currency, quantity, state, tags, synced_at
                                         from etsy_listings where organization_id=%s order by title limit 200""", org_id)
        orders = await _all(conn, """select etsy_receipt_id, status, grandtotal_amount, currency, ordered_at, shipped_at
                                       from etsy_orders where organization_id=%s order by ordered_at desc limit 100""", org_id)
        printify = await _one(conn, "select count(*) as n from printify_products where organization_id=%s", org_id)
    return {"shop": shop, "listings": listings, "orders": orders, "printify_products": printify["n"] if printify else 0}


@router.get("/research")
async def research(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        products = await _all(conn, """select id, niche, idea, opportunity_score, created_at from product_research
                                        where organization_id=%s order by created_at desc limit 100""", org_id)
        competitors = await _all(conn, """select id, platform, competitor_name, competitor_url, created_at from competitor_analysis
                                           where organization_id=%s order by created_at desc limit 50""", org_id)
        reports = await _all(conn, """select t.id, t.title, t.status, t.completed_at from tasks t
                                        join agents a on a.id = t.assigned_agent_id
                                       where t.organization_id=%s and a.code in
                                             ('etsy_product_research','etsy_competitor_analysis','yt_trend_research')
                                       order by t.created_at desc limit 30""", org_id)
    return {"products": products, "competitors": competitors, "reports": reports}


@router.get("/production")
async def production(org_id: UUID, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    async with db.user_tx(user) as conn:
        ideas = await _all(conn, """select id, title, opportunity_score, status, created_at from youtube_content_ideas
                                     where organization_id=%s and status in ('proposed','accepted') order by created_at desc limit 50""",
                           org_id)
        scripts = await _all(conn, """select id, hook, qc_status, version, created_at from youtube_scripts
                                       where organization_id=%s order by created_at desc limit 50""", org_id)
        videos = await _all(conn, """select youtube_video_id, title, lifecycle, privacy_status, published_at from youtube_videos
                                      where organization_id=%s and lifecycle <> 'archived' order by updated_at desc limit 100""", org_id)
        tasks = await _all(conn, """select t.id, t.title, t.status, a.name as agent, t.created_at from tasks t
                                      join agents a on a.id = t.assigned_agent_id
                                     where t.organization_id=%s and a.code like 'yt\\_%%'
                                     order by t.created_at desc limit 30""", org_id)
    return {"ideas": ideas, "scripts": scripts, "videos": videos, "tasks": tasks}


@router.get("/analytics")
async def analytics(org_id: UUID, days: int = 30, user: CurrentUser = Depends(current_user),
                    db: Database = Depends(get_db)) -> dict[str, Any]:
    if days not in (7, 30, 90):
        raise HTTPException(422, "days 7, 30 veya 90 olmalı")
    async with db.user_tx(user) as conn:
        yt = await _all(conn, """select g.day::date as day, coalesce(a.views, 0)::bigint as views,
                                        coalesce(a.watch_time_minutes, 0) as minutes,
                                        coalesce(a.subscribers_gained - a.subscribers_lost, 0)::int as net_subs,
                                        a.day is not null as has_data
                                   from generate_series(current_date - %s, current_date - 1, interval '1 day') g(day)
                                   left join youtube_analytics a on a.organization_id=%s and a.video_id is null and a.day=g.day::date
                                  order by 1""", days, org_id)
        etsy = await _all(conn, """select g.day::date as day, count(o.id)::int as orders
                                     from generate_series(current_date - %s, current_date - 1, interval '1 day') g(day)
                                     left join etsy_orders o on o.organization_id=%s and o.ordered_at::date = g.day::date
                                    group by 1 order by 1""", days, org_id)
        connected = {r["provider"]: r["status"] == "connected" for r in await _all(
            conn, "select provider, status from integrations where organization_id=%s", org_id)}
    return {"days": days, "youtube": yt if connected.get("youtube") else None,
            "etsy": etsy if connected.get("etsy") else None}


@router.get("/calendar")
async def calendar(org_id: UUID, month: str, user: CurrentUser = Depends(current_user),
                   db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as exc:
        raise HTTPException(422, "month YYYY-MM biçiminde olmalı") from exc
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    async with db.user_tx(user) as conn:
        return await _all(conn, """
            select 'video' as kind, title, published_at as at, lifecycle as status from youtube_videos
             where organization_id=%s and published_at >= %s and published_at < %s
            union all
            select 'task', title, coalesce(completed_at, created_at), status from tasks
             where organization_id=%s and parent_task_id is null and created_at >= %s and created_at < %s
            union all
            select 'automation', name, next_run_at, 'scheduled' from automation_rules
             where organization_id=%s and enabled and next_run_at >= %s and next_run_at < %s
            order by at""", org_id, first, nxt, org_id, first, nxt, org_id, first, nxt)
