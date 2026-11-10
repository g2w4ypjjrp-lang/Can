"""Site görünümü: herkese açık sayfaların tasarım modu (yönetim panelinden seçilir).

Web sitesi her istekte değil, kısa önbellekle (``Cache-Control: max-age=30``) okur. Kayıt
``system_settings`` tablosunda ``appearance`` anahtarıdadır; bilinmeyen değer varsayılana döner.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from ati_cloud.accounts import Database

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


def create_site_router(db: Database) -> APIRouter:
    router = APIRouter(prefix="/v1/site")

    @router.get("/appearance")
    async def appearance(response: Response) -> dict[str, str]:
        async with db.connection() as conn:
            value = await load_appearance(conn)
        response.headers["Cache-Control"] = "public, max-age=30"
        return value

    return router
