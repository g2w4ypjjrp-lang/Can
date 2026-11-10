"""Telegram bildirimleri: ayar doğrulama, gönderim, hata açıklamaları, hız sınırı, olaylar ve
yerel API. Gerçek Telegram yerine sahte sunucu (httpx.MockTransport)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.events import KillSwitchEngaged, TradeNotice
from ati_engine.notify.telegram import (
    RATE_PER_MINUTE,
    TelegramError,
    TelegramNotifier,
    format_trade,
)
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore

TOKEN = "123456789:AAH4kq0Bx9cZ-sahte_bot_anahtari_0123456"
CHAT = "987654321"


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reply: tuple[int, dict[str, Any]] = (200, {"ok": True, "result": {}})
        self.fail_network = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail_network:
            raise httpx.ConnectError("bağlantı yok", request=request)
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append((request.url.path, json.loads(request.content)))
        if method == "getUpdates":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "message": {
                                "chat": {"id": 987654321, "first_name": "Can", "last_name": "A"}
                            }
                        },
                        {"message": {"chat": {"id": 987654321, "first_name": "Can"}}},
                        {"channel_post": {"chat": {"id": -100555, "title": "Sinyaller"}}},
                    ],
                },
            )
        status, body = self.reply
        return httpx.Response(status, json=body)


@pytest.fixture
async def notifier(tmp_path: Path) -> AsyncIterator[tuple[TelegramNotifier, FakeTelegram]]:
    db = Database(tmp_path / "engine.db")
    await db.open()
    await db.migrate()
    fake = FakeTelegram()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    clock = [1000.0]
    n = TelegramNotifier(
        vault=SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key())),
        store=SettingsStore(db),
        api_base="https://telegram.test",
        client=client,
        clock=lambda: clock[0],
    )
    await n.load()
    yield n, fake
    await client.aclose()
    await db.close()


async def test_settings_are_validated_and_token_is_never_exposed(
    notifier: tuple[TelegramNotifier, FakeTelegram],
) -> None:
    n, _ = notifier
    with pytest.raises(TelegramError, match="biçimi geçersiz"):
        await n.configure(token="yanlis", chat_id=None, enabled=False, categories=["safety"])
    with pytest.raises(TelegramError, match="önce bot anahtarını"):
        await n.configure(token=None, chat_id=None, enabled=True, categories=["safety"])
    with pytest.raises(TelegramError, match="Sohbet kimliği"):
        await n.configure(token=TOKEN, chat_id="abc def", enabled=True, categories=[])
    with pytest.raises(TelegramError, match="Bilinmeyen"):
        await n.configure(token=None, chat_id=CHAT, enabled=True, categories=["para_cek"])
    await n.configure(token=TOKEN, chat_id=CHAT, enabled=True, categories=["safety", "trades"])
    status = n.status()
    assert status["configured"] and status["enabled"] and status["token_hint"] == TOKEN[-4:]
    assert TOKEN not in json.dumps(status)

    # Yeniden yüklenince ayarlar korunur; anahtar kasadan okunur.
    reloaded = TelegramNotifier(vault=n.vault, store=n.store, api_base="https://telegram.test")
    await reloaded.load()
    assert reloaded.status()["configured"] and reloaded.categories == ["safety", "trades"]

    await n.clear()
    assert not n.status()["configured"] and not n.enabled


async def test_send_discover_and_error_explanations(
    notifier: tuple[TelegramNotifier, FakeTelegram], caplog: pytest.LogCaptureFixture
) -> None:
    n, fake = notifier
    caplog.set_level(logging.DEBUG)
    await n.configure(token=TOKEN, chat_id=CHAT, enabled=True, categories=["safety"])
    await n.send_now("merhaba")
    path, payload = fake.calls[-1]
    assert path == f"/bot{TOKEN}/sendMessage" and payload["chat_id"] == CHAT
    assert payload["text"] == "merhaba" and n.last_sent_ms is not None

    chats = await n.discover()
    assert chats == [
        {"chat_id": "987654321", "name": "Can"},
        {"chat_id": "-100555", "name": "Sinyaller"},
    ]

    fake.reply = (400, {"ok": False, "description": "Bad Request: chat not found"})
    with pytest.raises(TelegramError, match="/start"):
        await n.send_now("x")
    fake.reply = (401, {"ok": False, "description": "Unauthorized"})
    with pytest.raises(TelegramError, match="geçersiz"):
        await n.send_now("x")
    fake.fail_network = True
    with pytest.raises(TelegramError) as info:
        await n.send_now("x")
    assert TOKEN not in str(info.value)
    assert TOKEN not in caplog.text


async def test_categories_rate_limit_and_bus_events(
    notifier: tuple[TelegramNotifier, FakeTelegram],
) -> None:
    n, fake = notifier
    await n.configure(token=TOKEN, chat_id=CHAT, enabled=True, categories=["safety", "trades"])
    n.notify("alerts", "seçilmemiş tür gönderilmez")
    bus = EventBus()
    n.subscribe(bus)
    worker = asyncio.create_task(n.run())
    await bus.publish(KillSwitchEngaged(reason="test", actor="yerel"))
    trade = TradeNotice(
        market="usdm_futures", mode="testnet", symbol="BTCUSDT", action="closed",
        side="long", quantity="0.01", price="65000", net_pnl="12.5",
    )  # fmt: skip
    await bus.publish(trade)
    for _ in range(100):
        if len(fake.calls) >= 2:
            break
        await asyncio.sleep(0.01)
    texts = [payload["text"] for _, payload in fake.calls]
    assert any("Acil durdurma devrede" in t for t in texts)
    assert any("BTCUSDT" in t and "12.5 USDT" in t and "Demo" in t for t in texts)
    assert not any("seçilmemiş" in t for t in texts)

    # Dakikada en çok 20 mesaj: fazlası düşürülür (motor beklemez).
    for i in range(RATE_PER_MINUTE + 5):
        n.notify("safety", f"mesaj {i}")
    for _ in range(200):
        if n._queue.empty():
            break
        await asyncio.sleep(0.01)
    assert len(fake.calls) == RATE_PER_MINUTE and n.dropped == 7  # 2 olay + 18 = 20
    worker.cancel()
    await asyncio.sleep(0)


def test_trade_message_format() -> None:
    opened = TradeNotice(
        market="spot", mode="live", symbol="ETHUSDT", action="opened", side="long",
        quantity="0.5", price="3200",
    )  # fmt: skip
    assert format_trade(opened) == "📈 ETHUSDT Uzun (long) açıldı\nGERÇEK · Spot · 0.5 @ 3200"


async def test_local_api_configures_and_tests(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=15)
    runtime = engine.runtime
    assert runtime is not None and runtime.telegram is not None
    fake = FakeTelegram()
    runtime.telegram._client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{engine.bound_port}",
        headers={"Authorization": f"Bearer {runtime.api_token}"},
    ) as http:
        assert (await http.get("/v1/notifications/telegram")).json()["configured"] is False
        bad = await http.post(
            "/v1/notifications/telegram", json={"bot_token": "x", "enabled": False}
        )
        assert bad.status_code == 422
        chats = await http.post("/v1/notifications/telegram/discover", json={"bot_token": TOKEN})
        assert chats.json()[0]["chat_id"] == CHAT
        ok = await http.post(
            "/v1/notifications/telegram",
            json={"bot_token": TOKEN, "chat_id": CHAT, "enabled": True, "categories": ["safety"]},
        )
        assert ok.status_code == 200 and ok.json()["enabled"] is True
        assert TOKEN not in ok.text
        sent = await http.post("/v1/notifications/telegram/test")
        assert sent.status_code == 200
        assert "Telegram bildirimleri çalışıyor" in fake.calls[-1][1]["text"]
        audit = (await http.get("/v1/audit")).text
        assert "notify.telegram_configured" in audit and TOKEN not in audit
        cleared = await http.post("/v1/notifications/telegram/remove")
        assert cleared.json()["configured"] is False
        # Kimliksiz erişim reddedilir.
        anon = await httpx.AsyncClient(base_url=f"http://127.0.0.1:{engine.bound_port}").get(
            "/v1/notifications/telegram"
        )
        assert anon.status_code == 401
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=15)
