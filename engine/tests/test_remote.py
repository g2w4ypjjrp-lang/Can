"""Aşama 13: uzaktan kontrol — eşleştirme ve komut doğrulaması. İmzasız, sahte imzalı,
değiştirilmiş, tekrar oynatılmış, eski, başka motora ait, izin listesi dışı ve Face ID gerektiren
komutların reddedildiği; geçerli komutun bir kez uygulandığı."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from ati_engine.remote.crypto import (
    EngineIdentity,
    KeyAgreement,
    SignatureError,
    channel_info,
    seal_json,
    verify_p256,
)
from ati_engine.remote.protocol import CommandVerifier, DeviceRegistry, PairingManager
from ati_engine.remote.service import RemoteService
from ati_engine.storage.database import Database
from remote_device import DeviceSim, now_ms


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    def executor(self, name: str):  # type: ignore[no-untyped-def]
        async def run(args: dict[str, Any], device: Any) -> str:
            self.calls.append((name, args, device.id))
            return f"{name} uygulandı"

        return run


async def make_service(
    db: Database, identity: EngineIdentity | None = None
) -> tuple[RemoteService, Recorder]:
    recorder = Recorder()
    names = [
        "engage_kill_switch",
        "pause_autotrade",
        "request_snapshot",
        "resume_autotrade",
        "release_kill_switch",
        "close_position",
        "close_all",
    ]

    async def snapshot() -> dict[str, Any]:
        return {"engine_state": "running"}

    service = RemoteService(
        db=db,
        identity=identity or EngineIdentity.generate(),
        kx=KeyAgreement.generate(),
        relay_url=None,
        executors={n: recorder.executor(n) for n in names},
        snapshot=snapshot,
    )
    return service, recorder


async def paired(db: Database) -> tuple[RemoteService, Recorder, DeviceSim]:
    service, recorder = await make_service(db)
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    device = DeviceSim()
    reply = await service.handle(device.pair_request(qr), device.device_id)
    assert reply is not None and reply["ok"], reply
    return service, recorder, device


def test_signature_primitives_match_ios_formats() -> None:
    device = DeviceSim()
    message = device.command("e" * 32, "engage_kill_switch")
    verify_p256(device.signing_key, base64.b64decode(message["s"]), message["p"].encode())
    with pytest.raises(SignatureError):
        verify_p256(device.signing_key, base64.b64decode(message["s"]), b"degistirilmis")
    identity = EngineIdentity.generate()
    signed = identity.signed({"type": "snapshot", "x": "ç"})
    assert DeviceSim.open_engine(identity.public_raw, signed)["x"] == "ç"
    restored = EngineIdentity.from_private_raw(identity.private_raw())
    assert restored.engine_id == identity.engine_id and len(identity.engine_id) == 32


# --- Eşleştirme -------------------------------------------------------------------------------


async def test_pairing_requires_qr_secret_and_is_single_use(db: Database) -> None:
    service, _ = await make_service(db)
    qr_text, expires = service.pairing.start("wss://relay.example")
    qr = json.loads(qr_text)
    assert qr["engine_id"] == service.identity.engine_id and expires > now_ms()
    assert base64.b64decode(qr["engine_key"]) == service.identity.public_raw

    attacker = DeviceSim("Aktarma servisi")
    forged_qr = {**qr, "pair": base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")}
    reply = await service.handle(attacker.pair_request(forged_qr), attacker.device_id)
    assert reply == {**reply, "ok": False, "reason": "bad_proof"}

    device = DeviceSim()
    request = device.pair_request(qr)
    tampered = {**request, "p": request["p"].replace("Test iPhone", "Sahte")}
    assert (await service.handle(tampered, device.device_id))["reason"] == "bad_proof"  # type: ignore[index]
    reply = await service.handle(request, device.device_id)
    assert reply is not None and reply["ok"] and reply["name"] == "Test iPhone"
    again = await service.handle(request, device.device_id)  # tek kullanımlık
    assert again is not None and again["reason"] == "no_session"
    devices = await service.registry.all()
    assert [d.id for d in devices] == [device.device_id]
    assert devices[0].protection == "software"


async def test_pairing_rejects_expired_session_and_key_mismatch(db: Database) -> None:
    clock = [now_ms()]
    registry = DeviceRegistry(db)
    identity = EngineIdentity.generate()
    manager = PairingManager(
        identity, registry, KeyAgreement.generate(), ttl_s=60, clock=lambda: clock[0]
    )
    qr = json.loads(manager.start("wss://r")[0])
    device = DeviceSim()
    other = DeviceSim()
    from ati_engine.remote.protocol import PairingError

    with pytest.raises(PairingError, match="device_id_mismatch"):
        await manager.complete(device.pair_request(qr, ts=clock[0]), other.device_id)
    clock[0] += 61_000
    with pytest.raises(PairingError, match="no_session"):
        await manager.complete(device.pair_request(qr, ts=clock[0]), device.device_id)


# --- Komutlar ----------------------------------------------------------------------------------


async def test_valid_command_executes_once(db: Database) -> None:
    service, recorder, device = await paired(db)
    engine_id = service.identity.engine_id
    message = device.command(engine_id, "engage_kill_switch", {"reason": "telefon"})
    result = await service.handle(message, device.device_id)
    assert (
        result is not None and result["ok"] and result["message"] == "engage_kill_switch uygulandı"
    )
    assert recorder.calls == [("engage_kill_switch", {"reason": "telefon"}, device.device_id)]
    replay = await service.handle(message, device.device_id)  # aynı mesaj tekrar
    assert replay is not None and replay["reason"] == "replay"
    assert len(recorder.calls) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "unsigned",
        "garbage_signature",
        "other_key",
        "tampered",
        "stale",
        "future",
        "wrong_engine",
        "old_seq",
        "not_allowed",
        "biometric",
        "spoofed_route",
    ],
)
async def test_attacks_are_rejected_and_never_executed(db: Database, attack: str) -> None:
    service, recorder, device = await paired(db)
    engine_id = service.identity.engine_id
    ok = device.command(engine_id, "pause_autotrade")
    assert (await service.handle(ok, device.device_id))["ok"]  # type: ignore[index]
    recorder.calls.clear()
    expected = {
        "unsigned": "malformed",
        "garbage_signature": "bad_signature",
        "other_key": "bad_signature",
        "tampered": "bad_signature",
        "stale": "stale",
        "future": "stale",
        "wrong_engine": "wrong_engine",
        "old_seq": "replay",
        "not_allowed": "not_allowed",
        "biometric": "biometric_required",
        "spoofed_route": "malformed",
    }[attack]
    route = device.device_id
    if attack == "unsigned":
        message: dict[str, str] = {"p": device.command(engine_id, "engage_kill_switch")["p"]}
    elif attack == "garbage_signature":
        message = {
            **device.command(engine_id, "engage_kill_switch"),
            "s": base64.b64encode(b"x" * 64).decode(),
        }
    elif attack == "other_key":
        intruder = DeviceSim("saldırgan")
        message = device.command(engine_id, "engage_kill_switch", signer=intruder.signing)
    elif attack == "tampered":
        signed = device.command(engine_id, "pause_autotrade")
        message = {**signed, "p": signed["p"].replace("pause_autotrade", "close_all")}
    elif attack == "stale":
        message = device.command(engine_id, "engage_kill_switch", ts=now_ms() - 10 * 60_000)
    elif attack == "future":
        message = device.command(engine_id, "engage_kill_switch", ts=now_ms() + 10 * 60_000)
    elif attack == "wrong_engine":
        message = device.command("0" * 32, "engage_kill_switch")
    elif attack == "old_seq":
        message = device.command(engine_id, "engage_kill_switch", seq=1)
    elif attack == "not_allowed":
        message = device.command(engine_id, "open_position", {"symbol": "BTCUSDT"}, key="guarded")
    elif attack == "biometric":
        message = device.command(engine_id, "close_all", key="signing")
    else:  # aktarma servisi mesajı başka bir cihazın kimliğiyle yönlendiriyor
        message = device.command(engine_id, "engage_kill_switch")
        route = DeviceSim().device_id
    result = await service.handle(message, route)
    assert result is not None and result["ok"] is False and result["reason"] == expected
    assert recorder.calls == []
    rows = await service.commands()
    assert rows[0]["accepted"] is False and rows[0]["reason"] == expected


async def test_guarded_commands_need_biometric_key(db: Database) -> None:
    service, recorder, device = await paired(db)
    engine_id = service.identity.engine_id
    args = {"market": "usdm_futures", "symbol": "BTCUSDT"}
    result = await service.handle(
        device.command(engine_id, "close_position", args, key="guarded"), device.device_id
    )
    assert result is not None and result["ok"]
    assert recorder.calls == [("close_position", args, device.device_id)]


async def test_unknown_and_revoked_devices(db: Database) -> None:
    service, recorder, device = await paired(db)
    engine_id = service.identity.engine_id
    stranger = DeviceSim("eşleşmemiş")
    result = await service.handle(
        stranger.command(engine_id, "engage_kill_switch"), stranger.device_id
    )
    assert result is not None and result["reason"] == "unknown_device"
    assert await service.registry.revoke(device.device_id, now_ms())
    result = await service.handle(device.command(engine_id, "engage_kill_switch"), device.device_id)
    assert result is not None and result["reason"] == "revoked_device"
    assert recorder.calls == []


async def test_sequence_survives_restart(db: Database) -> None:
    service, _, device = await paired(db)
    engine_id = service.identity.engine_id
    message = device.command(engine_id, "pause_autotrade")
    assert (await service.handle(message, device.device_id))["ok"]  # type: ignore[index]
    restarted, recorder = await make_service(db, service.identity)
    replay = await restarted.handle(message, device.device_id)
    assert replay is not None and replay["reason"] == "replay" and recorder.calls == []
    fresh = await restarted.handle(device.command(engine_id, "pause_autotrade"), device.device_id)
    assert fresh is not None and fresh["ok"]


async def test_concurrent_duplicate_is_executed_once(db: Database) -> None:
    import asyncio

    service, recorder, device = await paired(db)
    message = device.command(service.identity.engine_id, "engage_kill_switch")
    results = await asyncio.gather(*(service.handle(message, device.device_id) for _ in range(5)))
    assert sum(1 for r in results if r and r["ok"]) == 1
    assert len(recorder.calls) == 1


def test_verifier_allowlist_has_no_dangerous_commands() -> None:
    from ati_engine.remote.protocol import ALLOWED_COMMANDS

    forbidden = ("withdraw", "open", "limit", "key", "mode", "live", "transfer")
    assert not [c for c in ALLOWED_COMMANDS if any(f in c for f in forbidden)]
    assert ALLOWED_COMMANDS["engage_kill_switch"] == "signing"  # acil durdurma tek dokunuş
    assert {c for c, k in ALLOWED_COMMANDS.items() if k == "guarded"} == {
        "resume_autotrade",
        "release_kill_switch",
        "close_position",
        "close_all",
    }
    assert CommandVerifier  # içe aktarma


def test_shared_test_vectors_are_consistent() -> None:
    """iOS testlerinin kullandığı vektörler motor koduyla tutarlı olmalı."""
    from ati_engine.remote.crypto import (
        hmac_proof,
        key_id,
        relay_hello_text,
        unb64url,
        verify_ed25519,
    )

    path = (
        Path(__file__).resolve().parents[2]
        / "shared"
        / "protocol"
        / "test-vectors"
        / "remote-v1.json"
    )
    vectors = json.loads(path.read_text(encoding="utf-8"))
    engine = vectors["engine"]
    key = base64.b64decode(engine["key"])
    assert key_id(key) == engine["engine_id"]
    snap = engine["snapshot"]
    verify_ed25519(key, base64.b64decode(snap["s"]), snap["p"].encode())
    tampered = engine["tampered_snapshot"]
    with pytest.raises(SignatureError):
        verify_ed25519(key, base64.b64decode(tampered["s"]), tampered["p"].encode())
    device = vectors["device"]
    x963 = base64.b64decode(device["public_x963"])
    assert key_id(x963) == device["device_id"]
    command = device["command"]
    verify_p256(x963, base64.b64decode(command["s"]), command["p"].encode())
    pairing = vectors["pairing"]
    proof = hmac_proof(unb64url(pairing["secret_b64url"]), pairing["payload"].encode())
    assert base64.b64encode(proof).decode() == pairing["proof"]
    assert (
        vectors["relay"]["engine_hello_text"]
        == relay_hello_text("engine", engine["engine_id"], "1794100000000").decode()
    )


async def test_pairing_respects_license_companion_limit(db: Database) -> None:
    """Lisans zorunluyken kiradaki telefon sınırı (Aşama 15): sınır dolunca yeni telefon
    reddedilir ve (kanıt doğrulandığı için) nedeni telefona bildirilir; iptal edilen telefonun
    yeri boşalır; aynı telefon yeniden eşleşebilir."""
    limit: list[int | None] = [1]
    service = RemoteService(
        db=db,
        identity=EngineIdentity.generate(),
        kx=KeyAgreement.generate(),
        relay_url=None,
        executors={},
        snapshot=lambda: _empty_snapshot(),
        companion_limit=lambda: limit[0],
    )
    sent: list[dict[str, Any]] = []

    async def capture(device_id: str, payload: dict[str, Any], kx: bytes | None = None) -> None:
        sent.append(payload)

    service._send_to = capture  # type: ignore[method-assign]
    first, second = DeviceSim("Telefon 1"), DeviceSim("Telefon 2")
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    assert (await service.handle(first.pair_request(qr), first.device_id))["ok"]
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    reply = await service.handle(second.pair_request(qr), second.device_id)
    assert reply is not None and not reply["ok"] and reply["reason"] == "device_limit"
    assert sent[-1]["reason"] == "device_limit"  # telefona bildirildi
    # Aynı telefonun yeniden eşleşmesi yer tüketmez.
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    assert (await service.handle(first.pair_request(qr), first.device_id))["ok"]
    # Lisans geçersizse (sınır 0) yeni telefon eşleşemez; iptal edilen yer boşalır.
    await service.registry.revoke(first.device_id, 1)
    limit[0] = 0
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    assert not (await service.handle(second.pair_request(qr), second.device_id))["ok"]
    limit[0] = 1
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    assert (await service.handle(second.pair_request(qr), second.device_id))["ok"]
    # Diğer eşleştirme hatalarına yanıt gönderilmez.
    count = len(sent)
    await service.handle(DeviceSim().pair_request(qr), "baska")
    assert len(sent) == count


async def _empty_snapshot() -> dict[str, Any]:
    return {}


# --- Uçtan uca şifreleme (Aşama 18) ----------------------------------------------------------------


class FakeRelay:
    """Motorun aktarma bağlantısı yerine: gönderilen çerçeveleri toplar."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send(self, text: str) -> None:
        self.frames.append(json.loads(text))


