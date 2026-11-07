from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from ati_engine.core.models import Market
from ati_engine.security.binance_key_policy import evaluate_api_restrictions
from ati_engine.security.redaction import MASK, redact, redact_text
from ati_engine.security.vault import (
    AesGcmCipher,
    DpapiCipher,
    SecretVault,
    VaultError,
    default_cipher,
    load_or_create_dev_key,
)
from ati_engine.storage.database import Database

SAFE_KEY = {
    "ipRestrict": True,
    "createTime": 1623840271000,
    "enableInternalTransfer": False,
    "enableFutures": True,
    "enablePortfolioMarginTrading": False,
    "enableVanillaOptions": False,
    "permitsUniversalTransfer": False,
    "enableReading": True,
    "enableSpotAndMarginTrading": True,
    "enableWithdrawals": False,
    "enableMargin": False,
}


# --- Kasa ---------------------------------------------------------------------------------


async def test_vault_roundtrip_and_ciphertext_is_not_plaintext(db: Database) -> None:
    vault = SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))
    await vault.put("binance.api_secret", SecretStr("çok-gizli-değer"))
    row = await db.fetchone("SELECT ciphertext FROM secrets WHERE name = 'binance.api_secret'")
    assert row is not None
    assert b"gizli" not in bytes(row[0])
    value = await vault.get("binance.api_secret")
    assert value is not None
    assert value.get_secret_value() == "çok-gizli-değer"
    assert "çok-gizli" not in repr(value)
    assert await vault.names() == ["binance.api_secret"]
    assert await vault.delete("binance.api_secret")
    assert await vault.get("binance.api_secret") is None


async def test_vault_detects_tampering(db: Database) -> None:
    vault = SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))
    await vault.put("a", "değer")
    row = await db.fetchone("SELECT ciphertext FROM secrets WHERE name = 'a'")
    assert row is not None
    tampered = bytearray(row[0])
    tampered[-1] ^= 0x01
    await db.execute("UPDATE secrets SET ciphertext = ? WHERE name = 'a'", (bytes(tampered),))
    with pytest.raises(VaultError):
        await vault.get("a")


async def test_vault_ciphertext_bound_to_name(db: Database) -> None:
    """Bir kaydın şifreli verisi başka bir kaydın yerine taşınamaz (AAD)."""
    vault = SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))
    await vault.put("a", "A-değeri")
    await vault.put("b", "B-değeri")
    await db.execute(
        "UPDATE secrets SET ciphertext = (SELECT ciphertext FROM secrets WHERE name = 'a') "
        "WHERE name = 'b'"
    )
    with pytest.raises(VaultError):
        await vault.get("b")


async def test_vault_wrong_key_fails(db: Database) -> None:
    await SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key())).put("a", "x")
    with pytest.raises(VaultError):
        await SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key())).get("a")


async def test_vault_rejects_bad_names(db: Database) -> None:
    vault = SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))
    for bad in ["", "a b", "x" * 200, "a/b"]:
        with pytest.raises(ValueError, match="Geçersiz"):
            await vault.put(bad, "v")


def test_dev_key_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "k" / "dev.key"
    key = load_or_create_dev_key(path)
    assert len(key) == 32
    assert load_or_create_dev_key(path) == key
    if sys.platform != "win32":
        assert (path.stat().st_mode & 0o777) == 0o600


def test_default_cipher_per_platform(tmp_path: Path) -> None:
    cipher = default_cipher(tmp_path)
    assert cipher.provider == ("dpapi" if sys.platform == "win32" else "aesgcm")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnızca Windows'ta")
def test_dpapi_roundtrip() -> None:  # pragma: no cover - Windows CI'da çalışır
    cipher = DpapiCipher()
    blob = cipher.encrypt(b"gizli", aad=b"ad-1")
    assert cipher.decrypt(blob, aad=b"ad-1") == b"gizli"
    with pytest.raises(VaultError):
        cipher.decrypt(blob, aad=b"ad-2")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows dışı davranış")
def test_dpapi_unavailable_off_windows() -> None:
    with pytest.raises(VaultError):
        DpapiCipher()


# --- Maskeleme ------------------------------------------------------------------------------


def test_redact_by_key_name() -> None:
    data = {
        "api_key": "x",
        "apiSecret": "y",
        "nested": {"Authorization": "Bearer abc", "symbol": "BTCUSDT"},
        "items": [{"password": "p"}],
    }
    assert redact(data) == {
        "api_key": MASK,
        "apiSecret": MASK,
        "nested": {"Authorization": MASK, "symbol": "BTCUSDT"},
        "items": [{"password": MASK}],
    }


def test_redact_by_value_shape() -> None:
    fake_key = "FAKE" + "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWX"
    url = f"https://api.binance.com/api/v3/order?symbol=BTCUSDT&timestamp=1&signature={fake_key}"
    text = redact_text(f"istek: {url} anahtar={fake_key} Bearer abc.def")
    assert fake_key not in text
    assert "symbol=BTCUSDT" in text
    assert "Bearer ***" in text


# --- Binance API anahtar politikası --------------------------------------------------------------


def test_safe_key_is_accepted() -> None:
    verdict = evaluate_api_restrictions(
        SAFE_KEY, required_markets=[Market.SPOT, Market.USDM_FUTURES], trading_required=True
    )
    assert verdict.accepted
    assert verdict.findings == ()


def test_withdrawal_permission_blocks_key() -> None:
    verdict = evaluate_api_restrictions(
        {**SAFE_KEY, "enableWithdrawals": True},
        required_markets=[Market.SPOT],
        trading_required=True,
    )
    assert not verdict.accepted
    assert [f.code for f in verdict.blocking] == ["withdrawals_enabled"]


def test_transfer_permissions_block_key() -> None:
    verdict = evaluate_api_restrictions(
        {**SAFE_KEY, "enableInternalTransfer": True, "permitsUniversalTransfer": True},
        required_markets=[],
        trading_required=False,
    )
    assert {f.code for f in verdict.blocking} == {
        "internal_transfer_enabled",
        "universal_transfer_enabled",
    }


def test_missing_fields_are_treated_as_unsafe() -> None:
    verdict = evaluate_api_restrictions({}, required_markets=[], trading_required=False)
    assert not verdict.accepted
    assert "withdrawals_enabled" in {f.code for f in verdict.blocking}
    assert "reading_disabled" in {f.code for f in verdict.blocking}


def test_trading_permission_required_per_market() -> None:
    verdict = evaluate_api_restrictions(
        {**SAFE_KEY, "enableFutures": False},
        required_markets=[Market.USDM_FUTURES],
        trading_required=True,
    )
    assert [f.code for f in verdict.blocking] == ["futures_trading_disabled"]
    # Yalnızca veri okuma (PAPER) modunda işlem yetkisi gerekmez.
    assert evaluate_api_restrictions(
        {**SAFE_KEY, "enableFutures": False, "enableSpotAndMarginTrading": False},
        required_markets=[Market.USDM_FUTURES],
        trading_required=False,
    ).accepted


def test_warnings_do_not_block() -> None:
    verdict = evaluate_api_restrictions(
        {**SAFE_KEY, "ipRestrict": False, "enableMargin": True},
        required_markets=[Market.SPOT],
        trading_required=True,
    )
    assert verdict.accepted
    assert {f.code for f in verdict.warnings} == {"no_ip_restriction", "margin_enabled"}
