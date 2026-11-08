"""Aşama 15: motor lisans yöneticisi — etkinleştirme, kira doğrulama, çevrim dışı tolerans, saat
geri alma, sunucu reddi, işlem kapısı (hazırlık koşulu) ve telefon sınırı. Sahte lisans sunucusu
(httpx MockTransport) gerçek sunucunun imza kurallarını uygular; bulutla uçtan uca test ayrıdır
(``test_license_e2e.py``)."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ati_engine.config import LicenseSettings
from ati_engine.core.models import EngineState
from ati_engine.licensing.keys import InvalidLicenseKey, key_hint, normalize
from ati_engine.licensing.lease import LeaseError, verify_lease
from ati_engine.licensing.manager import (
    CONDITION,
    LicenseManager,
    LicenseRejected,
    LicenseUnavailable,
)
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.database import Database

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "shared/protocol/test-vectors/license-v1.json"
    ).read_text(encoding="utf-8")
)
HOUR = 3_600_000
DAY = 24 * HOUR


class Clock:
    def __init__(self, now: int = 1_800_000_000_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class FakeServer:
    """Bulut lisans servisinin davranışını taklit eder (imza doğrulama dâhil)."""

    def __init__(self, lclock: Clock) -> None:
        self.signing = Ed25519PrivateKey.generate()
        public = self.signing.public_key().public_bytes_raw()
        self.kid = hashlib.sha256(public).hexdigest()[:16]
        self.public_b64 = base64.b64encode(public).decode()
        self.clock = lclock
        self.skew_ms = 0  # sunucu saati - motor saati
        self.device_keys: dict[str, bytes] = {}
        self.reject: tuple[int, str, str] | None = None
        self.offline = False
        self.license_expires_at: int | None = None
        self.requests: list[dict[str, Any]] = []
        self.companion_limit = 2

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("ağ yok", request=request)
        message = json.loads(request.content)
        payload = json.loads(message["p"])
        self.requests.append(payload)
        if payload["type"] == "activate":
            key = base64.b64decode(payload["device_key"])
        else:
            key = self.device_keys[payload["device_id"]]
        Ed25519PublicKey.from_public_bytes(key).verify(
            base64.b64decode(message["s"]), message["p"].encode()
        )
        if self.reject:
            status, code, text = self.reject
            return httpx.Response(status, json={"detail": {"code": code, "message": text}})
        if payload["type"] == "deactivate":
            return httpx.Response(200, json={"status": "ok"})
        device_id = payload.get("device_id") or str(uuid.uuid4())
        if payload["type"] == "activate":
            normalize(payload["license_key"])
            self.device_keys[device_id] = key
            fingerprint = payload["fingerprint"]
        else:
            fingerprint = self.fingerprint
        self.fingerprint = fingerprint
        now = self.clock() + self.skew_ms
        lease = {
            "v": 1,
            "type": "license_lease",
            "lease_id": str(uuid.uuid4()),
            "license_id": "lic-1",
            "serial": 1,
            "plan_code": "d30_1dev",
            "plan_name": "30 Gün - 1 Cihaz",
            "status": "active",
            "license_expires_at": self.license_expires_at,
            "device_limit": 1,
            "companion_device_limit": self.companion_limit,
            "device_id": device_id,
            "device_key": base64.b64encode(self.device_keys[device_id]).decode(),
            "fingerprint": fingerprint,
            "issued_at": now,
            "valid_until": now + DAY,
            "offline_until": now + 3 * DAY,
            "kid": self.kid,
        }
        text = json.dumps(lease, sort_keys=True, separators=(",", ":"))
        signed = {"p": text, "s": base64.b64encode(self.signing.sign(text.encode())).decode()}
        return httpx.Response(200, json={"lease": signed, "server_time_ms": now})


@pytest.fixture
def lclock() -> Clock:
    return Clock()


@pytest.fixture
def server(lclock: Clock) -> FakeServer:
    return FakeServer(lclock)


@pytest.fixture
def vault(db: Database) -> SecretVault:
    return SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key()))


def make(
    db: Database,
    vault: SecretVault,
    server: FakeServer,
    lclock: Clock,
    *,
    enforce: bool = False,
    safety: SafetyCoordinator | None = None,
    fingerprint: str = "makine-1",
) -> LicenseManager:
    settings = LicenseSettings(
        server_url="https://lisans.test",
        trusted_keys={server.kid: server.public_b64},
        enforce=enforce,
    )
    return LicenseManager(
        settings=settings,
        db=db,
        vault=vault,
        safety=safety,
        clock=lclock,
        transport=server.transport(),
        fingerprint_override=fingerprint,
        device_name="Test PC",
    )


KEY = VECTORS["keys"]["valid"][0]["key"]


# --- Anahtar biçimi (bulutla ortak vektörler) ----------------------------------------------------


def test_key_vectors_match_cloud() -> None:
    for item in VECTORS["keys"]["valid"]:
        assert normalize(item["key"]) == item["normalized"]
        assert normalize(item["key"].lower().replace("-", " ")) == item["normalized"]
        assert key_hint(item["key"]) == item["hint"]
    for bad in VECTORS["keys"]["invalid"]:
        with pytest.raises(InvalidLicenseKey):
            normalize(bad)


def test_lease_vector_verifies_and_binds_to_device() -> None:
    lease_vec = VECTORS["lease"]
    trusted = {lease_vec["kid"]: base64.b64decode(lease_vec["public_key"])}
    device_key = base64.b64decode(lease_vec["device_key"])
    fingerprint = bytes.fromhex(lease_vec["fingerprint"])
    lease = verify_lease(
        lease_vec["signed"], trusted, device_key=device_key, fingerprint=fingerprint
    )
    assert lease.license_id == lease_vec["license_id"]
    with pytest.raises(LeaseError) as other:
        verify_lease(lease_vec["signed"], trusted, device_key=device_key, fingerprint=b"x" * 32)
    assert other.value.code == "other_device"
    tampered = dict(lease_vec["signed"])
    tampered["p"] = tampered["p"].replace('"serial":', '"serial":9')
    with pytest.raises(LeaseError):
        verify_lease(tampered, trusted, device_key=device_key, fingerprint=fingerprint)
    with pytest.raises(LeaseError) as unknown:
        verify_lease(lease_vec["signed"], {}, device_key=device_key, fingerprint=fingerprint)
    assert unknown.value.code == "unknown_key"


# --- Yönetici ------------------------------------------------------------------------------------


async def test_not_configured_without_trusted_keys(db: Database, vault: SecretVault) -> None:
    manager = LicenseManager(settings=LicenseSettings(), db=db, vault=vault)
    await manager.load()
    assert manager.status()["state"] == "not_configured" and not manager.valid
    with pytest.raises(LicenseUnavailable):
        await manager.activate(KEY)
    assert LicenseSettings().server_url == "https://api.canarslan.net.tr"


async def test_activation_persists_and_survives_restart(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    assert manager.state() == "unlicensed"
    with pytest.raises(InvalidLicenseKey):
        await manager.activate(KEY[:-1] + ("0" if KEY[-1] != "0" else "1"))
    assert server.requests == []  # yazım hatası sunucuya gitmedi

    status = await manager.activate(KEY.lower())
    assert status["state"] == "active" and status["valid"]
    assert status["plan_name"] == "30 Gün - 1 Cihaz" and status["key_hint"] == key_hint(KEY)
    request = server.requests[0]
    assert request["license_key"] == KEY and request["name"] == "Test PC"
    assert request["fingerprint"] == hashlib.sha256(b"ati-device-v1|makine-1").hexdigest()
    # Anahtarın kendisi yerel veritabanına yazılmaz.
    dump = json.dumps(await db.fetchall("SELECT * FROM license_state"))
    assert KEY not in dump and normalize(KEY) not in dump

    again = make(db, vault, server, lclock)
    await again.load()
    assert again.state() == "active" and again.lease_id == "lic-1"
    # Veritabanı başka bilgisayara kopyalanırsa kira geçersizdir.
    other_pc = make(db, vault, server, lclock, fingerprint="makine-2")
    await other_pc.load()
    assert other_pc.state() == "unlicensed" and "başka bir bilgisayara" in (
        other_pc.last_error or ""
    )


async def test_offline_tolerance_then_expiry(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    server.offline = True
    lclock.now += DAY + HOUR
    status = await manager.refresh()
    assert status["state"] == "offline_grace" and status["valid"]
    assert status["last_error"] == "Lisans sunucusuna ulaşılamadı"
    lclock.now += 2 * DAY
    assert manager.state() == "lease_expired" and not manager.valid
    server.offline = False
    assert (await manager.refresh())["state"] == "active"


async def test_server_time_offset_is_used(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    server.skew_ms = 2 * DAY  # motor saati 2 gün geride
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    assert manager.state() == "active"  # yerel saatle bakılsaydı kira "gelecekte" olurdu
    assert manager.offset_ms == 2 * DAY


async def test_clock_rollback_is_detected(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    lclock.now += 20 * HOUR
    await manager._update_readiness()  # gözlenen en ileri zaman kaydedilir
    lclock.now -= 15 * HOUR  # saat geri alındı (tolerans uzatma denemesi)
    assert manager.state() == "clock_error" and not manager.valid
    restarted = make(db, vault, server, lclock)
    await restarted.load()
    assert restarted.state() == "clock_error"  # yeniden başlatma tespiti silmez
    assert (await restarted.refresh())["state"] == "active"  # çevrim içi yenileme düzeltir


async def test_license_term_expiry(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    server.license_expires_at = lclock.now + 2 * HOUR
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    lclock.now += 3 * HOUR
    assert manager.state() == "license_expired"


@pytest.mark.parametrize("code", ["frozen", "cancelled", "not_activated", "bad_signature"])
async def test_terminal_rejection_revokes(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock, code: str
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    server.reject = (403, code, "Sunucu açıklaması")
    status = await manager.refresh()
    assert status["state"] == "revoked" and status["message"] == "Sunucu açıklaması"
    restarted = make(db, vault, server, lclock)
    await restarted.load()
    assert restarted.state() == "revoked"


async def test_transient_rejection_keeps_lease(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    server.reject = (409, "replay", "Bu istek daha önce kullanıldı")
    assert (await manager.refresh())["state"] == "active"


async def test_activation_rejection_is_reported(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    server.reject = (409, "device_limit", "Bilgisayar sınırına ulaşıldı")
    with pytest.raises(LicenseRejected) as exc:
        await manager.activate(KEY)
    assert exc.value.code == "device_limit" and manager.state() == "unlicensed"


async def test_deactivate(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    server.offline = True
    with pytest.raises(LicenseUnavailable):
        await manager.deactivate()
    assert manager.state() == "active"  # sunucuya ulaşılamadı: yer boşaltılamadı, kira korunur
    server.offline = False
    assert (await manager.deactivate())["state"] == "unlicensed"
    assert server.requests[-1]["type"] == "deactivate"


async def test_requests_have_increasing_timestamps(
    db: Database, vault: SecretVault, server: FakeServer, lclock: Clock
) -> None:
    manager = make(db, vault, server, lclock)
    await manager.load()
    await manager.activate(KEY)
    for _ in range(3):
        await manager.refresh()  # saat ilerlemese de damga artar (sunucu tekrar oynatmayı reddeder)
    stamps = [r["ts_ms"] for r in server.requests]
    assert stamps == sorted(set(stamps))


# --- İşlem kapısı ve telefon sınırı -------------------------------------------------------------


async def test_enforced_license_gates_new_trades(
    db: Database,
    vault: SecretVault,
    server: FakeServer,
    lclock: Clock,
    coordinator: SafetyCoordinator,
) -> None:
    manager = make(db, vault, server, lclock, enforce=True, safety=coordinator)
    await manager.load()
    await coordinator.boot_complete()
    assert coordinator.state.state is EngineState.SAFE_MODE
    condition = next(c for c in coordinator.conditions() if c.name == CONDITION)
    assert not condition.ready and "lisans" in condition.detail.lower()
    await manager.activate(KEY)
    assert coordinator.state.state is EngineState.RUNNING
    server.reject = (403, "frozen", "Lisans dondurulmuş")
    await manager.refresh()
    assert coordinator.state.state is EngineState.SAFE_MODE
    assert manager.companion_limit() == 0


async def test_unenforced_license_does_not_gate(
    db: Database,
    vault: SecretVault,
    server: FakeServer,
    lclock: Clock,
    coordinator: SafetyCoordinator,
) -> None:
    manager = make(db, vault, server, lclock, enforce=False, safety=coordinator)
    await manager.load()
    await coordinator.boot_complete()
    assert all(c.name != CONDITION for c in coordinator.conditions())
    assert coordinator.state.state is EngineState.RUNNING
    assert manager.companion_limit() is None


def test_enforce_requires_trusted_key() -> None:
    with pytest.raises(ValueError, match="güvenilir"):
        LicenseSettings(enforce=True)
    with pytest.raises(ValueError, match="https"):
        LicenseSettings(server_url="http://lisans.example.com")
    with pytest.raises(ValueError, match="Geçersiz kira anahtarı"):
        LicenseSettings(trusted_keys={"0000000000000000": base64.b64encode(b"k" * 32).decode()})
