"""Onaylı işlem yürütücüsü.

Bir işlem yalnızca şu koşulların HEPSİ sağlanırsa platform API'sine gönderilir:
  1. Onay kaydı 'approved' durumunda (kullanıcı kimliğiyle verilmiş).
  2. payload_hash, saklanan payload ile birebir uyuşuyor (onaydan sonra değişmemiş).
  3. İşlem türü desteklenen listede ve payload şeması geçerli.
  4. Entegrasyon bağlı ve gerekli YAZMA iznine sahip.
  5. Hedef kayıt (listeleme / video) bu organizasyona ait.
Sonuç 'executed' veya 'failed' olarak kaydedilir; denetim kaydı ve bildirim oluşturulur.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from psycopg.types.json import Jsonb

from .config import Settings
from .db import Database
from .integrations import youtube as yt
from .integrations.crypto import TokenCipher
from .integrations.etsy import EtsyClient, EtsyError

log = logging.getLogger("bizcenter.executor")

ACTIONS = {
    "etsy.listing.update": {"platform": "etsy", "scope": "listings_w", "risk": "medium"},
    "youtube.video.update_metadata": {"platform": "youtube", "scope": yt.WRITE_SCOPE, "risk": "medium"},
}
EDITABLE = ("title", "description", "tags")


def payload_hash(action: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"action": action, "payload": payload}, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def validate_payload(action: str, p: dict[str, Any]) -> None:
    if action not in ACTIONS:
        raise ValueError("Desteklenmeyen işlem")
    changes = p.get("changes")
    if not isinstance(changes, dict) or not changes or set(changes) - set(EDITABLE):
        raise ValueError("Değişiklikler yalnızca başlık, açıklama ve etiket olabilir")
    if "title" in changes and not (isinstance(changes["title"], str) and 1 <= len(changes["title"]) <= (
            140 if action.startswith("etsy") else 100)):
        raise ValueError("Başlık uzunluğu geçersiz (Etsy ≤ 140, YouTube ≤ 100)")
    if "description" in changes and not (isinstance(changes["description"], str) and len(changes["description"]) <= 5000):
        raise ValueError("Açıklama en fazla 5000 karakter olabilir")
    if "tags" in changes:
        tags = changes["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) and t.strip() for t in tags):
            raise ValueError("Etiketler metin listesi olmalı")
        if action.startswith("etsy") and (len(tags) > 13 or any(len(t) > 20 for t in tags)):
            raise ValueError("Etsy: en fazla 13 etiket, her biri en fazla 20 karakter")
    key = "listing_id" if action.startswith("etsy") else "video_id"
    if not p.get(key):
        raise ValueError(f"{key} gerekli")


class Executor:
    def __init__(self, db: Database, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.db, self.s, self.transport = db, settings, transport

    async def _q(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        async with self.db.pool.connection() as conn:
            cur = await conn.execute(sql, args)
            rows = await cur.fetchall() if cur.description else []
            await conn.commit()
            return rows

    async def run(self, approval_id: UUID) -> str:
        rows = await self._q("select * from approvals where id=%s for update skip locked", approval_id)
        if not rows:
            return "missing"
        a = rows[0]
        if a["status"] != "approved":
            return a["status"]
        if a["action"] not in ACTIONS:
            return "approved"   # otomatik yürütücüsü olmayan işlem: onay kayıtlı kalır, işlem elle yapılır
        try:
            validate_payload(a["action"], a["payload"])
            if payload_hash(a["action"], a["payload"]) != a["payload_hash"]:
                raise ValueError("Bütünlük kontrolü başarısız: işlem içeriği onaydan sonra değişmiş")
            result = await self._dispatch(a)
            await self._finish(a, "executed", "Uygulandı", result)
            return "executed"
        except (ValueError, EtsyError, yt.YouTubeError) as exc:
            await self._finish(a, "failed", str(exc), None)
            return "failed"
        except Exception:
            log.exception("approval %s execution crashed", approval_id)
            await self._finish(a, "failed", "Beklenmeyen yürütme hatası", None)
            return "failed"

    async def _token(self, org: Any, provider: str, scope: str) -> tuple[str, str]:
        rows = await self._q(
            """select i.external_account_id, i.scopes, t.access_token_enc from integrations i
               join oauth_tokens t on t.integration_id=i.id
               where i.organization_id=%s and i.provider=%s and i.status='connected'""", org, provider)
        if not rows:
            raise ValueError(f"{provider} bağlı değil")
        if scope not in (rows[0]["scopes"] or []):
            raise ValueError("Bağlantının yazma izni yok; API Integrations'tan 'yazma izniyle bağlan' ile yenileyin")
        return TokenCipher(self.s.token_encryption_key).decrypt(rows[0]["access_token_enc"]), rows[0]["external_account_id"]

    async def _dispatch(self, a: dict[str, Any]) -> dict[str, Any]:
        p, org, spec = a["payload"], a["organization_id"], ACTIONS[a["action"]]
        token, account = await self._token(org, spec["platform"], spec["scope"])
        if a["action"] == "etsy.listing.update":
            own = await self._q("select 1 from etsy_listings where organization_id=%s and etsy_listing_id=%s", org, int(p["listing_id"]))
            if not own:
                raise ValueError("Listeleme bu mağazaya ait değil")
            async with EtsyClient(self.s.etsy_api_key, token, self.transport) as ec:
                res = await ec.update_listing(int(account), int(p["listing_id"]), p["changes"])
            await self._q("update etsy_listings set title=coalesce(%s,title), description=coalesce(%s,description),"
                          " tags=coalesce(%s,tags), synced_at=now() where organization_id=%s and etsy_listing_id=%s",
                          p["changes"].get("title"), p["changes"].get("description"), p["changes"].get("tags"),
                          org, int(p["listing_id"]))
            return {"listing_id": res.get("listing_id"), "title": res.get("title")}
        own = await self._q("select 1 from youtube_videos where organization_id=%s and youtube_video_id=%s", org, p["video_id"])
        if not own:
            raise ValueError("Video bu kanala ait değil")
        async with yt.YouTubeClient(token, self.transport) as c:
            res = await c.update_video_snippet(p["video_id"], p["changes"])
        await self._q("update youtube_videos set title=coalesce(%s,title), description=coalesce(%s,description),"
                      " tags=coalesce(%s,tags) where organization_id=%s and youtube_video_id=%s",
                      p["changes"].get("title"), p["changes"].get("description"), p["changes"].get("tags"), org, p["video_id"])
        return {"video_id": res.get("id"), "title": res.get("snippet", {}).get("title")}

    async def _finish(self, a: dict[str, Any], status: str, note: str, result: dict[str, Any] | None) -> None:
        await self._q("update approvals set status=%s, decision_note=coalesce(decision_note,'') || %s where id=%s and status='approved'",
                      status, f"\n[{'Uygulandı' if status == 'executed' else 'Başarısız'}] {note}", a["id"])
        await self._q("insert into audit_logs(organization_id, actor_user_id, action, target_type, target_id, details)"
                      " values (%s,%s,%s,'approval',%s,%s)", a["organization_id"], a["decided_by"], f"approval.{status}",
                      str(a["id"]), Jsonb({"action": a["action"], "note": note, "result": result}))
        await self._q("insert into notifications(organization_id, user_id, kind, title, body, link) values (%s,%s,%s,%s,%s,'/approvals')",
                      a["organization_id"], a["decided_by"], f"approval_{status}",
                      ("İşlem uygulandı: " if status == "executed" else "İşlem başarısız: ") + a["action"], note)
