"""Lisans protokolü test vektörlerini üretir: ``shared/protocol/test-vectors/license-v1.json``.

Bulut (Python, bu proje) üretir; motor testleri doğrular. Anahtar biçimi ve imzalı kira iki
tarafta ayrı kodlanmıştır; vektörler uyumsuzluğu yakalar. Ed25519 imzaları belirlenimcidir,
dosya her çalıştırmada aynı çıkar (``tests/test_licensing.py`` güncel olduğunu denetler).

    uv run python scripts/gen_license_vectors.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ati_cloud.licensing.keys import check_char, format_key, key_hint
from ati_cloud.licensing.lease import LeaseSigner, LeaseTerms, lease_payload

OUT = (
    Path(__file__).resolve().parents[2] / "shared" / "protocol" / "test-vectors" / "license-v1.json"
)
BODIES = ["7XK9PQ82MN45ZR6", "000000000000000", "ZZZZZZZZZZZZZZZ", "ABCDEFGHJKMNPQR"]


def build() -> dict[str, object]:
    valid = []
    for body in BODIES:
        full = body + check_char(body)
        valid.append(
            {"key": format_key(full), "normalized": full, "hint": key_hint(format_key(full))}
        )
    first = BODIES[0] + check_char(BODIES[0])
    wrong_check = first[:15] + ("0" if first[15] != "0" else "1")
    swapped = first[1] + first[0] + first[2:]
    invalid = [
        format_key(wrong_check),
        format_key(swapped),
        "ATI-7XK9-PQ82-MN45",
        "ATI-UUUU-UUUU-UUUU-UUUU",
        "",
    ]

    signer = LeaseSigner(bytes(range(32)))
    device = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    device_key = device.public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(b"ati-device-v1|vector").digest()
    terms = LeaseTerms(
        license_id="7b3f3f0e-3c2a-4f4e-9d3b-2f6f0e1a5c11",
        serial=42,
        plan_code="d30_1dev",
        plan_name="30 Gün - 1 Cihaz",
        status="active",
        license_expires_at_ms=1_802_592_000_000,
        device_limit=1,
        companion_device_limit=2,
        device_id="0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e",
        device_key=device_key,
        fingerprint=fingerprint,
    )
    payload = lease_payload(terms, now_ms=1_800_000_000_000, ttl_s=86400, offline_s=259200)
    payload["lease_id"] = "11111111-2222-4333-8444-555555555555"  # belirlenimci
    return {
        "description": "Lisans protokolü v1 test vektörleri (shared/protocol/license-v1.md)",
        "keys": {"valid": valid, "invalid": invalid},
        "lease": {
            "kid": signer.kid,
            "public_key": base64.b64encode(signer.public_raw).decode(),
            "device_key": base64.b64encode(device_key).decode(),
            "fingerprint": fingerprint.hex(),
            "license_id": terms.license_id,
            "signed": signer.sign(payload),
        },
    }


def main() -> int:
    text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if "--check" in sys.argv:
        return 0 if OUT.read_text(encoding="utf-8") == text else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"Yazıldı: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
