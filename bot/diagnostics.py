"""Bağlantı teşhisi: Binance'e neden ulaşılamadığını adım adım bulur ve Türkçe öneri verir."""

from __future__ import annotations

import asyncio
import socket
import urllib.request
from typing import Any
from urllib.parse import urlsplit

import httpx

from .net import describe_network_error, ssl_context

STEP_INTERNET = "İnternet bağlantısı"
STEP_DNS = "Binance adresi (DNS)"
STEP_TCP = "Binance'e bağlantı (port 443)"
STEP_HTTPS = "Binance vadeli sunucusu (HTTPS)"
STEP_PROXY = "Vekil sunucu (proxy)"


async def _get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """(HTTP durum kodu, hata metni). Bağlantı kurulamazsa durum 0 olur."""
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=ssl_context(), follow_redirects=False) as client:
            resp = await client.get(url, headers={"User-Agent": "CanBot/1.0"})
            return resp.status_code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, describe_network_error(exc)


def advise(steps: list[dict[str, Any]], https_status: int) -> str:
    by_name = {s["name"]: s for s in steps}

    def failed(name: str) -> bool:
        s = by_name.get(name)
        return s is not None and not s["ok"]

    https = by_name.get(STEP_HTTPS, {})
    detail = str(https.get("detail", "")).lower()
    if https.get("ok"):
        return "Binance'e bağlantı sorunsuz. Hata sürerse API anahtarlarını ve izinlerini kontrol edin."
    if failed(STEP_INTERNET) and failed(STEP_DNS):
        return "Bu bilgisayarın internet bağlantısı yok gibi görünüyor. Bağlantıyı kontrol edip tekrar deneyin."
    if https_status == 451:
        return "Binance, bağlandığınız konumdan vadeli işlem erişimine izin vermiyor (HTTP 451)."
    if failed(STEP_DNS):
        return (
            "Bu ağ Binance'in adresini çözmüyor; ağınız ya da internet sağlayıcınız Binance'i engelliyor olabilir. "
            "Farklı bir bağlantıyla (ör. ev Wi-Fi'si ya da telefonun kişisel erişim noktası) deneyin."
        )
    if "ssl" in detail or "sertifika" in detail:
        return (
            "Güvenli bağlantı doğrulanamadı. Antivirüs programınız ya da şirket ağı HTTPS bağlantılarını "
            "inceliyor olabilir: antivirüste 'HTTPS / SSL tarama' özelliğini kapatmayı ya da CanBot'u "
            "istisnalara eklemeyi deneyin. Şirket ağındaysanız farklı bir bağlantı deneyin."
        )
    if failed(STEP_TCP) or "zaman aşımı" in detail or "kesildi" in detail or "reddedildi" in detail:
        return (
            "Bu ağın güvenlik duvarı Binance'e bağlantıyı engelliyor gibi görünüyor. Şirket ya da okul "
            "ağındaysanız bu tür sitelere izin verilmeyebilir; farklı bir bağlantıyla (ör. ev Wi-Fi'si ya da "
            "telefonun kişisel erişim noktası) deneyin."
        )
    if https_status in (403, 407):
        return "Ağ ya da vekil sunucu Binance'e erişimi reddetti. Farklı bir bağlantı deneyin."
    return f"Binance'e ulaşılamadı: {https.get('detail', 'bilinmeyen hata')}"


async def diagnose(base_url: str = "https://fapi.binance.com") -> dict[str, Any]:
    host = urlsplit(base_url).hostname or "fapi.binance.com"
    steps: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        steps.append({"name": name, "ok": ok, "detail": detail})

    status, err = await _get("https://www.google.com/generate_204", timeout=8)
    add(STEP_INTERNET, status in (200, 204), "Var" if status in (200, 204) else (err or f"HTTP {status}"))

    loop = asyncio.get_running_loop()
    ips: list[str] = []
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), 8)
        ips = sorted({str(i[4][0]) for i in infos})
        add(STEP_DNS, True, f"{host} → {', '.join(ips[:3])}")
    except Exception as exc:  # noqa: BLE001
        add(STEP_DNS, False, describe_network_error(exc))

    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https", "all")}
    if ips:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(ips[0], 443), 8)
            writer.close()
            add(STEP_TCP, True, f"{ips[0]}:443 açık")
        except Exception as exc:  # noqa: BLE001
            note = " Ağda vekil sunucu ayarlı; doğrudan bağlantı engelli olabilir." if proxies else ""
            add(STEP_TCP, False, describe_network_error(exc) + note)

    status, err = await _get(f"{base_url.rstrip('/')}/fapi/v1/ping")
    if status == 200:
        add(STEP_HTTPS, True, "Binance yanıt verdi")
    elif status:
        add(STEP_HTTPS, False, f"Binance HTTP {status} döndürdü")
    else:
        add(STEP_HTTPS, False, err)

    if proxies:
        add(STEP_PROXY, True, ", ".join(f"{k}: {v}" for k, v in proxies.items()))

    https_ok = next(s["ok"] for s in steps if s["name"] == STEP_HTTPS)
    return {"ok": https_ok, "host": host, "steps": steps, "summary": advise(steps, status)}
