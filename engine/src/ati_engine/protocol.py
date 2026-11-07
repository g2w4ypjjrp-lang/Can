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
from ati_engine.market.events import PUBLIC_MARKET_EVENT_TYPES
from ati_engine.scanner.scanner import MarketSignal
from ati_engine.whales.events import WhaleAlert

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
    schemas.MarketStatusResponse,
    schemas.TickersResponse,
    schemas.FocusRequest,
    schemas.FocusResponse,
    schemas.ScannerTopResponse,
    schemas.SignalInfo,
    schemas.WhaleTradeInfo,
    schemas.WhaleAlertInfo,
    schemas.WhaleSummaryResponse,
    schemas.ImpactInfo,
    schemas.PositioningInfo,
    schemas.HistoryStatusResponse,
    schemas.HistorySyncRequest,
    schemas.HistoryJobInfo,
    schemas.CandlesResponse,
    schemas.LevelsResponse,
    schemas.TrendResponse,
    schemas.SimilarResponse,
)


def build_protocol_schema() -> dict[str, Any]:
    api_defs: dict[str, Any] = {}
    for model in _API_MODELS:
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        for name, definition in schema.pop("$defs", {}).items():
            api_defs[name] = definition
        api_defs[model.__name__] = schema

    event_union: Any = functools.reduce(
        operator.or_,
        (*PUBLIC_EVENT_TYPES, *PUBLIC_MARKET_EVENT_TYPES, MarketSignal, WhaleAlert),
    )
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
            "GET /v1/market/status": {"response": "MarketStatusResponse", "auth": True},
            "GET /v1/market/tickers?market=&limit=&focus_only=": {
                "response": "TickersResponse",
                "auth": True,
            },
            "GET /v1/scanner/top?market=&sort=&limit=&min_quote_volume_24h=": {
                "response": "ScannerTopResponse",
                "auth": True,
            },
            "GET /v1/scanner/signals?limit=": {"response": "SignalInfo[]", "auth": True},
            "GET /v1/whales/trades?market=&symbol=&limit=": {
                "response": "WhaleTradeInfo[]",
                "auth": True,
            },
            "GET /v1/whales/alerts?limit=": {"response": "WhaleAlertInfo[]", "auth": True},
            "GET /v1/whales/summary?market=&window_s=&limit=": {
                "response": "WhaleSummaryResponse",
                "auth": True,
            },
            "GET /v1/whales/impact": {"response": "ImpactInfo[]", "auth": True},
            "GET /v1/whales/positioning": {"response": "PositioningInfo[]", "auth": True},
            "GET /v1/history/status": {"response": "HistoryStatusResponse", "auth": True},
            "POST /v1/history/sync": {
                "request": "HistorySyncRequest",
                "response": "HistoryJobInfo",
                "auth": True,
            },
            "GET /v1/history/candles?market=&symbol=&interval=&bars=": {
                "response": "CandlesResponse",
                "auth": True,
            },
            "GET /v1/history/levels?market=&symbol=&interval=&bars=": {
                "response": "LevelsResponse",
                "auth": True,
            },
            "GET /v1/history/trend?market=&symbol=&interval=&bars=": {
                "response": "TrendResponse",
                "auth": True,
            },
            "GET /v1/history/similar?market=&symbol=&interval=&bars=&window=&top_k=&horizons=": {
                "response": "SimilarResponse",
                "auth": True,
            },
            "POST /v1/market/focus": {
                "request": "FocusRequest",
                "response": "FocusResponse",
                "auth": True,
            },
        },
        "x-websocket": {
            "path": "/v1/events",
            "client_first_message": "WsAuthMessage",
            "server_auth_reply": "WsAuthOk",
            "server_messages": "EngineEvent",
        },
        "$defs": {**defs, "EngineEvent": event_union_schema},
    }
