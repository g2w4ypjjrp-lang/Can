"""Telefon tarayıcısı bildirim abonelikleri ve gönderim kuyruğu (bkz. ``webpush.py``).

* Cihaz başına bir abonelik; cihazın eşleştirmesi kaldırılınca silinir.
* Bildirimler kuyruğa alınır, motoru bekletmez. Cihaz başına dakikada en çok ``RATE_PER_MINUTE``.
* Bildirim servisi aboneliğin bittiğini söylerse (404/410) abonelik silinir.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import httpx

from ati_engine.remote.webpush import (
    PushError,
    Subscription,
    VapidKey,
    b64url,
    build_request,
    unb64url,
)
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

RATE_PER_MINUTE = 20
QUEUE_SIZE = 100


class PushStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def save(self, device_id: str, sub: Subscription, now: int) -> None:
        await self.db.execute(
            """
            INSERT INTO remote_push (device_id, endpoint, p256dh, auth, created_at, failures)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT (device_id) DO UPDATE SET
                endpoint = excluded.endpoint, p256dh = excluded.p256dh, auth = excluded.auth,
                created_at = excluded.created_at, failures = 0, last_error = NULL
            """,
            (device_id, sub.endpoint, b64url(sub.p256dh), b64url(sub.auth), now),
        )

    async def remove(self, device_id: str) -> bool:
        return (
            await self.db.execute("DELETE FROM remote_push WHERE device_id = ?", (device_id,)) > 0
        )

    async def has(self, device_id: str) -> bool:
        row = await self.db.fetchone("SELECT 1 FROM remote_push WHERE device_id = ?", (device_id,))
        return row is not None

    async def active(self) -> list[tuple[str, Subscription]]:
        """Eşleştirmesi geçerli cihazların abonelikleri."""
        rows = await self.db.fetchall(
            "SELECT p.device_id, p.endpoint, p.p256dh, p.auth FROM remote_push p "
            "JOIN remote_devices d ON d.id = p.device_id WHERE d.revoked_at IS NULL"
        )
        return [(r[0], Subscription(r[1], unb64url(r[2]), unb64url(r[3]))) for r in rows]

    async def subscribed_devices(self) -> set[str]:
        rows = await self.db.fetchall("SELECT device_id FROM remote_push")
        return {r[0] for r in rows}

    async def mark(self, device_id: str, ok: bool, error: str | None, now: int) -> None:
        if ok:
            await self.db.execute(
                "UPDATE remote_push SET last_ok_at = ?, failures = 0, last_error = NULL "
                "WHERE device_id = ?",
                (now, device_id),
            )
        else:
            await self.db.execute(
                "UPDATE remote_push SET failures = failures + 1, last_error = ? "
                "WHERE device_id = ?",
                ((error or "")[:200], device_id),
            )


class PushNotifier:
    def __init__(
        self,
        db: Database,
        vapid: VapidKey,
        *,
        subject: str,
        test_hosts: tuple[str, ...] = (),
        clock: Callable[[], float] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = PushStore(db)
        self.vapid = vapid
        self.subject = subject
        self.test_hosts = test_hosts
        self._clock = clock or time.time
        self._client = client
        self._queue: asyncio.Queue[tuple[dict[str, Any], str | None, str]] = asyncio.Queue(
            QUEUE_SIZE
        )
        self._sent: dict[str, deque[float]] = {}
        self.stats = {"sent": 0, "failed": 0, "dropped": 0, "expired": 0}
        self._task: asyncio.Task[None] | None = None

    @property
    def public_key(self) -> str:
        return self.vapid.public_b64url

    def parse(self, args: dict[str, Any]) -> Subscription:
        return Subscription.parse(
            args, extra_hosts=self.test_hosts, allow_http=bool(self.test_hosts)
        )

    # --- Kuyruk -----------------------------------------------------------------------------

    def enqueue(
        self, message: dict[str, Any], *, device_id: str | None = None, urgency: str = "normal"
    ) -> None:
        """Bildirimi kuyruğa alır (``device_id`` yoksa tüm abone cihazlara). Kuyruk doluysa
        düşürülür; motor beklemez."""
        try:
            self._queue.put_nowait((message, device_id, urgency))
        except asyncio.QueueFull:
            self.stats["dropped"] += 1

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="remote-push")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def run(self) -> None:
        while True:
            message, device_id, urgency = await self._queue.get()
            try:
                for target, sub in await self.store.active():
                    if device_id is not None and target != device_id:
                        continue
                    if not self._allowed(target):
                        self.stats["dropped"] += 1
                        continue
                    await self.deliver(target, sub, message, urgency=urgency)
            except Exception:  # bir bildirim hatası kuyruğu durdurmaz
                logger.warning("Telefon bildirimi gönderilemedi", exc_info=True)

    def _allowed(self, device_id: str) -> bool:
        now = self._clock()
        window = self._sent.setdefault(device_id, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_PER_MINUTE:
            return False
        window.append(now)
        return True

    # --- Gönderim ---------------------------------------------------------------------------

    async def deliver(
        self, device_id: str, sub: Subscription, message: dict[str, Any], *, urgency: str = "normal"
    ) -> tuple[bool, str]:
        """Tek bildirim gönderir: (başarılı mı, açıklama)."""
        now_ms = int(self._clock() * 1000)
        try:
            headers, body = build_request(
                self.vapid, sub, message, subject=self.subject, urgency=urgency
            )
            client = self._client or httpx.AsyncClient(timeout=15)
            try:
                response = await client.post(sub.endpoint, headers=headers, content=body)
            finally:
                if self._client is None:
                    await client.aclose()
        except (PushError, httpx.HTTPError) as exc:
            self.stats["failed"] += 1
            reason = f"Bildirim servisine ulaşılamadı ({type(exc).__name__})"
            await self.store.mark(device_id, False, reason, now_ms)
            return False, reason
        if response.status_code in (200, 201, 202):
            self.stats["sent"] += 1
            await self.store.mark(device_id, True, None, now_ms)
            return True, "gönderildi"
        if response.status_code in (404, 410):
            # Telefon bildirim iznini kaldırmış ya da abonelik süresi dolmuş.
            self.stats["expired"] += 1
            await self.store.remove(device_id)
            return False, "Telefondaki bildirim aboneliği sona ermiş; telefondan yeniden açın"
        self.stats["failed"] += 1
        reason = f"Bildirim servisi {response.status_code} döndü: {response.text[:120]}"
        await self.store.mark(device_id, False, reason, now_ms)
        return False, reason
