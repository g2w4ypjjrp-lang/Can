"""Eşleştirme ve uzaktan komut doğrulaması (protokol: ``shared/protocol/remote-v1.md``).

Motor bir komutu ancak şu denetimlerin **hepsi** geçerse uygular (sıra önemlidir):

1. biçim → 2. motor kimliği → 3. kayıtlı ve iptal edilmemiş cihaz → 4. imza →
5. zaman farkı → 6. sıra numarası (tekrar oynatma) → 7. izin listesi → 8. biyometrik anahtar

İmza sıra numarasından önce denetlenir: sahte mesaj sıra numarasını ilerletemez. Kabul edilen
sıra numarası kalıcıdır; motor yeniden başlasa da eski komut tekrar oynatılamaz.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ati_engine.remote.crypto import (
    EngineIdentity,
    SignatureError,
    b64url,
    key_id,
    open_signed,
    proof_matches,
    unb64,
    verify_p256,
)
from ati_engine.storage.database import Database

KeyKind = Literal["signing", "guarded"]

# Komut → gereken anahtar. Listede olmayan hiçbir komut uygulanmaz.
ALLOWED_COMMANDS: dict[str, KeyKind] = {
    "engage_kill_switch": "signing",
    "pause_autotrade": "signing",
    "request_snapshot": "signing",
    "resume_autotrade": "guarded",
    "release_kill_switch": "guarded",
    "close_position": "guarded",
    "close_all": "guarded",
}

MAX_NAME = 60


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    signing_key: bytes
    guarded_key: bytes
    protection: str
    paired_at: int
    last_seq: int
    last_seen: int | None
    revoked_at: int | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "protection": self.protection,
            "paired_at": self.paired_at,
            "last_seen": self.last_seen,
            "revoked": self.revoked_at is not None,
        }


class DeviceRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _row(row: tuple[Any, ...]) -> Device:
        return Device(
            id=row[0],
            name=row[1],
            signing_key=unb64(row[2]),
            guarded_key=unb64(row[3]),
            protection=row[4],
            paired_at=row[5],
            last_seq=row[6],
            last_seen=row[7],
            revoked_at=row[8],
        )

    _COLUMNS = (
        "id, name, signing_key, guarded_key, protection, paired_at, last_seq, last_seen, revoked_at"
    )

    async def get(self, device_id: str) -> Device | None:
        row = await self.db.fetchone(
            f"SELECT {self._COLUMNS} FROM remote_devices WHERE id = ?",  # noqa: S608 - sabit sütunlar
            (device_id,),
        )
        return self._row(row) if row else None

    async def all(self) -> list[Device]:
        rows = await self.db.fetchall(
            f"SELECT {self._COLUMNS} FROM remote_devices ORDER BY paired_at DESC"  # noqa: S608
        )
        return [self._row(r) for r in rows]

    async def add(
        self, *, device_id: str, name: str, signing: str, guarded: str, protection: str, now: int
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO remote_devices (id, name, signing_key, guarded_key, protection, paired_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name, guarded_key = excluded.guarded_key,
                protection = excluded.protection, paired_at = excluded.paired_at,
                revoked_at = NULL
            """,
            (device_id, name, signing, guarded, protection, now),
        )

    async def revoke(self, device_id: str, now: int) -> bool:
        changed = await self.db.execute(
            "UPDATE remote_devices SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, device_id),
        )
        return changed > 0

    async def advance_seq(self, device_id: str, seq: int, now: int) -> bool:
        """Sıra numarasını atomik olarak ilerletir; daha küçük/eşitse ``False`` (tekrar)."""
        changed = await self.db.execute(
            "UPDATE remote_devices SET last_seq = ?, last_seen = ? WHERE id = ? AND last_seq < ?",
            (seq, now, device_id, seq),
        )
        return changed > 0

    async def touch(self, device_id: str, now: int) -> None:
        await self.db.execute(
            "UPDATE remote_devices SET last_seen = ? WHERE id = ?", (now, device_id)
        )


# --- Eşleştirme -------------------------------------------------------------------------------


@dataclass
class PairingSession:
    secret: bytes
    expires_ms: int


