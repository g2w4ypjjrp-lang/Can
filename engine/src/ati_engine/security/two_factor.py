"""Uygulama doğrulaması (isteğe bağlı iki adımlı doğrulama): kritik işlemler için doğrulama kodu.

Kullanıcı Ayarlar → Güvenlik'ten açar: QR kodu Google Authenticator / Microsoft Authenticator gibi
bir uygulamayla okutulur, ilk kodla etkinleşir ve 8 kurtarma kodu bir kez gösterilir. Açıkken
aşağıdaki işlemler (yönetim panelindeki lisans silme gibi) 6 haneli kod ister:

* Gerçek para moduna geçiş ve gerçek parayla botu başlatma
* Gerçek hesap anahtarı ekleme / silme
* Acil durdurmayı kaldırma, günlük zarar kilidini kaldırma
* Lisansı bu bilgisayardan kaldırma
* Telefon eşleme (yeni cihaz)
* Doğrulamayı kapatma

Gizli anahtar şifreli kasada saklanır; aynı kod ikinci kez kabul edilmez (tekrar saldırısı);
5 dakikada 5'ten fazla hatalı kodda geçici olarak beklenir. Kurtarma kodları özetleriyle saklanır
ve her biri bir kez kullanılır.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from collections import deque
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ati_engine.security.vault import SecretVault
from ati_engine.storage.settings_store import SettingsStore

STEP_S = 30
WINDOW = 1  # ± bir adım (saat farkı payı)
SECRET_KEY = "app.2fa.secret"  # noqa: S105 - kasadaki kaydın adı, gizli değer değil
PENDING_KEY = "app.2fa.pending"
STATE_KEY = "app.2fa.state"  # {"last_step": int, "recovery": [özet, ...]}
RECOVERY_COUNT = 8
MAX_FAILURES = 5
FAILURE_WINDOW_S = 300

ACTIONS: dict[str, str] = {
    "live_mode": "Gerçek para moduna geçiş",
    "live_bot": "Gerçek parayla botu başlatma",
    "live_key": "Gerçek hesap anahtarı ekleme ya da silme",
    "kill_switch_release": "Acil durdurmayı kaldırma",
    "risk_release_day": "Günlük zarar kilidini kaldırma",
    "reconcile_adopt": "Yerel pozisyon kaydını borsaya eşitleme",
    "license_deactivate": "Lisansı bu bilgisayardan kaldırma",
    "phone_pairing": "Telefon eşleme",
    "two_factor_disable": "Doğrulamayı kapatma",
}


def totp(secret: bytes, step: int) -> str:
    """RFC 6238 (HMAC-SHA1, 6 hane)."""
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _b32(raw: bytes) -> str:
    return base64.b32encode(raw).decode().rstrip("=")


def _unb32(text: str) -> bytes:
    return base64.b32decode(text + "=" * (-len(text) % 8))


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _normalize(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


class VerificationError(Exception):
    """Kod gerekli ya da hatalı (``reason``: required / invalid / locked)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class TwoFactor:
    def __init__(
        self,
        vault: SecretVault,
        store: SettingsStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._vault = vault
        self._store = store
        self._clock = clock
        self._failures: deque[float] = deque()

    async def enabled(self) -> bool:
        return await self._vault.get(SECRET_KEY) is not None

    async def status(self) -> dict[str, Any]:
        state = await self._state()
        return {
            "enabled": await self.enabled(),
            "recovery_left": len(state.get("recovery", [])),
            "protected": [{"key": k, "label": v} for k, v in ACTIONS.items()],
        }

    async def _state(self) -> dict[str, Any]:
        value = await self._store.get(STATE_KEY)
        return value if isinstance(value, dict) else {}

    async def begin_setup(self, label: str = "Bilgisayar") -> dict[str, str]:
        if await self.enabled():
            raise VerificationError("enabled", "Doğrulama zaten açık")
        secret = _b32(secrets.token_bytes(20))
        await self._vault.put(PENDING_KEY, secret)
        issuer = "AI Trading Intelligence"
        uri = (
            f"otpauth://totp/{quote(issuer)}:{quote(label)}?secret={secret}"
            f"&issuer={quote(issuer)}&digits=6&period={STEP_S}"
        )
        return {"secret": secret, "uri": uri}

    def _matching_step(self, secret: bytes, code: str, last_step: int) -> int | None:
        now = int(self._clock() // STEP_S)
        for step in range(now - WINDOW, now + WINDOW + 1):
            if step > last_step and hmac.compare_digest(totp(secret, step), code):
                return step
        return None

    async def enable(self, code: str) -> list[str]:
        pending = await self._vault.get(PENDING_KEY)
        if pending is None:
            raise VerificationError("invalid", "Önce QR kodunu oluşturun")
        secret = _unb32(pending.get_secret_value())
        step = self._matching_step(secret, _normalize(code), -1)
        if step is None:
            raise VerificationError("invalid", "Kod hatalı. Uygulamadaki güncel kodu yazın")
        recovery = [
            f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
            for _ in range(RECOVERY_COUNT)
        ]
        await self._vault.put(SECRET_KEY, pending.get_secret_value())
        await self._vault.delete(PENDING_KEY)
        await self._store.set(
            STATE_KEY,
            {"last_step": step, "recovery": [_digest(_normalize(c)) for c in recovery]},
        )
        return recovery

    async def verify(self, code: str | None, *, action: str) -> None:
        """Doğrulama açıksa kodu denetler; kapalıysa hiçbir şey yapmaz."""
        stored = await self._vault.get(SECRET_KEY)
        if stored is None:
            return
        label = ACTIONS.get(action, "Bu işlem")
        now = self._clock()
        while self._failures and now - self._failures[0] > FAILURE_WINDOW_S:
            self._failures.popleft()
        if len(self._failures) >= MAX_FAILURES:
            raise VerificationError(
                "locked", "Çok fazla hatalı kod. Birkaç dakika bekleyip tekrar deneyin"
            )
        if not code or not code.strip():
            raise VerificationError("required", f"{label} için doğrulama kodu gerekli")
        normalized = _normalize(code)
        state = await self._state()
        secret = _unb32(stored.get_secret_value())
        if len(normalized) == 6 and normalized.isdigit():
            step = self._matching_step(secret, normalized, int(state.get("last_step", -1)))
            if step is not None:
                await self._store.set(STATE_KEY, {**state, "last_step": step})
                return
        else:
            digest = _digest(normalized)
            remaining = list(state.get("recovery", []))
            if digest in remaining:
                remaining.remove(digest)
                await self._store.set(STATE_KEY, {**state, "recovery": remaining})
                return
        self._failures.append(now)
        raise VerificationError("invalid", "Doğrulama kodu hatalı ya da kullanılmış")

    async def disable(self, code: str | None, *, verified: bool = False) -> None:
        """Doğrulamayı kapatır (kod, çağıran tarafından doğrulanmadıysa burada denetlenir)."""
        if not verified:
            await self.verify(code, action="two_factor_disable")
        await self._vault.delete(SECRET_KEY)
        await self._vault.delete(PENDING_KEY)
        await self._store.set(STATE_KEY, {})
