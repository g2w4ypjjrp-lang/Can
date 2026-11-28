"""Printify REST API istemcisi (yalnızca okuma). Belge: https://developers.printify.com/"""

from __future__ import annotations

from typing import Any

import httpx

BASE = "https://api.printify.com/v1"


class PrintifyError(Exception):
    """Kullanıcıya gösterilebilir hata."""


class PrintifyClient:
    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._c = httpx.AsyncClient(
            base_url=BASE, timeout=30.0, transport=transport,
            headers={"authorization": f"Bearer {token}", "user-agent": "AIBusinessCenter/0.1"})

    async def __aenter__(self) -> PrintifyClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._c.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        try:
            r = await self._c.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise PrintifyError("Printify'a bağlanılamadı") from exc
        if r.status_code == 401:
            raise PrintifyError("Printify token'ı geçersiz veya süresi dolmuş")
        if r.status_code == 403:
            raise PrintifyError("Printify token'ının bu işlem için yetkisi yok (shops.read, products.read)")
        if r.status_code == 429:
            raise PrintifyError("Printify hız sınırı aşıldı; biraz sonra tekrar deneyin")
        if r.status_code >= 400:
            raise PrintifyError(f"Printify hatası ({r.status_code})")
        return r.json()

    async def shops(self) -> list[dict[str, Any]]:
        data = await self._get("/shops.json")
        return [{"id": s["id"], "title": s.get("title", ""), "sales_channel": s.get("sales_channel", "")} for s in data]

    async def products(self, shop_id: int, max_pages: int = 20) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            data = await self._get(f"/shops/{shop_id}/products.json", page=page, limit=50)
            out.extend(data.get("data", []))
            if page >= int(data.get("last_page", 1)):
                break
        return out


def simplify_variants(product: dict[str, Any]) -> list[dict[str, Any]]:
    """Printify fiyatları kuruş (cent) cinsindendir; burada aynen saklanır ve açıkça etiketlenir."""
    return [{"id": v.get("id"), "title": v.get("title"), "price_cents": v.get("price"), "cost_cents": v.get("cost"),
             "is_enabled": v.get("is_enabled")} for v in product.get("variants", []) if v.get("is_enabled", True)]
