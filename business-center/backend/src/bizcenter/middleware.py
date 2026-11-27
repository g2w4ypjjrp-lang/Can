import json
import logging
import time
import uuid
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("bizcenter.http")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record), "level": record.levelname,
                "logger": record.name, "msg": record.getMessage()}
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup_logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """İstek kimliği, yapılandırılmış erişim logu ve güvenlik başlıkları."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        if len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["cache-control"] = "no-store"
        response.headers["content-security-policy"] = "default-src 'none'; frame-ancestors 'none'"
        log.info("request", extra={"extra_fields": {
            "request_id": rid, "method": request.method, "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1),
            "user_id": getattr(request.state, "user_id", None)}})
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """İstemci IP'si başına kayan pencere sınırı (tek süreç). Çok süreçte Redis'e taşınacak."""

    def __init__(self, app, per_minute: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limit = per_minute
        self.hits: dict[str, deque[float]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/health"):
            return await call_next(request)
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = self.hits.setdefault(key, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limit:
            return JSONResponse({"detail": "Çok fazla istek"}, status_code=429,
                                headers={"retry-after": "60"})
        q.append(now)
        if len(self.hits) > 10_000:
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] <= 60}
        return await call_next(request)