async def test_relay_sees_only_ciphertext_and_routing(db: Database) -> None:
    service, recorder = await make_service(db)
    relay = FakeRelay()
    service._ws = relay
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    assert base64.b64decode(qr["engine_kx"]) == service.kx.public_x963
    engine_kx = base64.b64decode(qr["engine_kx"])
    engine_key = base64.b64decode(qr["engine_key"])
    engine_id = qr["engine_id"]
    device = DeviceSim("Ayşe'nin iPhone'u")
    await service._dispatch(
        {
            "type": "from_device",
            "device_id": device.device_id,
            "msg": device.seal(engine_kx, engine_id, device.pair_request(qr)),
        }
    )
    assert [d.encrypted for d in await service.registry.all()] == [True]
    command = device.command(engine_id, "engage_kill_switch", {"reason": "gizli-neden-42"})
    await service._dispatch(
        {
            "type": "from_device",
            "device_id": device.device_id,
            "msg": device.seal(engine_kx, engine_id, command),
        }
    )
    assert [c[0] for c in recorder.calls] == ["engage_kill_switch"]
    assert relay.frames, "motor yanıt göndermeli"
    types = []
    for frame in relay.frames:
        assert set(frame) == {"type", "device_id", "msg"} and set(frame["msg"]) == {
            "v",
            "e",
            "n",
            "c",
        }
        text = json.dumps(frame, ensure_ascii=False)
        for secret in ("Ayşe", "engage_kill_switch", "snapshot", "pair_result", "engine_state"):
            assert secret not in text  # aktarma servisi içeriği göremez
        payload = device.open_sealed(engine_key, engine_id, frame["msg"])
        types.append(payload["type"])
    assert {"pair_result", "result", "snapshot"} <= set(types)


