"""Etsy Open API v3 istemcisi (OAuth 2.0 + PKCE, yalnızca okuma).
Belge: https://developers.etsy.com/documentation/
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://www.etsy.com/oauth/connect"
API = "https://api.etsy.com/v3"
SCOPES = ["shops_r", "listings_r", "transactions_r"]


class EtsyError(Exception):
    """Kullanıcıya gösterilebilir hata."""


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(keystring: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "response_type": "code", "client_id": keystring, "redirect_uri": redirect_uri, "scope": " ".join(SCOPES),
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})


def money(m: dict[str, Any] | None) -> tuple[Decimal | None, str | None]:
    """Etsy para nesnesi: {amount, divisor, currency_code} -> (Decimal, para birimi)."""
    if not m or m.get("amount") is None:
        return None, None
    return (Decimal(m["amount"]) / Decimal(m.get("divisor") or 1)).quantize(Decimal("0.01")), m.get("currency_code")


class EtsyClient:
    def __init__(self, api_key: str, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"x-api-key": api_key, "user-agent": "AIBusinessCenter/0.1"}
        if token:
            headers["authorization"] = f"Bearer {token}"
        self._c = httpx.AsyncClient(timeout=30.0, transport=transport, headers=headers)

    async def __aenter__(self) -> EtsyClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._c.aclose()

    @staticmethod
    def _check(r: httpx.Response) -> Any:
        if r.status_code == 401:
            raise EtsyError("Etsy yetkilendirmesi geçersiz veya süresi dolmuş; yeniden bağlanın")
        if r.status_code == 403:
            raise EtsyError("Etsy uygulamanızın bu veriye erişim izni yok")
        if r.status_code == 429:
            raise EtsyError("Etsy hız sınırı aşıldı; biraz sonra tekrar deneyin")
        if r.status_code >= 400:
            raise EtsyError(f"Etsy hatası ({r.status_code})")
        return r.json()

    async def _req(self, method: str, url: str, **kw: Any) -> Any:
        try:
            r = await self._c.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise EtsyError("Etsy'ye bağlanılamadı") from exc
        return self._check(r)

    async def exchange(self, keystring: str, redirect_uri: str, code: str, verifier: str) -> dict[str, Any]:
        return await self._req("POST", f"{API}/public/oauth/token", data={
            "grant_type": "authorization_code", "client_id": keystring, "redirect_uri": redirect_uri,
            "code": code, "code_verifier": verifier})

    async def refresh(self, keystring: str, refresh_token: str) -> dict[str, Any]:
        return await self._req("POST", f"{API}/public/oauth/token", data={
            "grant_type": "refresh_token", "client_id": keystring, "refresh_token": refresh_token})

    async def me(self) -> dict[str, Any]:
        return await self._req("GET", f"{API}/application/users/me")

    async def shop(self, shop_id: int) -> dict[str, Any]:
        return await self._req("GET", f"{API}/application/shops/{shop_id}")

    async def _paged(self, url: str, params: dict[str, Any], max_items: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while len(out) < max_items:
            data = await self._req("GET", url, params={**params, "limit": 100, "offset": offset})
            batch = data.get("results", [])
            out.extend(batch)
            offset += len(batch)
            if not batch or offset >= int(data.get("count", 0)):
                break
        return out[:max_items]

    async def listings(self, shop_id: int, max_items: int = 1000) -> list[dict[str, Any]]:
        return await self._paged(f"{API}/application/shops/{shop_id}/listings", {"state": "active"}, max_items)

    async def receipts(self, shop_id: int, min_created: int, max_items: int = 2000) -> list[dict[str, Any]]:
        return await self._paged(f"{API}/application/shops/{shop_id}/receipts", {"min_created": min_created}, max_items)
