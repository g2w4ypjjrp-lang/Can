"""Uzaktan kontrol servisi: aktarma servisine giden bağlantı, eşleştirme, komut yürütme ve
telefona imzalı özet/bildirim gönderimi.

Motor bilgisayardadır (NAT arkasında). Bu yüzden aktarma servisine bağlantıyı motor kendisi
açar. Telefondan gelen her mesaj ``protocol.py`` denetimlerinden geçmeden uygulanmaz. Motordan
çıkan her mesaj motor anahtarıyla imzalanır ve yalnızca eşleştirilmiş cihazlara, tek tek
gönderilir (yayın yapılmaz).

Uçtan uca şifreleme (Aşama 18): her mesaj alıcının P-256 anahtarına şifrelenir (``crypto.seal``).
Aktarma servisi yalnızca yönlendirme kimliklerini ve şifreli zarfı görür. Şifresiz veya
çözülemeyen mesaj işlenmez; şifreleme anahtarı olmayan (eski) cihaza mesaj gönderilmez.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from ati_engine.remote.crypto import (
    EngineIdentity,
    KeyAgreement,
    SealError,
    b64,
    channel_info,
    open_json,
    relay_hello_text,
    seal_json,
    unb64,
)
from ati_engine.remote.protocol import (
    CommandVerifier,
    Device,
    DeviceRegistry,
    PairingError,
    PairingManager,
)
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)

Executor = Callable[[dict[str, Any], Device], Awaitable[str]]
SnapshotBuilder = Callable[[], Awaitable[dict[str, Any]]]

REJECTION_MESSAGES = {
    "malformed": "Mesaj biçimi geçersiz",
    "wrong_engine": "Komut başka bir motora ait",
    "unknown_device": "Cihaz eşleştirilmemiş",
    "revoked_device": "Cihazın eşleştirmesi kaldırılmış",
    "bad_signature": "İmza geçersiz",
    "stale": "Komut çok eski veya saat farkı büyük",
    "replay": "Bu komut daha önce işlendi (tekrar oynatma)",
    "not_allowed": "Bu komut uzaktan çalıştırılamaz",
    "biometric_required": "Bu komut Face ID ile onay gerektirir",
    "browser_view_only": "Bu işlem telefon tarayıcısından yapılamaz; masaüstü uygulamasından yapın",
}


# Kullanıcının "Telefondan kontrol" seçimi (ayarlar tablosu).
REMOTE_ENABLED_KEY = "remote.enabled"


class RemoteService:
    def __init__(
        self,
        *,
        db: Database,
        identity: EngineIdentity,
        kx: KeyAgreement,
        relay_url: str | None,
        executors: dict[str, Executor],
        snapshot: SnapshotBuilder,
        snapshot_interval_s: float = 15.0,
        max_skew_s: float = 120.0,
        pairing_ttl_s: float = 300.0,
        clock: Callable[[], int] | None = None,
        companion_limit: Callable[[], int | None] | None = None,
    ) -> None:
        self.db = db
        self.identity = identity
        self.kx = kx
        self.relay_url = relay_url
        self.executors = executors
        self.snapshot_builder = snapshot
        self.snapshot_interval_s = snapshot_interval_s
        self._clock = clock or (lambda: int(time.time() * 1000))
        self.registry = DeviceRegistry(db)
        self.pairing = PairingManager(
            identity,
            self.registry,
            kx,
            ttl_s=pairing_ttl_s,
            max_skew_s=max_skew_s,
            clock=clock,
            companion_limit=companion_limit,
        )
        self.verifier = CommandVerifier(identity, self.registry, max_skew_s=max_skew_s, clock=clock)
        self.connected = False
        self.online: set[str] = set()
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=30)
        self.stats = {
            "accepted": 0, "rejected": 0, "paired": 0, "snapshots": 0, "undecryptable": 0,
        }  # fmt: skip
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        # Kullanıcı "Telefondan kontrol"ü açtıysa aktarma bağlantısı bu görevde çalışır.
        self.enabled = False
        self._task: asyncio.Task[None] | None = None

    # --- Aktarma bağlantısı -----------------------------------------------------------------

    async def run(self) -> None:
        """Aktarma servisine bağlı kalır; koparsa artan beklemeyle yeniden bağlanır."""
        if not self.relay_url:
            return
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Aktarma bağlantısı koptu", extra={"error": repr(exc)})
            finally:
                self.connected = False
                self.online.clear()
                self._ws = None
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, 60.0)

    def start(self) -> None:
        """Aktarma bağlantısını arka planda açar (zaten açıksa bir şey yapmaz)."""
        if not self.relay_url:
            raise ValueError("Aktarma servisi adresi yok")
        self.enabled = True
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self.run(), name="remote-relay")

    async def disable(self) -> None:
        """Telefondan kontrolü kapatır: bağlantı kesilir, bekleyen eşleştirme kodu geçersizleşir.
        Eşleşmiş telefonlar silinmez; yeniden açılınca aynı telefonlar bağlanabilir."""
        self.enabled = False
        self.pairing.session = None
        await self.stop()

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        task, self._task = self._task, None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self.connected = False
        self.online.clear()

    async def _session(self) -> None:
        if self.relay_url is None:
            return
        url = self.relay_url.rstrip("/") + "/v1/relay/engine"
        async with websockets.connect(url, open_timeout=15, ping_interval=20) as ws:
            ts = self._clock()
            hello = {
                "type": "hello",
                "role": "engine",
                "engine_id": self.identity.engine_id,
                "key": b64(self.identity.public_raw),
                "ts_ms": ts,
                "sig": b64(
                    self.identity.sign(relay_hello_text("engine", self.identity.engine_id, str(ts)))
                ),
            }
            await ws.send(json.dumps(hello))
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if reply.get("type") != "welcome":
                raise ConnectionError(f"aktarma servisi reddetti: {reply}")
            self._ws = ws
            self.connected = True
            ticker = asyncio.create_task(self._snapshots())
            try:
                async for raw in ws:
                    try:
                        await self._dispatch(json.loads(raw))
                    except Exception as exc:  # tek mesaj hatası bağlantıyı düşürmez
                        logger.warning("Uzak mesaj işlenemedi", extra={"error": repr(exc)})
            finally:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ticker

    async def _send_to(
        self, device_id: str, payload: dict[str, Any], kx_key: bytes | None = None
    ) -> None:
        """İmzalar, cihazın şifreleme anahtarına şifreler ve gönderir."""
        ws = self._ws
        if ws is None:
            return
        if kx_key is None:
            device = await self.registry.get(device_id)
            kx_key = device.kx_key if device is not None else None
        if kx_key is None:
            logger.warning("Cihazın şifreleme anahtarı yok; yeniden eşleştirme gerekli")
            return
        envelope = seal_json(
            kx_key,
            self.identity.signed(payload),
            channel_info("e2d", self.identity.engine_id, device_id),
        )
        message = {"type": "to_device", "device_id": device_id, "msg": envelope}
        async with self._send_lock:
            await ws.send(json.dumps(message, ensure_ascii=False))

    async def _dispatch(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        device_id = str(message.get("device_id", ""))
        if kind == "device_online":
            self.online.add(device_id)
            device = await self.registry.get(device_id)
            if device is not None and device.revoked_at is None:
                await self.push_snapshot(device_id)
        elif kind == "device_offline":
            self.online.discard(device_id)
        elif kind == "from_device":
            try:
                msg = open_json(
                    self.kx,
                    message.get("msg"),
                    channel_info("d2e", self.identity.engine_id, device_id),
                )
            except SealError:
                # Şifresiz, değiştirilmiş veya başka cihaza/yöne ait mesaj: yanıt verilmez.
                self.stats["undecryptable"] += 1
                await self._log(device_id, None, None, False, "undecryptable", None)
                return
            await self.handle(msg, device_id)

    # --- Gelen mesajlar ------------------------------------------------------------------------

    async def handle(self, msg: dict[str, Any], device_id: str) -> dict[str, Any] | None:
        """Telefondan gelen mesajı işler; yanıt içeriğini (imzalanmadan önce) döner."""
        if "proof" in msg:
            return await self._handle_pairing(msg, device_id)
        check = await self.verifier.check(msg, device_id)
        result: dict[str, Any] = {
            "v": 1,
            "type": "result",
            "engine_id": self.identity.engine_id,
            "device_id": device_id,
            "seq": check.seq,
            "command": check.command,
            "ts_ms": self._clock(),
        }
        if not check.accepted:
            self.stats["rejected"] += 1
            result.update(ok=False, reason=check.reason, message=REJECTION_MESSAGES[check.reason])
            await self._log(device_id, check.seq, check.command, False, check.reason, None)
            # Kayıtlı olmayan/iptal edilmiş cihaza yanıt verilmez (bilgi sızdırmaz).
            if check.device is not None and check.device.revoked_at is None:
                await self._send_to(device_id, result)
            return result
        if check.device is None or check.command is None:  # pragma: no cover - kabulde dolu
            return result
        self.stats["accepted"] += 1
        try:
            outcome = await self.executors[check.command](check.args or {}, check.device)
            result.update(ok=True, reason="ok", message=outcome)
        except Exception as exc:
            result.update(ok=False, reason="failed", message=str(exc)[:300])
        await self._log(
            device_id, check.seq, check.command, True, result["reason"], result["message"]
        )
        await self._send_to(device_id, result)
        if check.command != "request_snapshot":
            await self.push_snapshot(device_id)
        return result

    async def _handle_pairing(self, msg: dict[str, Any], device_id: str) -> dict[str, Any]:
        reply: dict[str, Any] = {
            "v": 1,
            "type": "pair_result",
            "engine_id": self.identity.engine_id,
            "device_id": device_id,
            "ts_ms": self._clock(),
        }
        try:
            device = await self.pairing.complete(msg, device_id)
        except PairingError as exc:
            await self._log(device_id, None, "pair", False, exc.reason, None)
            reply.update(ok=False, reason=exc.reason)
            if exc.reason == "device_limit":
                # Kanıt (QR gizli değeri) ve imza doğrulandıktan sonra oluşur: istek gerçekten
                # kullanıcının ekranındaki koddan geliyor; telefona nedeni bildirilir (cihaz
                # kaydedilmediği için şifreleme anahtarı istekten alınır).
                kx_key = unb64(str(json.loads(msg["p"])["kx_key"]))
                await self._send_to(device_id, reply, kx_key)
            return reply  # diğer başarısız eşleştirmelere yanıt gönderilmez
        self.stats["paired"] += 1
        await self._log(device_id, None, "pair", True, "ok", device.name)
        reply.update(ok=True, reason="ok", name=device.name)
        await self._send_to(device_id, reply)
        await self.push_snapshot(device_id)
        return reply

    async def _log(
        self,
        device_id: str,
        seq: int | None,
        command: str | None,
        accepted: bool,
        reason: str,
        result: str | None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO remote_commands (ts, device_id, seq, command, accepted, reason, result)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._clock(),
                device_id[:64],
                seq,
                (command or "")[:40],
                int(accepted),
                reason,
                (result or "")[:300],
            ),
        )

    # --- Giden özet ve bildirimler ---------------------------------------------------------------

    async def _paired_online(self) -> list[str]:
        result = []
        for device_id in list(self.online):
            device = await self.registry.get(device_id)
            if device is not None and device.revoked_at is None:
                result.append(device_id)
        return result

    async def push_snapshot(self, device_id: str) -> None:
        try:
            data = await self.snapshot_builder()
        except Exception as exc:
            logger.warning("Özet oluşturulamadı", extra={"error": repr(exc)})
            return
        payload = {
            "v": 1,
            "type": "snapshot",
            "engine_id": self.identity.engine_id,
            "device_id": device_id,
            "ts_ms": self._clock(),
            "data": data,
            "events": list(self.recent_events),
        }
        self.stats["snapshots"] += 1
        await self._send_to(device_id, payload)

    async def _snapshots(self) -> None:
        while True:
            await asyncio.sleep(self.snapshot_interval_s)
            for device_id in await self._paired_online():
                await self.push_snapshot(device_id)

    async def notify(self, kind: str, title: str, body: str) -> None:
        """Özet bildirim (hassas veri içermez); bağlı eşleştirilmiş cihazlara tek tek gider."""
        event = {"ts_ms": self._clock(), "kind": kind, "title": title[:80], "body": body[:200]}
        self.recent_events.appendleft(event)
        for device_id in await self._paired_online():
            await self._send_to(
                device_id,
                {
                    "v": 1,
                    "type": "event",
                    "engine_id": self.identity.engine_id,
                    "device_id": device_id,
                    **event,
                },
            )

    # --- Masaüstü API'si ------------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        devices = await self.registry.all()
        return {
            "enabled": self.enabled,
            "relay_url": self.relay_url,
            "connected": self.connected,
            "engine_id": self.identity.engine_id,
            "devices": [d.public_dict() | {"online": d.id in self.online} for d in devices],
            "pairing_active": self.pairing.active,
            "stats": dict(self.stats),
        }

    async def commands(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT ts, device_id, seq, command, accepted, reason, result FROM remote_commands "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "ts_ms": r[0],
                "device_id": r[1],
                "seq": r[2],
                "command": r[3],
                "accepted": bool(r[4]),
                "reason": r[5],
                "result": r[6],
            }
            for r in rows
        ]