async def test_plaintext_tampered_and_misrouted_messages_are_dropped(db: Database) -> None:
    service, recorder, device = await paired(db)
    service._ws = FakeRelay()
    engine_id = service.identity.engine_id
    other = DeviceSim("başka telefon")
    command = device.command(engine_id, "engage_kill_switch")
    sealed = device.seal(service.kx.public_x963, engine_id, command)
    flipped = {**sealed, "c": base64.b64encode(
        bytes([base64.b64decode(sealed["c"])[0] ^ 1]) + base64.b64decode(sealed["c"])[1:]
    ).decode()}  # fmt: skip
    wrong_direction = seal_json(
        service.kx.public_x963, command, channel_info("e2d", engine_id, device.device_id)
    )
    attempts = [
        (command, device.device_id),  # şifresiz (eski biçim)
        (flipped, device.device_id),  # değiştirilmiş şifreli metin
        (sealed, other.device_id),  # aktarma servisi başka cihaza yönlendiriyor
        (wrong_direction, device.device_id),  # yön karıştırma
        (seal_json(KeyAgreement.generate().public_x963, command,
                   channel_info("d2e", engine_id, device.device_id)), device.device_id),
        ({"v": 2, "e": "", "n": "", "c": ""}, device.device_id),
        ("metin", device.device_id),
    ]  # fmt: skip
    for msg, route in attempts:
        await service._dispatch({"type": "from_device", "device_id": route, "msg": msg})
    assert recorder.calls == []
    assert service.stats["undecryptable"] == len(attempts)
    assert service._ws.frames == []  # hiçbirine yanıt verilmedi
    await service._dispatch({"type": "from_device", "device_id": device.device_id, "msg": sealed})
    assert [c[0] for c in recorder.calls] == ["engage_kill_switch"]


