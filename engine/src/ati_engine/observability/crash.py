"""İsteğe bağlı hata raporları (kullanıcı açarsa; varsayılan kapalı).

Gönderilen: uygulama ve sürüm, işletim sistemi, bileşen (günlükçü adı), hata türü, ayıklanmış
mesaj ve yığın izi, parmak izi (aynı hatayı gruplamak için). Gönderilmeyen: kullanıcı adı, dosya
yollarındaki kişisel klasörler, e-posta, IP adresi, lisans anahtarı, API anahtarı/imza, bakiye,
emir kimliği. Ayıklama gönderimden önce burada, sunucuda bir kez daha yapılır.

Gönderim kuyrukludur ve motoru hiçbir zaman bekletmez. Aynı hata saatte bir kez, toplamda saatte en
çok 10 rapor gönderilir. Rapor gönderilemezse düşürülür (yeniden denenmez).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import platform
import re
import time
import traceback
from collections import deque
from datetime import UTC, datetime
from typing import Any

import httpx

from ati_engine.security.redaction import redact_text
from ati_engine.storage.settings_store import SettingsStore

logger = logging.getLogger(__name__)

STORE_KEY = "crash_reports.enabled"
MAX_MESSAGE = 500
MAX_STACK = 8000
PER_HOUR = 10
SAME_ERROR_S = 3600
QUEUE_SIZE = 20

# Windows kullanıcı adı boşluk içerebilir ("C:\\Users\\Ad Soyad\\..."): sonraki ayraca kadar.
_HOME = re.compile(r"(?i)([A-Z]:\\+(?:Users|Documents and Settings)\\+)[^\\/\"'\n]+")
_UNIX_HOME = re.compile(r"(/(?:home|Users)/)[^/\s\"']+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LICENSE = re.compile(r"\bATI-[0-9A-Z*]{4}(?:-[0-9A-Z*]{4}){3}\b")
# Harf ve rakam karışık uzun dizgiler (anahtar, belirteç, base64); düz dosya yolları etkilenmez.
_SECRETISH = re.compile(
    r"\b(?=[A-Za-z0-9+/=_-]*\d)(?=[A-Za-z0-9+/=_-]*[A-Za-z])[A-Za-z0-9+/=_-]{32,}"
)
_NUMBERS = re.compile(r"\b\d{6,}\b")


def scrub(text: str) -> str:
    """Kişisel ve gizli olabilecek her şeyi metinden ayıklar."""
    text = redact_text(text)
    text = _HOME.sub(r"\1<kullanici>", text)
    text = _UNIX_HOME.sub(r"\1<kullanici>", text)
    text = _EMAIL.sub("<e-posta>", text)
    text = _LICENSE.sub("<lisans>", text)
    text = _IPV4.sub("<ip>", text)
    text = _SECRETISH.sub("<gizli>", text)
    return _NUMBERS.sub("<sayi>", text)


def fingerprint(component: str, error_type: str, stack: str) -> str:
    """Aynı hatanın raporları tek grupta toplanır: tür + yığındaki işlev adları (satır numarası ya
    da mesaj değil; böylece farklı değerlerle oluşan aynı hata tek kayıt olur)."""
    frames = re.findall(r'File "[^"]*?([\w.]+)\.py", line \d+, in (\w+)', stack)
    key = "|".join([component, error_type, *[f"{m}:{f}" for m, f in frames[-8:]]])
    return hashlib.sha256(key.encode()).hexdigest()[:32]


class CrashReporter:
    def __init__(
        self,
        *,
        store: SettingsStore,
        url: str,
        version: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self._store = store
        self.url = url
        self.version = version
        self._transport = transport
        self._clock = clock
        self.enabled = False
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_SIZE)
        self._recent: dict[str, float] = {}
        self._sent_at: deque[float] = deque()
        self.sent = 0
        self.dropped = 0
        self.last_sent_at: str | None = None
        self.last_error: str | None = None

    async def load(self) -> None:
        self.enabled = bool(await self._store.get(STORE_KEY, False))

    async def set_enabled(self, enabled: bool) -> None:
        await self._store.set(STORE_KEY, enabled)
        self.enabled = enabled

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "sent": self.sent,
            "dropped": self.dropped,
            "last_sent_at": self.last_sent_at,
            "last_error": self.last_error,
            "endpoint": httpx.URL(self.url).host,
        }

    def build(self, component: str, error_type: str, message: str, stack: str) -> dict[str, Any]:
        clean_stack = scrub(stack)[-MAX_STACK:]
        return {
            "app": "engine" if component != "desktop-ui" else "desktop",
            "version": self.version,
            "os": f"{platform.system()} {platform.release()}"[:60],
            "component": scrub(component)[:120],
            "error_type": scrub(error_type)[:120],
            "message": scrub(message)[:MAX_MESSAGE],
            "stack": clean_stack,
            "fingerprint": fingerprint(component, error_type, clean_stack),
            "occurred_at": datetime.now(UTC).isoformat(),
        }

    def capture(self, component: str, error_type: str, message: str, stack: str) -> bool:
        """Raporu kuyruğa alır (kapalıysa, aynı hata yakın zamanda gönderildiyse ya da kuyruk
        doluysa almaz). Hiçbir zaman beklemez ve hata fırlatmaz."""
        if not self.enabled:
            return False
        try:
            report = self.build(component, error_type, message, stack)
            now = self._clock()
            last = self._recent.get(report["fingerprint"])
            if last is not None and now - last < SAME_ERROR_S:
                return False
            self._recent[report["fingerprint"]] = now
            if len(self._recent) > 500:
                self._recent.pop(next(iter(self._recent)))
            self._queue.put_nowait(report)
            return True
        except asyncio.QueueFull:
            self.dropped += 1
            return False
        except Exception:
            return False

    def capture_exception(self, component: str, exc: BaseException) -> bool:
        stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return self.capture(component, type(exc).__name__, str(exc), stack)

    def _allowed_now(self) -> bool:
        now = self._clock()
        while self._sent_at and now - self._sent_at[0] > 3600:
            self._sent_at.popleft()
        if len(self._sent_at) >= PER_HOUR:
            return False
        self._sent_at.append(now)
        return True

    async def send_one(self, client: httpx.AsyncClient, report: dict[str, Any]) -> None:
        if not self.enabled or not self._allowed_now():
            self.dropped += 1
            return
        try:
            response = await client.post(self.url, json=report)
            if response.status_code >= 400:
                self.last_error = f"Sunucu {response.status_code} döndü"
                self.dropped += 1
                return
        except httpx.HTTPError as exc:
            self.last_error = f"Gönderilemedi ({type(exc).__name__})"
            self.dropped += 1
            return
        self.sent += 1
        self.last_error = None
        self.last_sent_at = datetime.now(UTC).isoformat()

    async def drain(self) -> None:
        """Kuyruktakileri gönderir (testler için)."""
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
            while not self._queue.empty():
                await self.send_one(client, self._queue.get_nowait())

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
            while True:
                report = await self._queue.get()
                await self.send_one(client, report)


class CrashLogHandler(logging.Handler):
    """ERROR ve üstü, istisna bilgisi taşıyan günlük kayıtlarını raporlayıcıya iletir."""

    def __init__(self, reporter: CrashReporter) -> None:
        super().__init__(level=logging.ERROR)
        self.reporter = reporter

    def emit(self, record: logging.LogRecord) -> None:
        if not record.exc_info or record.name.startswith(__name__):
            return
        exc_type, exc, tb = record.exc_info
        if exc_type is None or exc is None:
            return
        with contextlib.suppress(Exception):
            stack = "".join(traceback.format_exception(exc_type, exc, tb))
            message = f"{record.getMessage()} — {exc}"
            self.reporter.capture(record.name, exc_type.__name__, message, stack)
