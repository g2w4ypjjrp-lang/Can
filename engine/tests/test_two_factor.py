"""Uygulama doğrulaması: açıkken kritik işlemler (gerçek para, gerçek hesap anahtarı, acil
durdurmayı kaldırma, lisansı kaldırma, telefon eşleme) 6 haneli kod ister; kod tekrar
kullanılamaz, kurtarma kodu bir kez çalışır, hatalı kodlar sınırlanır."""

from __future__ import annotations

import base64

import pytest

from ati_engine.security.two_factor import TwoFactor, VerificationError, totp
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def code_for(secret: str, clock: Clock, offset_steps: int = 0) -> str:
    raw = base64.b32decode(secret + "=" * (-len(secret) % 8))
    return totp(raw, int(clock.now // 30) + offset_steps)


def test_rfc6238_vector() -> None:
    # RFC 6238 Ek B (SHA1, 59 sn → 94287082; 6 hane: 287082).
    assert totp(b"12345678901234567890", 59 // 30) == "287082"


async def test_setup_verify_replay_recovery_and_lockout(db: Database) -> None:
    clock = Clock()
    vault = SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))
    tf = TwoFactor(vault, SettingsStore(db), clock=clock)
    await tf.verify(None, action="live_mode")  # kapalıyken kod istenmez
    assert (await tf.status())["enabled"] is False

    setup = await tf.begin_setup()
    assert setup["uri"].startswith("otpauth://totp/") and setup["secret"] in setup["uri"]
    with pytest.raises(VerificationError):
        await tf.enable("000000")
    recovery = await tf.enable(code_for(setup["secret"], clock))
    assert len(recovery) == 8 and (await tf.status())["recovery_left"] == 8
    with pytest.raises(VerificationError):
        await tf.begin_setup()  # açıkken yeniden kurulmaz

    with pytest.raises(VerificationError) as missing:
        await tf.verify(None, action="live_mode")
    assert missing.value.reason == "required" and "Gerçek para" in str(missing.value)
    clock.now += 30
    good = code_for(setup["secret"], clock)
    await tf.verify(good, action="live_mode")
    with pytest.raises(VerificationError) as replay:
        await tf.verify(good, action="live_mode")  # aynı kod ikinci kez kabul edilmez
    assert replay.value.reason == "invalid"
    clock.now += 30
    await tf.verify(code_for(setup["secret"], clock), action="live_key")

    await tf.verify(
        recovery[0].lower(), action="license_deactivate"
    )  # kurtarma kodu, büyük/küçük harf fark etmez
    with pytest.raises(VerificationError):
        await tf.verify(recovery[0], action="license_deactivate")  # bir kez
    assert (await tf.status())["recovery_left"] == 7

    for _ in range(4):
        with pytest.raises(VerificationError):
            await tf.verify("123456", action="live_mode")
    with pytest.raises(VerificationError) as locked:
        await tf.verify(code_for(setup["secret"], clock, 1), action="live_mode")
    assert locked.value.reason == "locked"
    clock.now += 301  # bekleme süresi dolar
    await tf.disable(code_for(setup["secret"], clock))
    assert (await tf.status())["enabled"] is False