async def test_pairing_requires_encryption_key(db: Database) -> None:
    service, _ = await make_service(db)
    qr = json.loads(service.pairing.start("wss://relay.example")[0])
    device = DeviceSim()
    request = device.pair_request(qr)
    payload = json.loads(request["p"])
    for broken in (None, "", base64.b64encode(b"\x04" + b"0" * 64).decode()):
        body = {k: v for k, v in payload.items() if k != "kx_key"}
        if broken is not None:
            body["kx_key"] = broken
        text = json.dumps(body)
        from ati_engine.remote.crypto import hmac_proof, unb64url
        from remote_device import raw_signature

        forged = {
            "p": text,
            "s": base64.b64encode(raw_signature(device.signing, text.encode())).decode(),
            "proof": base64.b64encode(hmac_proof(unb64url(qr["pair"]), text.encode())).decode(),
        }
        reply = await service.handle(forged, device.device_id)
        assert reply is not None and reply["reason"] == "bad_signature", broken
    assert await service.registry.all() == []


async def test_devices_without_encryption_key_get_no_messages(db: Database) -> None:
    service, _ = await make_service(db)
    relay = FakeRelay()
    service._ws = relay
    await db.execute(
        "INSERT INTO remote_devices (id, name, signing_key, guarded_key, protection, paired_at) "
        "VALUES ('eski', 'Eski iPhone', 'AA==', 'AA==', 'software', 1)"
    )
    await service.push_snapshot("eski")
    assert relay.frames == []


