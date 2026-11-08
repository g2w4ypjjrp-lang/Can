"""Aşama 15: lisans sistemi — anahtar biçimi, saklama, aktivasyon, kira, cihaz limiti, çakışma,
sahte/tekrar oynatılmış istekler, müşteri cihaz yönetimi. Gerçek PostgreSQL üzerinde."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import psycopg
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import SecretStr

from ati_cloud.app import create_app
from ati_cloud.config import CloudSettings
from ati_cloud.licensing.keys import (
    ALPHABET,
    InvalidLicenseKey,
    KeyCipher,
    KeyHasher,
    check_char,
    generate_key,
    key_hint,
    normalize,
)
from ati_cloud.licensing.lease import LeaseSigner, LeaseTerms, lease_payload
from ati_cloud.licensing.service import Licensing

ORIGIN = "http://localhost:3000"
PASSWORD = "Gizli-Parola-2026!"
SIGNING = secrets.token_bytes(32)
SECRETS = {
    "license_pepper": SecretStr(base64.b64encode(secrets.token_bytes(32)).decode()),
    "license_kek": SecretStr(base64.b64encode(secrets.token_bytes(32)).decode()),
    "lease_signing_key": SecretStr(base64.b64encode(SIGNING).decode()),
}
LEASE_PUBLIC = Ed25519PrivateKey.from_private_bytes(SIGNING).public_key()


# --- Anahtar biçimi ve kriptografi (veritabanı gerekmez) ---------------------------------------


def test_generated_keys_have_format_and_valid_check_char() -> None:
    keys = {generate_key() for _ in range(2000)}
    assert len(keys) == 2000
    for key in list(keys)[:200]:
        assert len(key) == 23 and key.startswith("ATI-")
        body = normalize(key)
        assert all(ch in ALPHABET for ch in body) and body[15] == check_char(body[:15])


def test_typos_are_caught_before_reaching_the_server() -> None:
    key = generate_key()
    body = normalize(key)
    caught = 0
    for i in range(16):
        for ch in ALPHABET:
            if ch == body[i]:
                continue
            typo = body[:i] + ch + body[i + 1 :]
            with pytest.raises(InvalidLicenseKey):
                normalize(typo)
            caught += 1
    assert caught == 16 * 31  # her tek karakter hatası yakalanır
    swaps = sum(
        1
        for i in range(15)
        if body[i] != body[i + 1] and _invalid(body[:i] + body[i + 1] + body[i] + body[i + 2 :])
    )
    differing = sum(1 for i in range(15) if body[i] != body[i + 1])
    assert swaps >= differing - 1  # yan yana yer değiştirmelerin (neredeyse) tamamı


def _invalid(body: str) -> bool:
    try:
        normalize(body)
    except InvalidLicenseKey:
        return True
    return False


def test_normalize_is_forgiving_about_formatting() -> None:
    key = generate_key()
    body = normalize(key)
    assert normalize(key.lower()) == body
    assert normalize(" ".join(body[i : i + 4] for i in range(0, 16, 4))) == body
    # Crockford: O→0, I/L→1 okunurken düzeltilir.
    confusable = body.replace("0", "O").replace("1", "I")
    assert normalize(confusable) == body
    assert key_hint(key) == f"ATI-****-****-****-{body[12:]}"
    for bad in ["", "ATI-1234", "ATI-UUUU-UUUU-UUUU-UUUU", key + "X"]:
        with pytest.raises(InvalidLicenseKey):
            normalize(bad)


def test_hash_depends_on_pepper_and_cipher_is_bound_to_row() -> None:
    key = generate_key()
    a, b = KeyHasher(secrets.token_bytes(32)), KeyHasher(secrets.token_bytes(32))
    assert a.digest(key) == a.digest(key.lower()) and a.digest(key) != b.digest(key)
    cipher = KeyCipher(secrets.token_bytes(32), "test-1")
    digest = a.digest(key)
    blob = cipher.encrypt(key, digest)
    assert key.encode() not in blob and normalize(key).encode() not in blob
    assert cipher.decrypt(blob, digest) == key
    with pytest.raises(InvalidTag):
        cipher.decrypt(blob, a.digest(generate_key()))  # başka satıra taşınmış
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(InvalidTag):
        cipher.decrypt(tampered, digest)
    with pytest.raises(InvalidTag):
        KeyCipher(secrets.token_bytes(32), "test-1").decrypt(blob, digest)  # başka KEK


def test_lease_is_signed_and_clamped_to_license_expiry() -> None:
    signer = LeaseSigner(SIGNING)
    terms = LeaseTerms(
        license_id=str(uuid.uuid4()),
        serial=7,
        plan_code="d30_1dev",
        plan_name="30 Gün - 1 Cihaz",
        status="active",
        license_expires_at_ms=1_000_000 + 3_600_000,
        device_limit=1,
        companion_device_limit=2,
        device_id=str(uuid.uuid4()),
        device_key=b"k" * 32,
        fingerprint=b"f" * 32,
    )
    signed = signer.sign(lease_payload(terms, now_ms=1_000_000, ttl_s=86400, offline_s=259200))
    LEASE_PUBLIC.verify(base64.b64decode(signed["s"]), signed["p"].encode())
    lease = json.loads(signed["p"])
    assert lease["valid_until"] == lease["offline_until"] == 1_000_000 + 3_600_000
    assert lease["kid"] == signer.kid and lease["type"] == "license_lease"


# --- Motor benzetimi ---------------------------------------------------------------------------


class Engine:
    """Motorun lisans istemcisi benzetimi: cihaz anahtarı + parmak izi, imzalı istekler."""

    def __init__(self, http: httpx.AsyncClient, fingerprint: bytes | None = None) -> None:
        self.http = http
        self.key = Ed25519PrivateKey.generate()
        self.fingerprint = fingerprint or secrets.token_bytes(32)
        self.ts = int(time.time() * 1000)
        self.lease: dict[str, Any] | None = None

    def _next_ts(self) -> int:
        self.ts = max(self.ts + 1, int(time.time() * 1000))
        return self.ts

    def sign(self, payload: dict[str, Any], key: Ed25519PrivateKey | None = None) -> dict[str, str]:
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = (key or self.key).sign(text.encode())
        return {"p": text, "s": base64.b64encode(signature).decode()}

    def activation(self, license_key: str, **extra: Any) -> dict[str, str]:
        public = self.key.public_key().public_bytes_raw()
        payload = {
            "v": 1,
            "type": "activate",
            "license_key": license_key,
            "device_key": base64.b64encode(public).decode(),
            "fingerprint": self.fingerprint.hex(),
            "name": "Ofis PC",
            "platform": "windows",
            "app_version": "0.15.0",
            "os_version": "Windows 11",
            "ts_ms": self._next_ts(),
            "nonce": secrets.token_hex(8),
            **extra,
        }
        return self.sign(payload)

    async def activate(self, license_key: str, **extra: Any) -> httpx.Response:
        response = await self.http.post(
            "/v1/licenses/activate", json=self.activation(license_key, **extra)
        )
        if response.status_code == 200:
            self.lease = verify_lease(response.json()["lease"])
        return response

    def device_message(self, kind: str, **extra: Any) -> dict[str, str]:
        assert self.lease
        return self.sign(
            {
                "v": 1,
                "type": kind,
                "license_id": self.lease["license_id"],
                "device_id": self.lease["device_id"],
                "ts_ms": self._next_ts(),
                "nonce": secrets.token_hex(8),
                **extra,
            }
        )

    async def renew(self) -> httpx.Response:
        response = await self.http.post("/v1/licenses/renew", json=self.device_message("renew"))
        if response.status_code == 200:
            self.lease = verify_lease(response.json()["lease"])
        return response


def verify_lease(signed: dict[str, str]) -> dict[str, Any]:
    LEASE_PUBLIC.verify(base64.b64decode(signed["s"]), signed["p"].encode())
    lease: dict[str, Any] = json.loads(signed["p"])
    return lease


def code(response: httpx.Response) -> str:
    return str(response.json()["detail"]["code"])


# --- Kurulum -----------------------------------------------------------------------------------


@pytest.fixture
async def app_client(dsn: str) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    settings = CloudSettings(
        environment="test", database_url=SecretStr(dsn), session_cookie_secure=False, **SECRETS
    )
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": ORIGIN},
    ) as http:
        yield app, http
    await app.state.db.close()


@pytest.fixture
def client(app_client: tuple[Any, httpx.AsyncClient]) -> httpx.AsyncClient:
    return app_client[1]


async def issue(app: Any, dsn: str, customer_id: Any | None, plan: str = "d30_1dev") -> str:
    licensing: Licensing = app.state.licensing
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        conn.row_factory = psycopg.rows.dict_row  # type: ignore[assignment]
        _, key = await licensing.issue(conn, plan_code=plan, customer_id=customer_id)  # type: ignore[arg-type]
    return key


async def customer(client: httpx.AsyncClient, conn: psycopg.Connection, email: str) -> Any:
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": PASSWORD, "accept_terms": True}
    )
    assert response.status_code == 202
    row = conn.execute(
        "SELECT payload->>'link' FROM email_outbox WHERE to_email = %s ORDER BY created_at DESC",
        (email,),
    ).fetchone()
    assert row
    token = parse_qs(urlparse(row[0]).query)["token"][0]
    assert (await client.post("/v1/auth/verify-email", json={"token": token})).status_code == 200
    found = conn.execute("SELECT id FROM customers WHERE email = %s", (email,)).fetchone()
    assert found
    return found[0]


async def login(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200


# --- Aktivasyon ve kira --------------------------------------------------------------------------


async def test_activation_starts_term_and_returns_device_bound_lease(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    stored = conn.execute("SELECT key_hint, status FROM licenses").fetchone()
    assert stored == (key_hint(key), "sold")
    assert conn.execute(
        "SELECT count(*) FROM licenses WHERE key_ciphertext::text LIKE %s", (f"%{key}%",)
    ).fetchone() == (0,)

    engine = Engine(client)
    response = await engine.activate(key)
    assert response.status_code == 200, response.text
    lease = engine.lease
    assert lease is not None
    assert lease["status"] == "active" and lease["plan_code"] == "d30_1dev"
    assert lease["fingerprint"] == engine.fingerprint.hex()
    assert base64.b64decode(lease["device_key"]) == engine.key.public_key().public_bytes_raw()
    assert lease["companion_device_limit"] == 2 and lease["device_limit"] == 1
    now = int(time.time() * 1000)
    assert abs(lease["valid_until"] - (now + 86_400_000)) < 60_000
    assert abs(lease["offline_until"] - (now + 72 * 3_600_000)) < 60_000
    status, days = conn.execute(
        "SELECT status, extract(day FROM expires_at - activated_at)::int FROM licenses"
    ).fetchone() or (None, None)
    assert status == "active" and days == 30
    assert abs(lease["license_expires_at"] - (now + 30 * 86_400_000)) < 60_000
    events = conn.execute(
        "SELECT from_status::text, to_status::text, actor_type::text FROM license_events ORDER BY id"
    ).fetchall()
    assert events[-1] == ("sold", "active", "engine")

    # Aynı bilgisayardan tekrar aktivasyon: yeni cihaz/aktivasyon oluşmaz.
    assert (await engine.activate(key)).status_code == 200
    assert conn.execute("SELECT count(*) FROM license_activations").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM devices").fetchone() == (1,)


async def test_device_limit_and_panel_reset(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    first, second = Engine(client), Engine(client)
    assert (await first.activate(key)).status_code == 200
    blocked = await second.activate(key)
    assert blocked.status_code == 409 and code(blocked) == "device_limit"

    await login(client, "can@example.com")
    (lic,) = (await client.get("/v1/me")).json()["licenses"]
    assert [d["name"] for d in lic["devices"]] == ["Ofis PC"] and lic["device_resets_left"] == 3
    assert first.lease
    removed = await client.post(
        f"/v1/me/licenses/{lic['id']}/devices/{first.lease['device_id']}/deactivate"
    )
    assert removed.status_code == 200 and removed.json()["device_resets_left"] == 2
    gone = await first.renew()
    assert gone.status_code == 403 and code(gone) == "not_activated"
    assert (await second.activate(key)).status_code == 200


async def test_concurrent_activations_cannot_exceed_limit(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner, plan="d30_2dev")
    engines = [Engine(client) for _ in range(6)]
    results = await asyncio.gather(*(e.activate(key) for e in engines))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 200, 409, 409, 409, 409]
    assert conn.execute(
        "SELECT count(*) FROM license_activations WHERE deactivated_at IS NULL"
    ).fetchone() == (2,)


async def test_invalid_unknown_and_unsold_keys(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str
) -> None:
    app, client = app_client
    engine = Engine(client)
    key = generate_key()
    typo = key[:-1] + ("0" if key[-1] != "0" else "1")
    bad = await engine.activate(typo)
    assert bad.status_code == 400 and code(bad) == "invalid_key"
    unknown = await engine.activate(key)
    assert unknown.status_code == 404 and code(unknown) == "not_found"
    pool_key = await issue(app, dsn, None)  # satış havuzunda, kimseye satılmamış
    pool = await engine.activate(pool_key)
    assert pool.status_code == 404 and code(pool) == "not_found"


async def test_forged_stale_and_replayed_requests_are_rejected(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    engine = Engine(client)

    # Başkasının anahtarıyla imzalanmış aktivasyon (cihaz anahtarına sahip değil).
    forged = engine.activation(key)
    forged["s"] = base64.b64encode(Ed25519PrivateKey.generate().sign(forged["p"].encode())).decode()
    response = await client.post("/v1/licenses/activate", json=forged)
    assert response.status_code == 401 and code(response) == "bad_signature"
    stale = await engine.activate(key, ts_ms=int(time.time() * 1000) - 3_600_000)
    assert stale.status_code == 400 and code(stale) == "stale"

    assert (await engine.activate(key)).status_code == 200
    renew = engine.device_message("renew")
    assert (await client.post("/v1/licenses/renew", json=renew)).status_code == 200
    replay = await client.post("/v1/licenses/renew", json=renew)
    assert replay.status_code == 409 and code(replay) == "replay"

    # Sahte imzalı yenileme sıra damgasını ilerletemez: ardından gelen gerçek istek geçer.
    fake = engine.device_message("renew", ts_ms=int(time.time() * 1000) + 200_000)
    fake["s"] = base64.b64encode(Ed25519PrivateKey.generate().sign(fake["p"].encode())).decode()
    forged_renew = await client.post("/v1/licenses/renew", json=fake)
    assert forged_renew.status_code == 401
    assert (await engine.renew()).status_code == 200
    # Yenilemede yeni kira kimliği.
    assert engine.lease and engine.lease["lease_id"]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("UPDATE licenses SET status = 'frozen', frozen_reason = 'inceleme'", "frozen"),
        ("UPDATE licenses SET status = 'cancelled', cancel_reason = 'iade'", "cancelled"),
        ("UPDATE licenses SET expires_at = now() - interval '1 minute'", "expired"),
    ],
)
async def test_renewal_is_refused_after_status_change(
    app_client: tuple[Any, httpx.AsyncClient],
    dsn: str,
    conn: psycopg.Connection,
    sql: str,
    expected: str,
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    engine = Engine(client)
    assert (await engine.activate(key)).status_code == 200
    conn.execute(sql)
    response = await engine.renew()
    assert response.status_code == 403 and code(response) == expected
    if expected == "expired":  # süre dolumu kalıcı olarak işlenir
        assert conn.execute("SELECT status FROM licenses").fetchone() == ("expired",)
    again = await Engine(client).activate(key)
    assert again.status_code == 403 and code(again) == expected


async def test_reinstall_rotates_device_key_and_release_frees_slot(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    old = Engine(client)
    assert (await old.activate(key)).status_code == 200
    # Aynı bilgisayarda yeniden kurulum: yeni cihaz anahtarı, aynı parmak izi.
    fresh = Engine(client, fingerprint=old.fingerprint)
    assert (await fresh.activate(key)).status_code == 200
    assert conn.execute("SELECT count(*) FROM devices").fetchone() == (1,)
    stolen = await old.renew()  # eski anahtar artık geçersiz
    assert stolen.status_code == 401 and code(stolen) == "bad_signature"

    release = await client.post("/v1/licenses/deactivate", json=fresh.device_message("deactivate"))
    assert release.status_code == 200
    assert conn.execute(
        "SELECT deactivated_by::text, deactivation_reason FROM license_activations"
    ).fetchone() == ("engine", "device_request")
    assert (await Engine(client).activate(key)).status_code == 200  # yer açıldı


async def test_lifetime_license_has_no_expiry(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner, plan="lifetime_1dev")
    engine = Engine(client)
    assert (await engine.activate(key)).status_code == 200
    assert engine.lease and engine.lease["license_expires_at"] is None
    assert conn.execute("SELECT expires_at FROM licenses").fetchone() == (None,)


# --- Müşteri paneli ----------------------------------------------------------------------------


async def test_customer_reset_limit_and_ownership(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    await login(client, "can@example.com")
    license_id = (await client.get("/v1/me")).json()["licenses"][0]["id"]
    codes = []
    for _ in range(4):
        engine = Engine(client)
        assert (await engine.activate(key)).status_code == 200
        assert engine.lease
        response = await client.post(
            f"/v1/me/licenses/{license_id}/devices/{engine.lease['device_id']}/deactivate"
        )
        codes.append(response.status_code)
    assert codes == [200, 200, 200, 429]

    foreign = await client.post(
        f"/v1/me/licenses/{license_id}/devices/{uuid.uuid4()}/deactivate",
        headers={"Origin": "https://kotu.example"},
    )
    assert foreign.status_code == 403
    await customer(client, conn, "baska@example.com")
    await login(client, "baska@example.com")
    other = await client.post(f"/v1/me/licenses/{license_id}/reveal", json={"password": PASSWORD})
    assert other.status_code == 404  # başkasının lisansı


async def test_reveal_requires_password_and_is_audited(
    app_client: tuple[Any, httpx.AsyncClient], dsn: str, conn: psycopg.Connection
) -> None:
    app, client = app_client
    owner = await customer(client, conn, "can@example.com")
    key = await issue(app, dsn, owner)
    await login(client, "can@example.com")
    license_id = (await client.get("/v1/me")).json()["licenses"][0]["id"]
    wrong = await client.post(f"/v1/me/licenses/{license_id}/reveal", json={"password": "yanlis"})
    assert wrong.status_code == 401
    shown = await client.post(f"/v1/me/licenses/{license_id}/reveal", json={"password": PASSWORD})
    assert shown.status_code == 200 and shown.json() == {"key": key}
    assert shown.headers["cache-control"] == "no-store"
    assert conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'license.key_revealed'"
    ).fetchone() == (1,)
    codes = [
        (
            await client.post(f"/v1/me/licenses/{license_id}/reveal", json={"password": PASSWORD})
        ).status_code
        for _ in range(5)
    ]
    assert codes[-1] == 429


async def test_unconfigured_service_reports_unavailable(dsn: str) -> None:
    app = create_app(CloudSettings(environment="test", database_url=SecretStr(dsn)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.post("/v1/licenses/activate", json={"p": "{}", "s": "x" * 20})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "unavailable"


async def test_signing_key_endpoint_matches(client: httpx.AsyncClient) -> None:
    body = (await client.get("/v1/licenses/signing-key")).json()
    public = base64.b64decode(body["public_key"])
    assert public == LEASE_PUBLIC.public_bytes_raw()
    assert body["kid"] == hashlib.sha256(public).hexdigest()[:16]
    Ed25519PublicKey.from_public_bytes(public)


def test_shared_vectors_are_up_to_date() -> None:
    """shared/protocol/test-vectors/license-v1.json bu koddan üretilir; motor bunlarla doğrular."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_license_vectors.py"
    result = subprocess.run([sys.executable, str(script), "--check"], check=False)  # noqa: S603
    assert result.returncode == 0, "uv run python scripts/gen_license_vectors.py ile yenileyin"
