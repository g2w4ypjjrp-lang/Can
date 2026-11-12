"""Telegram bildirimleri: kullanıcının kendi botu (Telegram'da @BotFather) ve kendi sohbeti.

* Bot anahtarı kasada şifreli saklanır; API'den geri okunamaz (yalnızca son 4 karakter).
* Mesajlar kısa özetlerdir: API anahtarı, emir kimliği, bakiye ayrıntısı içermez.
* Gönderim kuyrukludur ve motoru hiçbir zaman bekletmez. Dakikada en çok 20 mesaj gönderilir;
  fazlası düşürülür ve sayılır (Telegram'ın sınırları ve bildirim yağmuruna karşı).
* Telegram'a giden istek adresinde bot anahtarı bulunduğundan HTTP istek günlükleri kapalıdır
  (``observability.logging``) ve hata mesajlarına adres yazılmaz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from ati_engine.core.bus import EventBus
from ati_engine.core.events import (
    Alert,
    EngineStateChanged,
    KillSwitchEngaged,
    KillSwitchReleased,
    TradeNotice,
)
from ati_engine.notify.trade_text import trade_details
from ati_engine.security.vault import SecretVault
from ati_engine.storage.settings_store import SettingsStore

logger = logging.getLogger(__name__)

_BOT_URL = re.compile(r"/bot\d{5,15}:[A-Za-z0-9_-]+")


class _HideBotToken(logging.Filter):
    """İkinci kat koruma: günlük düzeyi ne olursa olsun HTTP istek kayıtlarındaki bot anahtarı
    maskelenir (Telegram adresi ``/bot<anahtar>/yöntem`` biçimindedir)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "/bot" in message:
            record.msg = _BOT_URL.sub("/bot***", message)
            record.args = ()
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_HideBotToken())

TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,60}$")
CHAT_RE = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$")
VAULT_KEY = "telegram.bot_token"
STORE_KEY = "telegram"
CATEGORIES: dict[str, str] = {
    "safety": "Acil durdurma ve motor durumu",
    "trades": "Pozisyon açılış ve kapanışları",
    "alerts": "Risk ve sistem uyarıları",
}
DEFAULT_CATEGORIES = ["safety", "trades", "alerts"]
RATE_PER_MINUTE = 20
QUEUE_SIZE = 50

MODES = {"testnet": "Demo", "paper": "Sanal", "live": "GERÇEK"}


class TelegramError(Exception):
    """Kullanıcıya gösterilecek açıklamalı hata."""


def _explain(status: int, description: str) -> str:
    low = description.lower()
    if status == 401 or "unauthorized" in low:
        return "Bot anahtarı geçersiz. @BotFather'dan aldığınız anahtarı kontrol edin."
    if "chat not found" in low:
        return "Sohbet bulunamadı: Telegram'da botunuza /start yazın, sonra sohbeti yeniden bulun."
    if "blocked" in low:
        return "Bot engellenmiş: Telegram'da botun engelini kaldırıp /start yazın."
    if status == 429:
        return "Telegram çok sık mesaj gönderildiğini bildirdi; biraz sonra yeniden denenir."
    return f"Telegram hata verdi ({status}): {description[:120]}"


def format_trade(n: TradeNotice) -> str:
    side = "Uzun (long)" if n.side == "long" else "Kısa (short)"
    mode = MODES.get(n.mode, n.mode)
    market = "Futures" if n.market == "usdm_futures" else "Spot"
    # Ayrıntılar (stop, hedef, puan, kapanış nedeni, süre) varsa alt satırlara eklenir.
    extra = "".join(f"\n{line}" for line in trade_details(n)[1:])
    if n.action == "opened":
        return f"📈 {n.symbol} {side} açıldı\n{mode} · {market} · {n.quantity} @ {n.price}{extra}"
    pct = f" (%{n.pnl_pct:+.2f})" if n.pnl_pct is not None else ""
    pnl = f"\nNet kâr/zarar: {n.net_pnl} USDT{pct}" if n.net_pnl is not None else ""
    return f"📉 {n.symbol} {side} kapandı\n{mode} · {market} · {n.quantity} @ {n.price}{pnl}{extra}"


