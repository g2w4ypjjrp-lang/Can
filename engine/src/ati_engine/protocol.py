"""Paylaşılan protokol şeması üretimi.

Masaüstü (TypeScript), iOS (Swift) ve bulut aktarma katmanı, motorla konuşurken bu
şemayı kullanır. Şema; yerel API istek/yanıt modellerini ve WebSocket üzerinden akan
olay türlerini içerir. ``tests/test_protocol_schema.py`` depodaki şemanın koddan
üretilenle aynı olduğunu doğrular; böylece istemciler ile motor arasında sessiz
uyumsuzluk oluşmaz.
"""

from __future__ import annotations

import functools
import operator
from typing import Any

import msgspec
from pydantic import BaseModel

from ati_engine.api import schemas
from ati_engine.core.events import PUBLIC_EVENT_TYPES

PROTOCOL_VERSION = 1

_API_MODELS: tuple[type[BaseModel], ...] = (
    schemas.HealthResponse,
    schemas.StatusResponse,
    schemas.KillSwitchEngageRequest,
    schemas.KillSwitchReleaseRequest,
    schemas.KillSwitchResponse,
    schemas.TradingModeRequest,
    schemas.TradingModeResponse,
    schemas.AuditEntry,
    schemas.ShutdownResponse,
    schemas.ErrorResponse,
    schemas.WsAuthMessage,
    schemas.WsAuthOk,
)


def build_protocol_schema() -> dict[str, Any]:
    api_defs: dict[str, Any] = {}
    for model in _API_MODELS:
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        for name, definition in schema.pop("$defs", {}).items():
            api_defs[name] = definition
        api_defs[model.__name__] = schema

    event_union: Any = functools.reduce(operator.or_, PUBLIC_EVENT_TYPES)
    (event_union_schema,), event_components = msgspec.json.schema_components(
        [event_union], ref_template="#/$defs/{name}"
    )
    defs = {**api_defs, **event_components}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ati.local/protocol/engine-local-api.schema.json",
        "title": "AI Trading Intelligence - Engine Local API Protocol",
        "x-protocol-version": PROTOCOL_VERSION,
        "x-rest-endpoints": {
            "GET /v1/health": {"response": "HealthResponse", "auth": False},
            "GET /v1/status": {"response": "StatusResponse", "auth": True},
            "POST /v1/kill-switch/engage": {
                "request": "KillSwitchEngageRequest",
                "response": "KillSwitchResponse",
                "auth": True,
            },
            "POST /v1/kill-switch/release": {
                "request": "KillSwitchReleaseRequest",
                "response": "KillSwitchResponse",
                "auth": True,
            },
            "GET /v1/trading-mode": {"response": "TradingModeResponse", "auth": True},
            "POST /v1/trading-mode": {
                "request": "TradingModeRequest",
                "response": "TradingModeResponse",
                "auth": True,
            },
            "GET /v1/audit": {"response": "AuditEntry[]", "auth": True},
            "POST /v1/engine/shutdown": {"response": "ShutdownResponse", "auth": True},
        },
        "x-websocket": {
            "path": "/v1/events",
            "client_first_message": "WsAuthMessage",
            "server_auth_reply": "WsAuthOk",
            "server_messages": "EngineEvent",
        },
        "$defs": {**defs, "EngineEvent": event_union_schema},
    }
