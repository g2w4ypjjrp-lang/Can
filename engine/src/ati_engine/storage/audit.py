"""Hash zincirli denetim kaydı (audit log).

Her kaydın özeti, bir önceki kaydın özetini de içerir:
``hash = SHA256(prev_hash | ts | actor | action | canonical_json(details))``.
Aradaki bir kayıt silinir veya değiştirilirse ``verify()`` zincirin kırıldığı yeri bulur.
Ayrıca SQLite tetikleyicileri UPDATE/DELETE işlemlerini reddeder.

Bu kayıt; mod değişimleri, acil durdurma, API anahtarı ekleme/silme, strateji terfisi,
risk sınırı değişiklikleri gibi kritik işlemleri tutar.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ati_engine.core.clock import Clock, SystemClock
from ati_engine.security.redaction import redact
from ati_engine.storage.database import Database

GENESIS_HASH = "0" * 64


def _canonical(details: dict[str, Any]) -> str:
    return json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, ts: int, actor: str, action: str, details_json: str) -> str:
    payload = "\x1f".join([prev_hash, str(ts), actor, action, details_json])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditVerification:
    ok: bool
    checked: int
    broken_at_id: int | None = None


class AuditLog:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self._db = db
        self._clock = clock or SystemClock()

    async def record(
        self, *, actor: str, action: str, details: dict[str, Any] | None = None
    ) -> str:
        safe_details = redact(details or {})
        details_json = _canonical(safe_details)
        ts = self._clock.now_ms()

        def _insert(conn: sqlite3.Connection) -> str:
            row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row[0] if row else GENESIS_HASH
            digest = compute_hash(prev_hash, ts, actor, action, details_json)
            conn.execute(
                "INSERT INTO audit_log (ts, actor, action, details, prev_hash, hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, actor, action, details_json, prev_hash, digest),
            )
            return digest

        return await self._db.transaction(_insert)

    async def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT id, ts, actor, action, details FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "details": json.loads(r[4])}
            for r in rows
        ]

    async def verify(self) -> AuditVerification:
        rows = await self._db.fetchall(
            "SELECT id, ts, actor, action, details, prev_hash, hash FROM audit_log ORDER BY id"
        )
        expected_prev = GENESIS_HASH
        for count, (row_id, ts, actor, action, details, prev_hash, digest) in enumerate(rows):
            if prev_hash != expected_prev:
                return AuditVerification(False, count, row_id)
            if compute_hash(prev_hash, ts, actor, action, details) != digest:
                return AuditVerification(False, count, row_id)
            expected_prev = digest
        return AuditVerification(True, len(rows))