def test_envelope_vectors_open_and_reproduce() -> None:
    """Diller arası şifreli zarf vektörleri: çözülür ve aynı geçici anahtar/nonce ile birebir
    yeniden üretilir; dosya üreticiyle günceldir (iOS aynı dosyayı kullanır)."""
    import importlib.util

    from ati_engine.remote.crypto import SealError, open_json, open_sealed, seal, unb64

    root = Path(__file__).resolve().parents[2]
    path = root / "shared" / "protocol" / "test-vectors" / "remote-v1.json"
    vectors = json.loads(path.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "gen_remote_vectors", root / "engine" / "scripts" / "gen_remote_vectors.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    assert generator.render() == path.read_text(encoding="utf-8"), "vektörler güncel değil"

    env = vectors["envelope"]
    keys = {
        "e2d": KeyAgreement.from_private_raw(bytes.fromhex(env["device_kx_private_hex"])),
        "d2e": KeyAgreement.from_private_raw(bytes.fromhex(env["engine_kx_private_hex"])),
    }
    assert base64.b64decode(env["device_kx_public_x963"]) == keys["e2d"].public_x963
    for direction, recipient in keys.items():
        case = env[direction]
        info = case["info"].encode()
        assert open_sealed(recipient, case["envelope"], info).decode() == case["plaintext"]
        again = seal(
            recipient.public_x963,
            case["plaintext"].encode(),
            info,
            ephemeral=KeyAgreement.from_private_raw(bytes.fromhex(case["ephemeral_private_hex"])),
            nonce=unb64(case["nonce"]),
        )
        assert again == case["envelope"]
        message = open_json(recipient, case["envelope"], info)
        assert set(message) == {"p", "s"}
        other = "d2e" if direction == "e2d" else "e2d"
        with pytest.raises(SealError):
            open_sealed(recipient, case["envelope"], env[other]["info"].encode())
        with pytest.raises(SealError):
            open_sealed(keys[other], case["envelope"], info)
