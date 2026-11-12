"""Telefon bildirimleri (Web Push): RFC 8291 şifreleme, VAPID imzası, abonelik doğrulaması,
gönderim kuyruğu ve uzaktan kontrol komutları.

Bildirim içeriği motorda tarayıcının anahtarına şifrelenir; testte telefon tarafı gibi çözülüp
içerik doğrulanır."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ati_engine.core.events import TradeNotice
from ati_engine.notify.telegram import format_trade
from ati_engine.notify.trade_text import trade_body, trade_title
from ati_engine.remote.crypto import EngineIdentity, KeyAgreement
from ati_engine.remote.push import RATE_PER_MINUTE, PushNotifier
from ati_engine.remote.service import RemoteService
from ati_engine.remote.webpush import (
    PushError,
    Subscription,
    VapidKey,
    b64url,
    encrypt,
    unb64url,
)
from ati_engine.storage.database import Database
from remote_device import DeviceSim

ENDPOINT = "https://web.push.apple.com/QGFrZWVwLXRlc3QtdG9rZW4"


class Phone:
    """Tarayıcı tarafı: abonelik anahtarları ve gelen bildirimi çözme."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )

    def args(self, endpoint: str = ENDPOINT) -> dict[str, str]:
        return {"endpoint": endpoint, "p256dh": b64url(self.public), "auth": b64url(self.auth)}

    def decrypt(self, body: bytes) -> dict[str, Any]:
        salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        sender_raw = body[21 : 21 + idlen]
        assert rs == 4096 and idlen == 65
        sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_raw)
        shared = self.key.exchange(ec.ECDH(), sender)

        def mac(k: bytes, d: bytes) -> bytes:
            return hmac.new(k, d, hashlib.sha256).digest()

        ikm = mac(mac(self.auth, shared), b"WebPush: info\x00" + self.public + sender_raw + b"\x01")
        prk = mac(salt, ikm)
        cek = mac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
        nonce = mac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
        plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
        assert plain.endswith(b"\x02")
        return dict(json.loads(plain[:-1]))


class PushService:
    """Sahte bildirim servisi (Apple/Google yerine)."""

    def __init__(self, status: int = 201) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