class TelegramNotifier:
    def __init__(
        self,
        *,
        vault: SecretVault,
        store: SettingsStore,
        api_base: str = "https://api.telegram.org",
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.vault = vault
        self.store = store
        self.api_base = api_base.rstrip("/")
        self._client = client
        self._clock = clock
        self.chat_id: str | None = None
        self.enabled = False
        self.categories: list[str] = list(DEFAULT_CATEGORIES)
        self.token_hint: str | None = None
        self.last_error: str | None = None
        self.last_sent_ms: int | None = None
        self.dropped = 0
        self._token: str | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._sent: deque[float] = deque()

    # --- Ayarlar ---------------------------------------------------------------------------

    async def load(self) -> None:
        secret = await self.vault.get(VAULT_KEY)
        self._token = secret.get_secret_value() if secret else None
        self.token_hint = self._token[-4:] if self._token else None
        stored = await self.store.get(STORE_KEY, {}) or {}
        self.chat_id = stored.get("chat_id")
        self.enabled = bool(stored.get("enabled", False))
        cats = stored.get("categories")
        self.categories = (
            [c for c in cats if c in CATEGORIES]
            if isinstance(cats, list)
            else list(DEFAULT_CATEGORIES)
        )

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self._token and self.chat_id),
            "enabled": self.enabled,
            "token_hint": self.token_hint,
            "chat_id": self.chat_id,
            "categories": self.categories,
            "available_categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
            "last_error": self.last_error,
            "last_sent_ms": self.last_sent_ms,
            "dropped": self.dropped,
        }

    async def configure(
        self,
        *,
        token: str | None,
        chat_id: str | None,
        enabled: bool,
        categories: list[str],
    ) -> None:
        if token is not None:
            token = token.strip()
            if not TOKEN_RE.fullmatch(token):
                raise TelegramError("Bot anahtarı biçimi geçersiz (ör. 123456789:AA…)")
            await self.vault.put(VAULT_KEY, token)
            self._token = token
            self.token_hint = token[-4:]
        if chat_id is not None:
            chat_id = chat_id.strip()
            if not CHAT_RE.fullmatch(chat_id):
                raise TelegramError("Sohbet kimliği geçersiz (sayı ya da @kanal_adi)")
            self.chat_id = chat_id
        unknown = [c for c in categories if c not in CATEGORIES]
        if unknown:
            raise TelegramError(f"Bilinmeyen bildirim türü: {', '.join(unknown)}")
        if enabled and not (self._token and self.chat_id):
            raise TelegramError("Açmak için önce bot anahtarını ve sohbet kimliğini girin")
        self.enabled = enabled
        self.categories = categories
        await self.store.set(
            STORE_KEY,
            {"chat_id": self.chat_id, "enabled": self.enabled, "categories": self.categories},
        )

    async def clear(self) -> None:
        await self.vault.delete(VAULT_KEY)
        self._token = None
        self.token_hint = None
        self.chat_id = None
        self.enabled = False
        self.last_error = None
        await self.store.set(STORE_KEY, {"categories": self.categories})

    # --- Telegram API ----------------------------------------------------------------------

    async def _call(self, token: str, method: str, payload: dict[str, Any]) -> Any:
        client = self._client or httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(f"{self.api_base}/bot{token}/{method}", json=payload)
        except httpx.HTTPError as exc:
            # Adres (bot anahtarını içerir) mesaja yazılmaz.
            raise TelegramError(f"Telegram'a ulaşılamadı ({type(exc).__name__})") from None
        finally:
            if self._client is None:
                await client.aclose()
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or not data.get("ok"):
            raise TelegramError(_explain(response.status_code, str(data.get("description", ""))))
        return data.get("result")

    async def send_now(self, text: str) -> None:
        if not (self._token and self.chat_id):
            raise TelegramError("Bot anahtarı ve sohbet kimliği girilmemiş")
        await self._call(
            self._token,
            "sendMessage",
            {"chat_id": self.chat_id, "text": text[:3500], "disable_web_page_preview": True},
        )
        self.last_sent_ms = int(time.time() * 1000)
        self.last_error = None

    async def discover(self, token: str | None = None) -> list[dict[str, str]]:
        """Bota son yazan sohbetler: kullanıcı önce bota /start yazar, sohbet kimliği buradan
        seçilir."""
        token = (token or "").strip() or self._token
        if not token or not TOKEN_RE.fullmatch(token):
            raise TelegramError("Önce geçerli bir bot anahtarı girin")
        updates = await self._call(token, "getUpdates", {"limit": 50, "timeout": 0})
        chats: dict[str, dict[str, str]] = {}
        for update in updates or []:
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" not in chat:
                continue
            name = chat.get("title") or " ".join(
                p for p in (chat.get("first_name"), chat.get("last_name")) if p
            )
            chats[str(chat["id"])] = {"chat_id": str(chat["id"]), "name": name or str(chat["id"])}
        return list(chats.values())

    # --- Kuyruk ----------------------------------------------------------------------------

    def notify(self, category: str, text: str) -> None:
        if not self.enabled or category not in self.categories:
            return
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            self.dropped += 1

    async def run(self) -> None:
        while True:
            text = await self._queue.get()
            now = self._clock()
            while self._sent and now - self._sent[0] > 60:
                self._sent.popleft()
            if len(self._sent) >= RATE_PER_MINUTE:
                self.dropped += 1
                continue
            self._sent.append(now)
            try:
                await self.send_now(text)
            except TelegramError as exc:
                self.last_error = str(exc)
                logger.warning("Telegram bildirimi gönderilemedi", extra={"error": str(exc)})
            except Exception as exc:  # kuyruk asla durmaz
                self.last_error = f"Gönderilemedi ({type(exc).__name__})"

    def subscribe(self, bus: EventBus) -> None:
        async def on_kill(event: KillSwitchEngaged) -> None:
            self.notify("safety", f"🛑 Acil durdurma devrede\n{event.reason}")

        async def on_release(event: KillSwitchReleased) -> None:
            self.notify("safety", "✅ Acil durdurma kaldırıldı")

        async def on_state(event: EngineStateChanged) -> None:
            if event.current.value in ("safe_mode", "halted"):
                self.notify("safety", f"⚠️ Motor durumu: {event.current.value}\n{event.reason}")

        async def on_alert(event: Alert) -> None:
            if event.severity.value in ("warning", "critical"):
                self.notify("alerts", f"⚠️ {event.title}\n{event.message}")

        async def on_trade(event: TradeNotice) -> None:
            self.notify("trades", format_trade(event))

        bus.subscribe(KillSwitchEngaged, on_kill, name="telegram-kill")
        bus.subscribe(KillSwitchReleased, on_release, name="telegram-release")
        bus.subscribe(EngineStateChanged, on_state, name="telegram-state")
        bus.subscribe(Alert, on_alert, name="telegram-alerts")
        bus.subscribe(TradeNotice, on_trade, name="telegram-trades")


async def stop_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
