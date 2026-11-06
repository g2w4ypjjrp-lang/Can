import asyncio

import httpx

from bot import diagnostics
from bot.binance_client import BinanceAPIError, BinanceFuturesClient, friendly_error
from bot.diagnostics import STEP_DNS, STEP_HTTPS, STEP_INTERNET, STEP_TCP, advise
from bot.net import describe_network_error, ssl_context


def err(text, cause=None):
    e = httpx.ConnectError(text)
    if cause is not None:
        e.__cause__ = cause
    return e


def test_describe_network_error_maps_common_causes():
    assert "SSL" in describe_network_error(err("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    assert "DNS" in describe_network_error(err("[Errno 11001] getaddrinfo failed"))
    assert "zaman aşımı" in describe_network_error(httpx.ConnectTimeout("timed out"))
    assert "kesildi" in describe_network_error(err("", OSError(10054, "An existing connection was forcibly closed")))
    assert "reddedildi" in describe_network_error(err("[WinError 10061] No connection could be made because the target machine actively refused it"))
    assert "Bağlantı hatası" in describe_network_error(err("weird"))


def test_network_error_reaches_user_message():
    def handler(request):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    c = BinanceFuturesClient("https://example.test", transport=httpx.MockTransport(handler))
    try:
        asyncio.run(c._request("POST", "/fapi/v1/order"))
    except BinanceAPIError as e:
        msg = friendly_error(e)
        assert "DNS" in msg and "kod None" not in msg
    else:
        raise AssertionError("hata bekleniyordu")


def test_ssl_context_uses_os_store_when_available():
    ctx = ssl_context()
    assert ctx is True or hasattr(ctx, "wrap_socket")


def step(name, ok, detail=""):
    return {"name": name, "ok": ok, "detail": detail}


def test_advise_messages():
    ok = [step(STEP_INTERNET, True), step(STEP_DNS, True), step(STEP_TCP, True), step(STEP_HTTPS, True)]
    assert "sorunsuz" in advise(ok, 200)
    dns = [step(STEP_INTERNET, True), step(STEP_DNS, False), step(STEP_HTTPS, False, "DNS")]
    assert "adresini çözmüyor" in advise(dns, 0)
    ssl = [step(STEP_INTERNET, True), step(STEP_DNS, True), step(STEP_TCP, True), step(STEP_HTTPS, False, "Güvenli bağlantı (SSL) doğrulanamadı")]
    assert "Antivirüs" in advise(ssl, 0)
    fw = [step(STEP_INTERNET, True), step(STEP_DNS, True), step(STEP_TCP, False), step(STEP_HTTPS, False, "zaman aşımı")]
    assert "güvenlik duvarı" in advise(fw, 0)
    geo = [step(STEP_INTERNET, True), step(STEP_DNS, True), step(STEP_TCP, True), step(STEP_HTTPS, False, "HTTP 451")]
    assert "451" in advise(geo, 451)
    offline = [step(STEP_INTERNET, False), step(STEP_DNS, False), step(STEP_HTTPS, False)]
    assert "internet bağlantısı yok" in advise(offline, 0)


def test_diagnose_reports_dns_block(monkeypatch):
    async def fake_get(url, timeout=10.0):
        if "google" in url:
            return 204, ""
        return 0, describe_network_error(err("[Errno 11001] getaddrinfo failed"))

    class Loop:
        async def getaddrinfo(self, *a, **k):
            raise OSError(11001, "getaddrinfo failed")

    monkeypatch.setattr(diagnostics, "_get", fake_get)
    monkeypatch.setattr(diagnostics.asyncio, "get_running_loop", lambda: Loop())
    r = asyncio.run(diagnostics.diagnose("https://fapi.binance.com"))
    names = [s["name"] for s in r["steps"]]
    assert names[:2] == [STEP_INTERNET, STEP_DNS] and STEP_TCP not in names
    assert r["ok"] is False and "adresini çözmüyor" in r["summary"]
