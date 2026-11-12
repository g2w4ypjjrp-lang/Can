"""Genel indirim kampanyası: yönetim panelinden bütün paketlere uygulanan yüzde indirim.

Ayar ``system_settings`` tablosunda ``campaign`` anahtarıyla saklanır:
``{"enabled": bool, "percent": 1-90, "label": str, "ends_at": ISO tarih ya da null}``.
Kampanya paket fiyatına uygulanır; kupon (varsa) kampanyalı fiyatın üzerine uygulanır.
Deneme ve ücretsiz paketler etkilenmez.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

KEY = "campaign"


def is_active(campaign: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not campaign or not campaign.get("enabled"):
        return False
    percent = campaign.get("percent")
    if not isinstance(percent, int) or not 1 <= percent <= 90:
        return False
    ends = campaign.get("ends_at")
    if ends:
        try:
            end = datetime.fromisoformat(str(ends))
        except ValueError:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end <= (now or datetime.now(UTC)):
            return False
    return True


def discounted(price_minor: int, percent: int) -> int:
    """Kampanyalı fiyat (kuruşa aşağı yuvarlanmış indirim: müşteri lehine yukarı değil)."""
    return price_minor - (price_minor * percent) // 100


async def load(conn: Any) -> dict[str, Any] | None:
    cur = await conn.execute("SELECT value FROM system_settings WHERE key = %s", (KEY,))
    row = await cur.fetchone()
    if row is None:
        return None
    value = row["value"] if isinstance(row, dict) else row[0]
    return value if isinstance(value, dict) else None


async def active(conn: Any) -> dict[str, Any] | None:
    campaign = await load(conn)
    return campaign if is_active(campaign) else None


def apply_to_plan(plan: dict[str, Any], campaign: dict[str, Any] | None) -> dict[str, Any]:
    """Paket satırına kampanyayı uygular: ``price_minor`` indirimli olur, liste fiyatı ve
    kampanya bilgisi eklenir."""
    price = int(plan["price_minor"])
    if campaign is None or plan.get("is_trial") or price <= 0:
        return {**plan, "list_price_minor": None, "campaign_percent": None, "campaign_label": None,
                "campaign_ends_at": None}  # fmt: skip
    percent = int(campaign["percent"])
    return {
        **plan,
        "price_minor": discounted(price, percent),
        "list_price_minor": price,
        "campaign_percent": percent,
        "campaign_label": campaign.get("label") or None,
        "campaign_ends_at": campaign.get("ends_at") or None,
    }
