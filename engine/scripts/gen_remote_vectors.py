"""Uzaktan kontrol protokolü için diller arası test vektörleri üretir.

Çıktı: shared/protocol/test-vectors/remote-v1.json. iOS (Swift) testleri bu dosyayı okur:

* motorun Ed25519 imzalı mesajını doğrular, değiştirilmişini reddeder;
* telefonun P-256 imzalı komutunu doğrular (ham r‖s);
* kimlik türetimini, eşleştirme HMAC kanıtını ve aktarma hello metnini aynı biçimde üretir.

Anahtarlar sabittir (yalnızca test). Ed25519 imzaları deterministiktir; ECDSA imzası rastgele
olduğundan dosya bir kez üretilip saklanır. Motor testleri dosyanın tutarlılığını denetler.

    uv run python scripts/gen_remote_vectors.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from ati_engine.remote.crypto import (
    EngineIdentity,
    b64,
    b64url,
    hmac_proof,
    key_id,
    relay_hello_text,
)

OUT = (
    Path(__file__).resolve().parents[2] / "shared" / "protocol" / "test-vectors" / "remote-v1.json"
)


def main() -> None:
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
    r, s = decode_dss_signature(device.sign(command_text.encode(), ec.ECDSA(hashes.SHA256())))
    secret = hashlib.sha256(b"ati-test-pair").digest()
    pair_text = '{"type":"pair_request","name":"Test"}'
    vectors = {
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
            "command": {"p": command_text, "s": b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))},
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
    }
    OUT.write_text(json.dumps(vectors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Yazıldı: {OUT}")


if __name__ == "__main__":
    main()
