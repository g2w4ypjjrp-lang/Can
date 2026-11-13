"""Site görünümü: herkese açık sayfaların tasarım modu (yönetim panelinden seçilir).

Web sitesi her istekte değil, kısa önbellekle (``Cache-Control: max-age=30``) okur. Kayıt
``system_settings`` tablosunda ``appearance`` anahtarıdadır; bilinmeyen değer varsayılana döner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response

from ati_cloud.accounts import Database
from ati_cloud.payments import campaign

# Kod → panelde görünen ad. Renkler web/app/globals.css'te; her mod açık ve koyu temada
# erişilebilirlik (kontrast) testinden geçer (web/e2e/designs.spec.ts).
DESIGNS: dict[str, str] = {
    "okyanus": "Okyanus — mavi ve mor (varsayılan)",
    "zumrut": "Zümrüt — yeşil ve turkuaz",
    "gunbatimi": "Gün batımı — turuncu ve pembe",
    "altin": "Altın — kehribar ve bronz",
    "grafit": "Grafit — sade, tek renk",
}
DEFAULT_DESIGN = "okyanus"


def design_of(value: Any) -> str:
    design = value.get("design") if isinstance(value, dict) else None
    return design if design in DESIGNS else DEFAULT_DESIGN


async def load_appearance(conn: Any) -> dict[str, str]:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = 'appearance'")
    row = await cur.fetchone()
    return {"design": design_of(row["value"] if row else None)}


# --- Duyuru şeridi (sitenin en üstü; yönetim paneli → Ayarlar) -----------------------------------

ANNOUNCEMENT_TONES = ("info", "success", "warning", "campaign")


def announcement_active(value: Any, now: datetime | None = None) -> bool:
    if not isinstance(value, dict) or not value.get("enabled") or not value.get("text"):
        return False
    ends = value.get("ends_at")
    if ends:
        try:
            end = datetime.fromisoformat(str(ends))
        except ValueError:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return end > (now or datetime.now(UTC))
    return True


async def load_announcement(conn: Any) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = 'announcement'")
    row = await cur.fetchone()
    value = row["value"] if row else None
    return value if isinstance(value, dict) else None


def create_site_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1/site")

    @router.get("/appearance")
    async def appearance(response: Response) -> dict[str, str]:
        async with db.connection() as conn:
            value = await load_appearance(conn)
        response.headers["Cache-Control"] = "public, max-age=30"
        return value

    @router.get("/announcement")
    async def announcement(response: Response) -> dict[str, Any]:
        """Sitenin en üstündeki şerit: yönetimin duyurusu ve (varsa) yürürlükteki kampanya."""
        async with db.connection() as conn:
            stored = await load_announcement(conn)
            active_campaign = await campaign.active(conn)
        response.headers["Cache-Control"] = "public, max-age=30"
        shown = None
        if stored is not None and announcement_active(stored):
            shown = {k: stored.get(k) for k in ("text", "link", "tone", "ends_at")}
        promo = None
        if active_campaign is not None:
            promo = {
                "percent": active_campaign["percent"],
                "label": active_campaign.get("label") or None,
                "ends_at": active_campaign.get("ends_at") or None,
            }
        return {"announcement": shown, "campaign": promo}

    return router
