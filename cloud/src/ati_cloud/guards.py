"""İstek koruması (Aşama 18): her isteğe, uygulama gövdeyi ayrıştırmadan önce uygulanır.

1. **Köken (CSRF):** tarayıcıdan gelen durum değiştiren her istek (GET/HEAD/OPTIONS dışı) kendi
   kökenimizden gelmelidir. ``/admin/`` yolları yönetici kökenlerine, diğerleri site kökenlerine
   bağlıdır. Çerez kullanmayan makine uç noktaları (imzalı cihaz istekleri, ödeme bildirimleri)
   muaftır; onların kimliği imzayla doğrulanır. Uç noktalardaki köken denetimi ikinci katmandır.
2. **Gövde boyutu:** en fazla ``max_body`` bayt (uvicorn varsayılanda sınır koymaz).
3. **Gövde biçimi:** JSON gövdesi geçerli UTF-8 olmalı ve iç içe derinliği sınırlıdır.
   (Python'un JSON ayrıştırıcısı derin iç içe dizilerde ``RecursionError`` verir; bozuk UTF-8
   ``UnicodeDecodeError`` verir. Çerçeve ikisini de yakalamaz ve 500 döner.)
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Çerezsiz, imzayla kimliği doğrulanan uç noktalar (köken denetimi yok). Hata raporu çerez
# kullanmaz ve kimseye ait veri değiştirmez (masaüstü motoru gönderir; IP başına sınırlı).
MACHINE_PREFIXES = (
    "/v1/crash-reports",
    "/v1/licenses/activate",
    "/v1/licenses/renew",
    "/v1/licenses/deactivate",
    "/v1/payments/webhooks/",
    "/v1/payments/return/",
)
MAX_BODY = 256 * 1024
MAX_DEPTH = 32


def json_depth_exceeds(body: bytes, limit: int) -> bool:
    """JSON metninde dizgi dışındaki ``[``/``{`` iç içeliği ``limit``'i aşıyor mu?"""
    if body.count(b"[") + body.count(b"{") <= limit:
        return False  # hızlı yol: bu kadar açılış yoksa derinlik de yok
    depth = 0
    in_string = escaped = False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # \
                escaped = True
            elif byte == 0x22:  # "
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x5D, 0x7D):
            depth -= 1
    return False


class RequestGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        web_origins: list[str],
        admin_origins: list[str],
        max_body: int = MAX_BODY,
        max_depth: int = MAX_DEPTH,
    ) -> None:
        self.app = app
        self.web_origins = frozenset(web_origins)
        self.admin_origins = frozenset(admin_origins)
        self.max_body = max_body
        self.max_depth = max_depth

    @staticmethod
    async def _reject(send: Send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if not path.startswith(MACHINE_PREFIXES):
            allowed = self.admin_origins if path.startswith("/admin/") else self.web_origins
            origin = headers.get(b"origin", b"").decode("latin-1")
            if origin not in allowed:
                await self._reject(send, 403, "İstek kaynağı doğrulanamadı")
                return
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_body):
            await self._reject(send, 413, "İstek gövdesi çok büyük")
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body:
                await self._reject(send, 413, "İstek gövdesi çok büyük")
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)

        content_type = headers.get(b"content-type", b"").lower()
        if body and (not content_type or b"json" in content_type):
            try:
                body.decode("utf-8")
            except UnicodeDecodeError:
                await self._reject(send, 400, "İstek gövdesi geçerli UTF-8 değil")
                return
            if json_depth_exceeds(body, self.max_depth):
                await self._reject(send, 400, "İstek gövdesi çok derin iç içe")
                return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