def test_rfc8291_example_is_reproduced() -> None:
    """RFC 8291 Ek A: aynı anahtar ve tuzla birebir aynı şifreli gövde."""
    sender = ec.derive_private_key(
        int.from_bytes(unb64url("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
        ec.SECP256R1(),
    )
    body = encrypt(
        b"When I grow up, I want to be a watermelon",
        unb64url(
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
        ),
        unb64url("BTBZMqHH6r4Tts7J_aSIgg"),
        sender_key=sender,
        salt=unb64url("DGv6ra1nlYgDCS1FRnbzlw"),
    )
    assert b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS"
        "6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_"
        "Qulcy4a-fN"
    )


def test_vapid_token_is_es256_signed_for_the_push_service() -> None:
    vapid = VapidKey.generate()
    again = VapidKey.from_private_raw(vapid.private_raw())
    assert again.public_raw == vapid.public_raw and len(vapid.public_raw) == 65
    header = vapid.authorization(ENDPOINT, "https://canarslan.net.tr", now=1_800_000_000)
    assert header.startswith("vapid t=") and header.endswith(f", k={vapid.public_b64url}")
    token = header.removeprefix("vapid t=").split(",", 1)[0]
    head, claims, signature = token.split(".")
    assert json.loads(unb64url(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(unb64url(claims)) == {
        "aud": "https://web.push.apple.com",
        "exp": 1_800_000_000 + 50 * 60,  # Apple en çok 1 saat kabul eder
        "sub": "https://canarslan.net.tr",
    }
    raw = unb64url(signature)
    assert len(raw) == 64  # DER değil, r||s
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), vapid.public_raw)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_subscription_accepts_only_known_push_services() -> None:
    phone = Phone()
    for endpoint in (
        ENDPOINT,
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ):
        assert Subscription.parse(phone.args(endpoint)).endpoint == endpoint
    for endpoint in (
        "http://web.push.apple.com/abc",  # şifresiz
        "https://evil.example/abc",  # rastgele adres (motor oraya istek atmaz)
        "https://push.apple.com.evil.example/abc",
        "https://127.0.0.1/abc",
        "",
    ):
        with pytest.raises(PushError):
            Subscription.parse(phone.args(endpoint))
    with pytest.raises(PushError):
        Subscription.parse({**phone.args(), "p256dh": b64url(b"\x04" + b"\x01" * 64)})
    with pytest.raises(PushError):
        Subscription.parse({**phone.args(), "auth": b64url(b"kisa")})
    local = Subscription.parse(
        phone.args("http://127.0.0.1:9999/push"), extra_hosts=("127.0.0.1",), allow_http=True
    )
    assert local.endpoint.startswith("http://127.0.0.1")


def test_trade_text_has_every_detail() -> None:
    opened = TradeNotice(
        market="usdm_futures", mode="testnet", symbol="BTCUSDT", action="opened", side="long",
        quantity="0.004", price="96120.5", stop_loss="95000", take_profit="98400", score=78.0,
        reason="Kırılım + hacim artışı", leverage=3,
    )  # fmt: skip
    assert trade_title(opened) == "📈 BTCUSDT Long açıldı"
    assert trade_body(opened) == (
        "Demo · Futures · 0.004 @ 96120.5\nstop 95000 · hedef 98400 · 3x\n"
        "puan 78 · Kırılım + hacim artışı"
    )
    closed = TradeNotice(
        market="usdm_futures", mode="live", symbol="SOLUSDT", action="closed", side="short",
        quantity="3", price="177.79", net_pnl="13.83", entry_price="182.40", pnl_pct=2.53,
        close_reason="kâr al hedefi", duration_s=2520,
    )  # fmt: skip
    assert trade_title(closed) == "✅ SOLUSDT Short kapandı · +13.83 USDT (%+2.53)"
    assert trade_body(closed) == (
        "GERÇEK · Futures · 3 @ 177.79\ngiriş 182.40 → çıkış 177.79 · kâr al hedefi · 42 dk"
    )
    loss = TradeNotice(
        market="spot", mode="testnet", symbol="ETHUSDT", action="closed", side="long",
        quantity="0.05", price="3404.2", net_pnl="-0.79",
    )  # fmt: skip
    assert trade_title(loss).startswith("🔻 ETHUSDT Long kapandı · -0.79 USDT")
    telegram = format_trade(closed)
    assert "Net kâr/zarar: 13.83 USDT (%+2.53)" in telegram and "kâr al hedefi" in telegram


async def test_notifier_encrypts_for_the_phone_and_drops_expired(db: Database) -> None:
    service = PushService()
    phone = Phone()
    notifier = PushNotifier(
        db,
        VapidKey.generate(),
        subject="https://canarslan.net.tr",
        client=httpx.AsyncClient(transport=httpx.MockTransport(service.handler)),
    )
    await db.execute(
        "INSERT INTO remote_devices (id, name, signing_key, guarded_key, protection, paired_at) "
        "VALUES ('cihaz-1', 'iPhone', 'x', 'x', 'browser', 0)"
    )
    await notifier.store.save("cihaz-1", Subscription.parse(phone.args()), 1)
    [(device_id, sub)] = await notifier.store.active()
    ok, _ = await notifier.deliver(
        device_id, sub, {"title": "📈 BTCUSDT Long açıldı"}, urgency="high"
    )
    assert ok
    request = service.requests[0]
    assert str(request.url) == ENDPOINT
    assert request.headers["Content-Encoding"] == "aes128gcm"
    assert request.headers["Urgency"] == "high" and request.headers["TTL"] == "3600"
    assert request.headers["Authorization"].startswith("vapid t=")
    assert b"BTCUSDT" not in request.content  # içerik bildirim servisine şifreli gider
    assert phone.decrypt(request.content) == {"title": "📈 BTCUSDT Long açıldı"}

    # Dakikalık sınır: fazlası düşürülür.
    assert all(notifier._allowed("cihaz-2") for _ in range(RATE_PER_MINUTE))
    assert not notifier._allowed("cihaz-2")

    # Telefon izni kaldırdı: servis 410 döner, abonelik silinir.
    service.status = 410
    ok, reason = await notifier.deliver(device_id, sub, {"title": "x"})
    assert not ok and "yeniden açın" in reason
    assert await notifier.store.active() == []


async def test_phone_subscribes_receives_trades_and_revoke_stops_it(db: Database) -> None:
    push_service = PushService()
    notifier = PushNotifier(
        db,
        VapidKey.generate(),
        subject="https://canarslan.net.tr",
        client=httpx.AsyncClient(transport=httpx.MockTransport(push_service.handler)),
    )

    async def snapshot() -> dict[str, Any]:
        return {"engine": {"state": "running"}}

    remote = RemoteService(
        db=db,
        identity=EngineIdentity.generate(),
        kx=KeyAgreement.generate(),
        relay_url="wss://relay.example",
        executors={},
        snapshot=snapshot,
        push=notifier,
    )
    qr = json.loads(remote.pairing.start("wss://relay.example")[0])
    device = DeviceSim("iPhone (tarayıcı)", protection="browser")
    assert (await remote.handle(device.pair_request(qr), device.device_id) or {})["ok"]
    engine_id = remote.identity.engine_id
    phone = Phone()

    bad = await remote.handle(
        device.command(engine_id, "push_subscribe", phone.args("https://evil.example/x")),
        device.device_id,
    )
    assert bad is not None and not bad["ok"] and "Bilinmeyen" in bad["message"]
    ok = await remote.handle(
        device.command(engine_id, "push_subscribe", phone.args()), device.device_id
    )
    assert ok is not None and ok["ok"], ok
    status = await remote.status()
    assert status["devices"][0]["push"] is True

    test = await remote.handle(device.command(engine_id, "push_test", {}), device.device_id)
    assert test is not None and test["ok"], test
    assert phone.decrypt(push_service.requests[-1].content)["kind"] == "test"

    # İşlem bildirimi: telefon bağlı değilken de bildirim servisine gider.
    remote.enabled = True
    notifier.start()
    await remote.notify("trade", "📈 BTCUSDT Long açıldı", "Demo · Futures", push=True, urgent=True)
    await remote.notify("whale", "Balina", "önemsiz")  # push=False: bildirim gitmez
    for _ in range(100):
        if len(push_service.requests) >= 2:
            break
        await asyncio.sleep(0.01)
    assert len(push_service.requests) == 2
    message = phone.decrypt(push_service.requests[-1].content)
    assert message["title"] == "📈 BTCUSDT Long açıldı" and message["kind"] == "trade"
    assert push_service.requests[-1].headers["Urgency"] == "high"

    # Eşleştirme masaüstünden kaldırılınca abonelik silinir; bildirim gitmez.
    assert await remote.registry.revoke(device.device_id, int(time.time() * 1000))
    assert await notifier.store.active() == []
    await remote.notify("trade", "📉 kapandı", "x", push=True)
    await asyncio.sleep(0.05)
    assert len(push_service.requests) == 2
    await notifier.stop()


def test_snapshot_carries_sender_key(tmp_path: Path) -> None:
    vapid = VapidKey.generate()
    assert base64.urlsafe_b64decode(vapid.public_b64url + "=") == vapid.public_raw
