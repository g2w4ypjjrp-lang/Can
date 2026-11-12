"""Binance REST istemcisi (httpx, asenkron).

* Her istek önce ağırlık bütçesinden geçer (``WeightBudget``).
* Yanıt başlıklarındaki kullanılmış ağırlık bütçeye yansıtılır.
* HTTP 429 → ``RateLimitError`` (bütçe ``Retry-After`` süresince durur).
* HTTP 418 → ``IpBannedError`` (yasak bitene kadar hiçbir istek gönderilmez).
* Diğer hatalar → ``BinanceApiError`` (Binance hata kodu ve mesajıyla).
* İmzalı istekler (Aşama 10) ``RequestSigner`` ile yapılır; API anahtarı ``X-MBX-APIKEY``
  başlığında gönderilir ve hiçbir zaman loglanmaz.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx
import msgspec

from ati_engine import __version__
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.exchange.rate_limit import IpBannedError, Priority, RateLimitError, WeightBudget
from ati_engine.exchange.signing import RequestSigner, build_query, signed_query

_decoder = msgspec.json.Decoder()


class BinanceApiError(RuntimeError):
    def __init__(self, status: int, code: int | None, message: str) -> None:
        super().__init__(f"Binance API hatası (HTTP {status}, kod {code}): {message}")
        self.status = status
        self.code = code
        self.message = message


def _retry_after(headers: Mapping[str, str]) -> float:
    try:
        return float(headers.get("retry-after", "60"))
    except ValueError:
        return 60.0


class BinanceRestClient:
    def __init__(
        self,
        base_url: str,
        *,
        budget: WeightBudget,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        clock: Clock | None = None,
        api_key: str | None = None,
        signer: RequestSigner | None = None,
        recv_window_ms: int = 5000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._budget = budget
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s,
            headers={"User-Agent": f"ati-engine/{__version__}"},
        )
        self._clock = clock or SystemClock()
        self._api_key = api_key
        self._signer = signer
        self._recv_window_ms = recv_window_ms
        self._time_offset_ms = 0
        self._time_path: str | None = None  # -1021'de saati yeniden eşitlemek için
        self.requests = 0
        self.errors = 0

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def budget(self) -> WeightBudget:
        return self._budget

    @property
    def time_offset_ms(self) -> int:
        return self._time_offset_ms

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        weight: int,
        priority: Priority = Priority.NORMAL,
        signed: bool = False,
        api_key_only: bool = False,
    ) -> Any:
        """İstek gönderir. İmzalı istekte -1021 (bilgisayar saati Binance'ten kaymış) alınırsa
        saat yeniden eşitlenir ve istek bir kez tekrarlanır."""
        kwargs: dict[str, Any] = {
            "params": params,
            "weight": weight,
            "priority": priority,
            "signed": signed,
            "api_key_only": api_key_only,
        }
        try:
            return await self._request_once(method, path, **kwargs)
        except BinanceApiError as exc:
            if not signed or exc.code != -1021 or self._time_path is None:
                raise
            await self.sync_time(self._time_path)
            return await self._request_once(method, path, **kwargs)

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        weight: int,
        priority: Priority = Priority.NORMAL,
        signed: bool = False,
        api_key_only: bool = False,
    ) -> Any:
        """``api_key_only``: imzasız ama API anahtarı başlığı gereken uç noktalar
        (ör. vadeli kullanıcı akışı ``listenKey``)."""
        query_params: dict[str, Any] = dict(params or {})
        headers: dict[str, str] = {}
        if api_key_only and not signed:
            if not self._api_key:
                raise RuntimeError("Bu istek için API anahtarı gerekli")
            headers["X-MBX-APIKEY"] = self._api_key
        if signed:
            if self._signer is None or not self._api_key:
                raise RuntimeError("İmzalı istek için API anahtarı ve imzalayıcı gerekli")
            query_params.setdefault("recvWindow", self._recv_window_ms)
            query_params["timestamp"] = self._clock.now_ms() + self._time_offset_ms
            query = signed_query(query_params, self._signer)
            headers["X-MBX-APIKEY"] = self._api_key
        else:
            query = build_query(query_params)
        await self._budget.acquire(weight, priority)
        url = f"{self._base_url}{path}" + (f"?{query}" if query else "")
        self.requests += 1
        try:
            response = await self._client.request(method, url, headers=headers)
        except httpx.HTTPError:
            self.errors += 1
            raise
        self._budget.update_from_headers(response.headers)

        if response.status_code == 429:
            self.errors += 1
            retry = _retry_after(response.headers)
            self._budget.on_rate_limited(retry)
            raise RateLimitError("Binance istek limiti aşıldı (HTTP 429)", retry)
        if response.status_code == 418:
            self.errors += 1
            retry = _retry_after(response.headers)
            self._budget.on_banned(retry)
            raise IpBannedError("Binance IP adresini geçici olarak yasakladı (HTTP 418)", retry)
        if response.status_code >= 400:
            self.errors += 1
            code: int | None = None
            message = response.text[:300]
            try:
                body = _decoder.decode(response.content)
                if isinstance(body, dict):
                    code = body.get("code")
                    message = str(body.get("msg", message))
            except msgspec.DecodeError:
                pass
            raise BinanceApiError(response.status_code, code, message)
        return _decoder.decode(response.content)

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        weight: int,
        priority: Priority = Priority.NORMAL,
    ) -> Any:
        return await self.request("GET", path, params=params, weight=weight, priority=priority)

    async def sync_time(self, path: str) -> int:
        """Sunucu saatiyle farkı ölçer (ağ gecikmesinin yarısı düzeltilerek). Fark ms döner."""
        self._time_path = path
        start = time.monotonic()
        local_before = self._clock.now_ms()
        body = await self.get(path, weight=1, priority=Priority.HIGH)
        rtt_ms = (time.monotonic() - start) * 1000
        server_ms = int(body["serverTime"])
        self._time_offset_ms = int(server_ms - (local_before + rtt_ms / 2))
        return self._time_offset_ms