class PairingError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PairingManager:
    def __init__(
        self,
        identity: EngineIdentity,
        registry: DeviceRegistry,
        *,
        ttl_s: float = 300.0,
        max_skew_s: float = 120.0,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.identity = identity
        self.registry = registry
        self.ttl_s = ttl_s
        self.max_skew_s = max_skew_s
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.session: PairingSession | None = None

    def start(self, relay_url: str) -> tuple[str, int]:
        """Yeni tek kullanımlık eşleştirme oturumu; QR içeriği (JSON metni) ve süre sonu."""
        import base64

        session = PairingSession(secrets.token_bytes(32), self._clock() + int(self.ttl_s * 1000))
        self.session = session
        payload = {
            "v": 1,
            "relay": relay_url,
            "engine_id": self.identity.engine_id,
            "engine_key": base64.b64encode(self.identity.public_raw).decode("ascii"),
            "pair": b64url(session.secret),
            "exp": session.expires_ms,
        }
        return json.dumps(payload, separators=(",", ":")), session.expires_ms

    @property
    def active(self) -> bool:
        return self.session is not None and self.session.expires_ms >= self._clock()

    async def complete(self, message: dict[str, Any], routed_device_id: str) -> Device:
        session = self.session
        if session is None or session.expires_ms < self._clock():
            raise PairingError("no_session")
        try:
            text, signature, p = open_signed(message)
            proof = unb64(str(message.get("proof", "")))
        except SignatureError as exc:
            raise PairingError("malformed") from exc
        if p.get("type") != "pair_request" or p.get("engine_id") != self.identity.engine_id:
            raise PairingError("malformed")
        data = text.encode("utf-8")
        if not proof_matches(session.secret, data, proof):
            raise PairingError("bad_proof")
        try:
            signing = unb64(str(p.get("signing_key", "")))
            guarded = unb64(str(p.get("guarded_key", "")))
            verify_p256(signing, signature, data)
            # Korumalı anahtarın da geçerli bir P-256 noktası olduğunu doğrula.
            from ati_engine.remote.crypto import load_p256

            load_p256(guarded)
        except SignatureError as exc:
            raise PairingError("bad_signature") from exc
        device_id = key_id(signing)
        if p.get("device_id") != device_id or routed_device_id != device_id:
            raise PairingError("device_id_mismatch")
        ts = p.get("ts_ms")
        if not isinstance(ts, int) or abs(self._clock() - ts) > self.max_skew_s * 1000:
            raise PairingError("stale")
        protection = p.get("protection")
        if protection not in ("secure_enclave", "software"):
            raise PairingError("malformed")
        name = str(p.get("name") or "iPhone")[:MAX_NAME]
        self.session = None  # tek kullanımlık
        await self.registry.add(
            device_id=device_id,
            name=name,
            signing=str(p["signing_key"]),
            guarded=str(p["guarded_key"]),
            protection=str(protection),
            now=self._clock(),
        )
        device = await self.registry.get(device_id)
        if device is None:  # pragma: no cover - az önce yazıldı
            raise PairingError("store_failed")
        return device


# --- Komut doğrulama ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandCheck:
    accepted: bool
    reason: str
    device: Device | None = None
    seq: int | None = None
    command: str | None = None
    args: dict[str, Any] | None = None


class CommandVerifier:
    def __init__(
        self,
        identity: EngineIdentity,
        registry: DeviceRegistry,
        *,
        max_skew_s: float = 120.0,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.identity = identity
        self.registry = registry
        self.max_skew_s = max_skew_s
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def check(self, message: Any, routed_device_id: str) -> CommandCheck:
        try:
            text, signature, p = open_signed(message)
        except SignatureError:
            return CommandCheck(False, "malformed")
        seq = p.get("seq")
        command = p.get("command")
        args = p.get("args", {})
        key = p.get("key")
        if (
            p.get("v") != 1
            or p.get("type") != "command"
            or not isinstance(seq, int)
            or isinstance(seq, bool)
            or not isinstance(command, str)
            or not isinstance(args, dict)
            or key not in ("signing", "guarded")
        ):
            return CommandCheck(False, "malformed")
        if p.get("engine_id") != self.identity.engine_id:
            return CommandCheck(False, "wrong_engine", seq=seq, command=command)
        device_id = p.get("device_id")
        if device_id != routed_device_id:
            return CommandCheck(False, "malformed", seq=seq, command=command)
        device = await self.registry.get(str(device_id))
        if device is None:
            return CommandCheck(False, "unknown_device", seq=seq, command=command)
        if device.revoked_at is not None:
            return CommandCheck(False, "revoked_device", device, seq, command)
        public = device.signing_key if key == "signing" else device.guarded_key
        try:
            verify_p256(public, signature, text.encode("utf-8"))
        except SignatureError:
            return CommandCheck(False, "bad_signature", device, seq, command)
        ts = p.get("ts_ms")
        now = self._clock()
        if not isinstance(ts, int) or abs(now - ts) > self.max_skew_s * 1000:
            return CommandCheck(False, "stale", device, seq, command)
        if seq <= device.last_seq:
            return CommandCheck(False, "replay", device, seq, command)
        required = ALLOWED_COMMANDS.get(command)
        if required is None:
            return CommandCheck(False, "not_allowed", device, seq, command)
        if required == "guarded" and key != "guarded":
            return CommandCheck(False, "biometric_required", device, seq, command)
        if not await self.registry.advance_seq(device.id, seq, now):
            return CommandCheck(False, "replay", device, seq, command)  # eşzamanlı tekrar
        return CommandCheck(True, "ok", device, seq, command, args)
