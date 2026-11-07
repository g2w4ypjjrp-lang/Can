"""JSON değerli anahtar/değer deposu (``settings`` tablosu)."""

from __future__ import annotations

import json
from typing import Any

from ati_engine.core.clock import Clock, SystemClock
from ati_engine.storage.database import Database


class SettingsStore:
    def __init__(self, db: Database, clock: Clock | None = None) -> None:
        self._db = db
        self._clock = clock or SystemClock()

    async def get(self, key: str, default: Any = None) -> Any:
        row = await self._db.fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return default if row is None else json.loads(row[0])

    async def set(self, key: str, value: Any) -> None:
        await self._db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), self._clock.now_ms()),
        )
