"""Yerel API istek/yanıt şemaları.

Bu modeller ``shared/protocol/engine-local-api.schema.json`` dosyasına dışa aktarılır;
masaüstü (TypeScript) ve iOS (Swift) istemcileri tiplerini bu şemadan üretir.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ati_engine.core.models import EngineState, TradingMode


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class KillSwitchInfo(BaseModel):
    engaged: bool
    reason: str | None = None
    actor: str | None = None
    since_ms: int | None = None


class ReadinessInfo(BaseModel):
    name: str
    ready: bool
    detail: str


class TaskInfo(BaseModel):
    name: str
    state: str
    restarts: int
    last_error: str | None = None


class LoopLagInfo(BaseModel):
    last_ms: float
    p99_ms: float
    max_ms: float


class StatusResponse(BaseModel):
    version: str
    engine_state: EngineState
    state_reason: str
    trading_mode: TradingMode
    can_open_positions: bool
    can_manage_positions: bool
    kill_switch: KillSwitchInfo
    readiness: list[ReadinessInfo]
    tasks: list[TaskInfo]
    loop_lag: LoopLagInfo
    uptime_s: float


class KillSwitchEngageRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class KillSwitchReleaseRequest(BaseModel):
    confirmation: str = Field(max_length=100)


class KillSwitchResponse(BaseModel):
    changed: bool
    kill_switch: KillSwitchInfo
    engine_state: EngineState


class TradingModeRequest(BaseModel):
    mode: TradingMode
    acknowledgement: str | None = Field(default=None, max_length=200)


class CheckInfo(BaseModel):
    name: str
    passed: bool
    message: str


class TradingModeResponse(BaseModel):
    accepted: bool
    mode: TradingMode
    checks: list[CheckInfo]


class AuditEntry(BaseModel):
    id: int
    ts: int
    actor: str
    action: str
    details: dict[str, object]


class ShutdownResponse(BaseModel):
    accepted: bool = True


class ErrorResponse(BaseModel):
    detail: str


class WsAuthMessage(BaseModel):
    type: Literal["auth"]
    token: str


class WsAuthOk(BaseModel):
    type: Literal["auth_ok"] = "auth_ok"
    version: str
