"""Zamanlayıcı: süresi dolan onayları kapatır, vadesi gelen otomasyon kurallarını görev olarak başlatır.

Zamanlanmış görevler de normal görevlerle aynı kurallara tabidir: ajanların platformlara yazma
yetkisi yoktur, kritik işlemler onay bekler, görev bütçesi ve eşzamanlılık sınırı geçerlidir.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from .db import Database
from .dispatch import Dispatcher

log = logging.getLogger("bizcenter.scheduler")

TEMPLATES: list[dict[str, str]] = [
    {"key": "daily_youtube", "name": "Günlük YouTube performans raporu", "cron": "0 8 * * *",
     "command": "Dünkü YouTube kanal performansını (izlenme, CTR, süre, abone, gelir) analiz et, öneri ver."},
    {"key": "daily_etsy", "name": "Günlük Etsy satış raporu", "cron": "5 8 * * *",
     "command": "Dünkü Etsy siparişlerini ve satışlarını analiz et; dikkat gerektiren siparişleri listele."},
    {"key": "daily_tasks", "name": "Günlük görev durumu raporu", "cron": "10 8 * * *",
     "command": "Bugün iki departmanın da günlük raporunu hazırla."},
    {"key": "weekly_trends", "name": "Haftalık trend araştırması", "cron": "0 9 * * 1",
     "command": "Bu hafta YouTube için 5 video fikri bul ve fırsat puanı ver."},
    {"key": "weekly_products", "name": "Haftalık ürün araştırması", "cron": "30 9 * * 1",
     "command": "Etsy mağazam için satış potansiyeli olan 10 print-on-demand ürün araştır."},
    {"key": "weekly_competitors", "name": "Haftalık rakip analizi", "cron": "0 10 * * 2",
     "command": "Etsy ve YouTube'daki başlıca rakipleri analiz et ve pazar boşluklarını çıkar."},
    {"key": "weekly_content_plan", "name": "Haftalık içerik planı", "cron": "0 10 * * 3",
     "command": "Gelecek haftanın YouTube yayın takvimini hazırla."},
    {"key": "weekly_profit", "name": "Haftalık kâr analizi", "cron": "0 10 * * 5",
     "command": "Kâr marjı düşük Etsy ürünlerini bul ve iyileştirme öner."},
    {"key": "monthly_pnl", "name": "Aylık gelir-gider raporu", "cron": "0 9 1 * *",
     "command": "Geçen ayın gelir-gider raporunu YouTube, Etsy ve birleşik olarak hazırla."},
    {"key": "monthly_review", "name": "Aylık strateji değerlendirmesi", "cron": "0 10 1 * *",
     "command": "YouTube kanalını ve Etsy mağazasını geçen ayın sonuçlarına göre değerlendir; büyüme önerileri sun."},
]


def next_run(cron: str, tz: str, after: datetime) -> datetime:
    local = after.astimezone(ZoneInfo(tz))
    return croniter(cron, local).get_next(datetime).astimezone(UTC)


def valid_cron(cron: str) -> bool:
    return croniter.is_valid(cron) and len(cron.split()) == 5


async def tick(db: Database, dispatcher: Dispatcher, max_active: int, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    started: list[Any] = []
    skipped = 0
    async with db.pool.connection() as conn:
        cur = await conn.execute("select app.expire_approvals() as n")
        expired = (await cur.fetchone() or {}).get("n", 0)
        cur = await conn.execute(
            """select id, organization_id, name, schedule_cron, timezone, command, created_by
                 from automation_rules where enabled and (next_run_at is null or next_run_at <= %s)
                order by next_run_at nulls first limit 50 for update skip locked""", (now,))
        for rule in await cur.fetchall():
            nxt = next_run(rule["schedule_cron"], rule["timezone"], now)
            c2 = await conn.execute(
                "select count(*) as n from tasks where organization_id=%s and parent_task_id is null"
                " and status in ('queued','running','waiting_qc','waiting_approval')", (rule["organization_id"],))
            active = (await c2.fetchone() or {}).get("n", 0)
            if active >= max_active:
                skipped += 1
                await conn.execute(
                    "insert into notifications(organization_id, kind, title, body, link) values"
                    " (%s,'automation_skipped',%s,%s,'/automation')",
                    (rule["organization_id"], f"Otomasyon atlandı: {rule['name']}",
                     "Eşzamanlı görev sınırı dolu olduğu için bu çalıştırma atlandı."))
            else:
                c3 = await conn.execute(
                    "insert into tasks(organization_id, title, command, created_by) values (%s,%s,%s,%s)"
                    " returning id", (rule["organization_id"], f"[Otomatik] {rule['name']}"[:120],
                                      rule["command"], rule["created_by"]))
                started.append((await c3.fetchone() or {})["id"])
            await conn.execute("update automation_rules set last_run_at=%s, next_run_at=%s where id=%s",
                               (now, nxt, rule["id"]))
        # Ertelenmiş görevler (ilk görev paketi): organizasyon başına boş kapasite kadar başlatılır.
        cur = await conn.execute(
            """with cap as (
                 select organization_id, count(*) filter (where status in ('running','waiting_qc','waiting_approval')
                        or (status = 'queued' and coalesce((result->>'deferred')::boolean, false) = false)) as busy
                   from tasks where parent_task_id is null group by organization_id),
               ranked as (
                 select t.id, t.organization_id,
                        row_number() over (partition by t.organization_id order by t.created_at) as rn
                   from tasks t where t.status = 'queued' and (t.result->>'deferred')::boolean)
               select r.id from ranked r join cap c using (organization_id)
                where r.rn <= greatest(%s - c.busy, 0)""", (max_active,))
        for row in await cur.fetchall():
            await conn.execute("update tasks set result = result - 'deferred' where id = %s", (row["id"],))
            started.append(row["id"])
        await conn.commit()
    for task_id in started:
        dispatcher.enqueue(task_id)
    if expired or started or skipped:
        log.info("scheduler tick", extra={"extra_fields": {"expired": expired, "started": len(started),
                                                            "skipped": skipped}})
    return {"expired_approvals": expired, "started": started, "skipped": skipped}
