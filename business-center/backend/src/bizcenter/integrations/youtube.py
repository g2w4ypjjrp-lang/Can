"""YouTube Data API v3 + YouTube Analytics API v2 istemcisi (Google OAuth 2.0 + PKCE, yalnızca okuma)."""

from __future__ import annotations

import contextlib
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (adres, sır değil)
DATA = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"]


class YouTubeError(Exception):
    def __init__(self, msg: str, status: int = 0) -> None:
        super().__init__(msg)
        self.status = status


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


class YouTubeClient:
    def __init__(self, token: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        h = {"user-agent": "AIBusinessCenter/0.1"}
        if token:
            h["authorization"] = f"Bearer {token}"
        self._c = httpx.AsyncClient(timeout=30.0, transport=transport, headers=h)

    async def __aenter__(self) -> YouTubeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._c.aclose()

    async def _req(self, method: str, url: str, **kw: Any) -> Any:
        try:
            r = await self._c.request(method, url, **kw)
        except httpx.HTTPError as exc:
            raise YouTubeError("Google'a bağlanılamadı") from exc
        if r.status_code == 401:
            raise YouTubeError("YouTube yetkilendirmesi geçersiz; yeniden bağlanın", 401)
        if r.status_code == 403:
            reason = ""
            with contextlib.suppress(KeyError, IndexError, ValueError):
                reason = r.json()["error"]["errors"][0]["reason"]
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                raise YouTubeError("YouTube API günlük kotası doldu; yarın tekrar deneyin", 403)
            raise YouTubeError("Bu veri için YouTube izni yok", 403)
        if r.status_code >= 400:
            raise YouTubeError(f"YouTube hatası ({r.status_code})", r.status_code)
        return r.json()

    async def exchange(self, client_id: str, secret: str, redirect_uri: str, code: str, verifier: str) -> dict[str, Any]:
        return await self._req("POST", TOKEN_URL, data={
            "client_id": client_id, "client_secret": secret, "code": code, "code_verifier": verifier,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri})

    async def refresh(self, client_id: str, secret: str, refresh_token: str) -> dict[str, Any]:
        return await self._req("POST", TOKEN_URL, data={
            "client_id": client_id, "client_secret": secret, "refresh_token": refresh_token, "grant_type": "refresh_token"})

    async def my_channel(self) -> dict[str, Any] | None:
        data = await self._req("GET", f"{DATA}/channels", params={"part": "snippet,statistics,contentDetails", "mine": "true"})
        items = data.get("items") or []
        return items[0] if items else None

    async def recent_videos(self, uploads_playlist: str, max_items: int = 50) -> list[dict[str, Any]]:
        pl = await self._req("GET", f"{DATA}/playlistItems", params={
            "part": "contentDetails", "playlistId": uploads_playlist, "maxResults": min(max_items, 50)})
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if not ids:
            return []
        data = await self._req("GET", f"{DATA}/videos", params={"part": "snippet,statistics,status", "id": ",".join(ids)})
        return data.get("items", [])

    async def daily_report(self, start: str, end: str, with_revenue: bool) -> dict[str, Any]:
        metrics = "views,estimatedMinutesWatched,subscribersGained,subscribersLost"
        if with_revenue:
            metrics += ",estimatedRevenue"
        return await self._req("GET", ANALYTICS, params={
            "ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": metrics,
            "dimensions": "day", "sort": "day", "currency": "USD"})
