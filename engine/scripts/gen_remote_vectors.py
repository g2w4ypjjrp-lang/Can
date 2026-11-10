"""Uzaktan kontrol protokolü için diller arası test vektörleri üretir.

Çıktı: shared/protocol/test-vectors/remote-v1.json. iOS (Swift) testleri bu dosyayı okur:

* motorun Ed25519 imzalı mesajını doğrular, değiştirilmişini reddeder;
* telefonun P-256 imzalı komutunu doğrular (ham r‖s);
* kimlik türetimini, eşleştirme HMAC kanıtını ve aktarma hello metnini aynı biçimde üretir.

* uçtan uca şifreli zarfı (Aşama 18) çözer ve aynı geçici anahtar/nonce ile birebir üretir.

Anahtarlar sabittir (yalnızca test). Ed25519 ve ECDSA imzaları (RFC 6979) deterministiktir;
dosya her üretimde aynıdır. Motor testi ``--check`` ile dosyanın güncel olduğunu denetler.

    uv run python scripts/gen_remote_vectors.py          # yaz
    uv run python scripts/gen_remote_vectors.py --check  # yalnızca karşılaştır
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from ati_engine.remote.crypto import (
    EngineIdentity,
    KeyAgreement,
    b64,
    b64url,
    channel_info,
    hmac_proof,
    key_id,
    relay_hello_text,
    seal,
)

OUT = (
    Path(__file__).resolve().parents[2] / "shared" / "protocol" / "test-vectors" / "remote-v1.json"
)


def test_scalar(label: str) -> bytes:
    """Testlere özel sabit P-256 gizli anahtarı (32 bayt)."""
    return (int.from_bytes(hashlib.sha256(label.encode()).digest(), "big") % (2**255)).to_bytes(
        32, "big"
    )


def envelope_case(
    recipient: KeyAgreement, info: bytes, plaintext: str, label: str
) -> dict[str, Any]:
    ephemeral = KeyAgreement.from_private_raw(test_scalar(f"ati-test-eph-{label}"))
    nonce = hashlib.sha256(f"ati-test-nonce-{label}".encode()).digest()[:12]
    envelope = seal(
        recipient.public_x963, plaintext.encode("utf-8"), info, ephemeral=ephemeral, nonce=nonce
    )
    return {
        "info": info.decode(),
        "ephemeral_private_hex": ephemeral.private_raw().hex(),
        "nonce": b64(nonce),
        "plaintext": plaintext,
        "envelope": envelope,
    }


def build() -> dict[str, Any]:
    engine = EngineIdentity.from_private_raw(hashlib.sha256(b"ati-test-engine").digest())
    scalar = int.from_bytes(hashlib.sha256(b"ati-test-device").digest(), "big") % (2**255)
    device = ec.derive_private_key(scalar, ec.SECP256R1())
    device_x963 = device.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    device_id = key_id(device_x963)
    snapshot = engine.signed(
        {
            "v": 1,
            "type": "snapshot",
            "engine_id": engine.engine_id,
            "device_id": device_id,
            "ts_ms": 1794100000000,
            "data": {
                "engine": {"state": "running", "trading_mode": "testnet", "kill_switch": False},
                "positions": [{"market": "usdm_futures", "symbol": "BTCUSDT", "quantity": "0.5"}],
            },
            "events": [
                {
                    "ts_ms": 1794099990000,
                    "kind": "whale",
                    "title": "Balina: BTCUSDT",
                    "body": "Büyük alım ğüşıöç",
                }
            ],
        }
    )
    tampered = {**snapshot, "p": snapshot["p"].replace('"kill_switch":false', '"kill_switch":true')}
    command_text = json.dumps(
        {
            "v": 1,
            "type": "command",
            "engine_id": engine.engine_id,
            "device_id": device_id,
            "key": "signing",
            "seq": 1794100000123,
            "ts_ms": 1794100000123,
            "command": "engage_kill_switch",
            "args": {"reason": "telefon"},
        },
        separators=(",", ":"),
    )
    r, s = decode_dss_signature(
        device.sign(command_text.encode(), ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
    )
    command = {"p": command_text, "s": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}
    device_kx = KeyAgreement.from_private_raw(test_scalar("ati-test-device-kx"))
    engine_kx = KeyAgreement.from_private_raw(test_scalar("ati-test-engine-kx"))
    compact = {"separators": (",", ":"), "ensure_ascii": False}
    secret = hashlib.sha256(b"ati-test-pair").digest()
    pair_text = '{"type":"pair_request","name":"Test"}'
    vectors: dict[str, Any] = {
        "comment": (
            "Uzaktan kontrol v1 test vektörleri (yalnızca test anahtarları). "
            "Üretici: engine/scripts/gen_remote_vectors.py"
        ),
        "engine": {
            "key": b64(engine.public_raw),
            "engine_id": engine.engine_id,
            "snapshot": snapshot,
            "tampered_snapshot": tampered,
        },
        "device": {
            "private_scalar_hex": format(scalar, "064x"),
            "public_x963": b64(device_x963),
            "device_id": device_id,
            "command": command,
        },
        "pairing": {
            "secret_b64url": b64url(secret),
            "payload": pair_text,
            "proof": b64(hmac_proof(secret, pair_text.encode())),
        },
        "relay": {
            "device_hello_text": relay_hello_text(
                "device", device_id, engine.engine_id, "1794100000000"
            ).decode(),
            "engine_hello_text": relay_hello_text(
                "engine", engine.engine_id, "1794100000000"
            ).decode(),
        },
        "envelope": {
            "device_kx_private_hex": device_kx.private_raw().hex(),
            "device_kx_public_x963": b64(device_kx.public_x963),
            "engine_kx_private_hex": engine_kx.private_raw().hex(),
            "engine_kx_public_x963": b64(engine_kx.public_x963),
            # Motor → telefon: imzalı özet, telefonun anahtarına.
            "e2d": envelope_case(
                device_kx,
                channel_info("e2d", engine.engine_id, device_id),
                json.dumps(snapshot, **compact),  # type: ignore[arg-type]
                "e2d",
            ),
            # Telefon → motor: imzalı komut, motorun anahtarına.
            "d2e": envelope_case(
                engine_kx,
                channel_info("d2e", engine.engine_id, device_id),
                json.dumps(command, **compact),  # type: ignore[arg-type]
                "d2e",
            ),
        },
    }
    return vectors


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("Test vektörleri güncel değil: scripts/gen_remote_vectors.py çalıştırın")
            return 1
        print("Test vektörleri güncel")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"Yazıldı: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
