"""Ajanların yapılandırılmış çıktıları: şemalar, bağlam ve kalıcı kayıt.

Ajan önerileri doğrudan uygulanmaz; yalnızca Approval Center'a öneri olarak düşer.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Jsonb

from ..db import Database
from ..executor import ProposalError, create_proposal

log = logging.getLogger("bizcenter.structured")
MAX_PROPOSALS = 10


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


_STR = {"type": "string"}
_TAGS = {"type": "array", "items": _STR}

SCHEMAS: dict[str, dict[str, Any]] = {
    "product_ideas": _obj({"report": _STR, "ideas": {"type": "array", "items": _obj(
        {"niche": _STR, "idea": _STR, "score": {"type": "integer"}, "evidence": {"type": "array", "items": _STR}})}}),
    "video_ideas": _obj({"report": _STR, "ideas": {"type": "array", "items": _obj(
        {"title": _STR, "summary": _STR, "score": {"type": "integer"}, "sources": {"type": "array", "items": _STR}})}}),
    "etsy_proposals": _obj({"report": _STR, "proposals": {"type": "array", "items": _obj(
        {"listing_id": _STR, "new_title": _STR, "new_tags": _TAGS, "reason": _STR})}}),
    "yt_proposals": _obj({"report": _STR, "proposals": {"type": "array", "items": _obj(
        {"video_id": _STR, "new_title": _STR, "new_tags": _TAGS, "reason": _STR})}}),
}

INSTRUCTIONS = {
    "product_ideas": "Raporun yanında her ürün fikrini 'ideas' listesine ekle (score 0-100, evidence: kaynak bağlantıları).",
    "video_ideas": "Raporun yanında her video fikrini 'ideas' listesine ekle (score 0-100, sources: kaynak bağlantıları).",
    "etsy_proposals": ("Aşağıdaki GERÇEK listelemeleri incele. İyileştirilebilecek olanlar için 'proposals' ekle: listing_id verilen "
                       "listeden olmalı; değişmeyecek alan için new_title boş metin, new_tags boş liste olsun. Başlık ≤ 140 karakter, "
                       "tam 13 etiket, her etiket ≤ 20 karakter. En fazla 10 öneri. Bunlar yalnızca kullanıcı onayına sunulur."),
    "yt_proposals": ("Aşağıdaki GERÇEK videoları incele. İyileştirilebilecek olanlar için 'proposals' ekle: video_id verilen listeden "
                     "olmalı; değişmeyecek alan için new_title boş metin, new_tags boş liste olsun. Başlık ≤ 100 karakter. "
                     "En fazla 10 öneri. Bunlar yalnızca kullanıcı onayına sunulur."),
}


async def domain_context(db: Database, org: Any, kind: str | None) -> str:
    """Ajanın üzerinde çalışacağı gerçek kayıtlar (güvenilmeyen veri olarak verilir)."""
    if kind not in ("etsy_proposals", "yt_proposals"):
        return ""
    sql = ("select etsy_listing_id::text as id, title, tags from etsy_listings where organization_id=%s and state='active'"
           " order by synced_at desc nulls last limit 40") if kind == "etsy_proposals" else (
          "select youtube_video_id as id, title, tags from youtube_videos where organization_id=%s and youtube_video_id is not null"
          " order by published_at desc nulls last limit 30")
    async with db.pool.connection() as conn:
        rows = await (await conn.execute(sql, (org,))).fetchall()
    if not rows:
        return "\n\n(Senkronlanmış kayıt yok; öneri listesi boş olsun ve raporda bunu belirt.)"
    lines = "\n".join(f"- id={r['id']} | başlık={r['title']} | etiketler={', '.join(r['tags'] or [])}" for r in rows)
    return f'\n\n<untrusted_data source="records">\n{lines.replace("</untrusted_data>", "")}\n</untrusted_data>'


def _clamp(v: Any) -> int | None:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return None


async def persist(db: Database, task: dict[str, Any], agent: dict[str, Any], kind: str, data: dict[str, Any]) -> dict[str, int]:
    """Yapılandırılmış çıktıyı kaydeder. Döner: kaydedilen fikir / öneri sayıları."""
    org, saved, proposed, rejected = task["organization_id"], 0, 0, 0
    async with db.pool.connection() as conn:
        if kind == "product_ideas":
            for i in (data.get("ideas") or [])[:50]:
                await conn.execute(
                    "insert into product_research(organization_id, task_id, niche, idea, opportunity_score, evidence)"
                    " values (%s,%s,%s,%s,%s,%s)",
                    (org, task["id"], str(i.get("niche", ""))[:300], str(i.get("idea", ""))[:500], _clamp(i.get("score")),
                     Jsonb([str(e)[:500] for e in i.get("evidence", [])][:10])))
                saved += 1
        elif kind == "video_ideas":
            for i in (data.get("ideas") or [])[:50]:
                await conn.execute(
                    "insert into youtube_content_ideas(organization_id, task_id, title, summary, opportunity_score, sources)"
                    " values (%s,%s,%s,%s,%s,%s)",
                    (org, task["id"], str(i.get("title", ""))[:300], str(i.get("summary", ""))[:2000], _clamp(i.get("score")),
                     Jsonb([str(e)[:500] for e in i.get("sources", [])][:10])))
                saved += 1
        await conn.commit()
    if kind in ("etsy_proposals", "yt_proposals"):
        action = "etsy.listing.update" if kind == "etsy_proposals" else "youtube.video.update_metadata"
        key = "listing_id" if kind == "etsy_proposals" else "video_id"
        for prop in (data.get("proposals") or [])[:MAX_PROPOSALS]:
            changes: dict[str, Any] = {}
            if str(prop.get("new_title", "")).strip():
                changes["title"] = str(prop["new_title"]).strip()
            tags = [str(t).strip() for t in prop.get("new_tags") or [] if str(t).strip()]
            if tags:
                changes["tags"] = tags
            if not changes:
                continue
            try:
                await create_proposal(db, org, action, str(prop.get(key, "")), changes,
                                      f"{agent['name']}: {str(prop.get('reason', ''))[:1500]}",
                                      "Arama görünürlüğü ve tıklama oranında artış (tahmin)",
                                      agent_id=agent["id"], task_id=task["id"])
                proposed += 1
            except ProposalError as exc:
                rejected += 1
                log.info("agent proposal rejected: %s", exc)
    return {"saved": saved, "proposed": proposed, "rejected": rejected}
