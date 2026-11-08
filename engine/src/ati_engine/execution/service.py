"""Yürütme servisi: test ağı işlem motorlarını (piyasa başına) kurar, mutabakatı çalıştırır ve
yerel API'ye işlem açma/kapama sunar.

Güvenlik kuralları (kod düzeyinde):

* Yalnızca **Binance test ağı** (TESTNET). Gerçek hesap anahtarı kasaya yazılamaz, Binance
  yürütücüsü LIVE modda kurulamaz, test ağı modunda gerçek Binance adresine bağlanılamaz.
* İşlem açmak için işlem modu TESTNET olmalı, motor RUNNING durumunda olmalı ve niyette zarar
  durdur (veya iz süren stop) bulunmalı; kaldıraç ayardaki üst sınırı aşamaz.
* Anahtar, saklanmadan önce salt-okunur imzalı bir istekle doğrulanır; doğrulanamazsa
  saklanmaz. Anahtarın kendisi denetim kaydına ve yanıtlara yazılmaz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import EngineState, Market, SymbolInfo, TradingMode
from ati_engine.exchange.rate_limit import Priority, WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.exchange.signing import RequestSigner
from ati_engine.execution.binance_venue import BinanceFuturesVenue, BinanceSpotVenue
from ati_engine.execution.engine import ManagedPosition, TradeIntent, TradingEngine
from ati_engine.execution.orders import OrderRecord
from ati_engine.execution.reconcile import Reconciler, ReconcileReport
from ati_engine.execution.venue import ExecutionBlocked
from ati_engine.market.discovery import parse_exchange_info
from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
from ati_engine.risk.account import AccountMonitor
from ati_engine.risk.gate import RiskGate
from ati_engine.risk.guard import RiskGuard
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.security.exchange_keys import ExchangeKeyStore, KeyCheck, StoredKey, verify_key
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database

logger = logging.getLogger(__name__)


class ExecutionUnavailable(RuntimeError):
    """İstenen piyasa için test ağı yürütücüsü bağlı değil."""


@dataclass(frozen=True)
class TestnetEndpoints:
    rest: str
    ws: str
    time_path: str
    exchange_info_path: str


@dataclass
class MarketExecution:
    market: Market
    engine: TradingEngine
    rest: BinanceRestClient
    reconciler: Reconciler
    symbols: dict[str, SymbolInfo]
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class ExecutionService:
    def __init__(
        self,
        *,
        settings: EngineSettings,
        db: Database,
        audit: AuditLog,
        keys: ExchangeKeyStore,
        trading_mode: Callable[[], TradingMode],
        engine_state: Callable[[], EngineState],
        endpoints: dict[Market, TestnetEndpoints] | None = None,
        safety: SafetyCoordinator | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.settings = settings
        self.cfg = settings.execution
        self.db = db
        self.audit = audit
        self.keys = keys
        self.trading_mode = trading_mode
        self.engine_state = engine_state
        b = settings.binance
        self.endpoints = endpoints or {
            Market.SPOT: TestnetEndpoints(
                b.spot_testnet_rest, b.spot_testnet_ws_api, "/api/v3/time", "/api/v3/exchangeInfo"
            ),
            Market.USDM_FUTURES: TestnetEndpoints(
                b.futures_testnet_rest,
                b.futures_testnet_ws_private,
                "/fapi/v1/time",
                "/fapi/v1/exchangeInfo",
            ),
        }
        self.markets: dict[Market, MarketExecution] = {}
        self.last_error: dict[Market, str] = {}
        self._lock = asyncio.Lock()

        # Risk yönetimi (Aşama 11): kapı her açılışı denetler; bekçi sürekli izler.
        def engines() -> list[TradingEngine]:
            return [m.engine for m in self.markets.values()]

        self.monitor = AccountMonitor(
            db, mode=TradingMode.TESTNET, engines=engines, quote_asset=settings.quote_asset
        )
        self.gate = RiskGate(
            limits=settings.risk,
            db=db,
            monitor=self.monitor,
            engines=engines,
            trading_mode=trading_mode,
            engine_state=engine_state,
            fees={
                Market.SPOT: Decimal(str(settings.scoring.spot_taker_fee)),
                Market.USDM_FUTURES: Decimal(str(settings.scoring.futures_taker_fee)),
            },
        )
        self.guard: RiskGuard | None = None
        if safety is not None:
            self.guard = RiskGuard(
                limits=settings.risk,
                monitor=self.monitor,
                safety=safety,
                db=db,
                targets=lambda: list(self.markets.values()),
                bus=bus,
                close_all=lambda reason: self.close_all(reason=reason, actor="risk_guard"),
            )
        self._guard_stop = asyncio.Event()
        self._guard_task: asyncio.Task[None] | None = None

    def start_guard(self) -> None:
        if self.guard is None or self._guard_task is not None:
            return
        self.guard.start()
        self._guard_task = asyncio.create_task(self.guard.run(self._guard_stop), name="risk-guard")

    # --- Anahtarlar ---------------------------------------------------------------------------

    def _rest(self, market: Market, api_key: str, signer: RequestSigner) -> BinanceRestClient:
        return BinanceRestClient(
            self.endpoints[market].rest,
            budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market]),
            api_key=api_key,
            signer=signer,
            recv_window_ms=self.cfg.recv_window_ms,
        )

    async def store_key(
        self, market: Market, api_key: str, secret: str, *, actor: str
    ) -> tuple[KeyCheck, StoredKey | None]:
        """Test ağı anahtarını doğrular; doğrulanırsa şifreli kasaya yazar."""
        from ati_engine.exchange.signing import HmacSigner

        rest = self._rest(market, api_key.strip(), HmacSigner(secret.strip()))
        try:
            with contextlib.suppress(Exception):
                await rest.sync_time(self.endpoints[market].time_path)
            check = await verify_key(rest, market)
        finally:
            await rest.close()
        stored = None
        if check.ok:
            stored = await self.keys.store("testnet", market, api_key, secret)
        await self.audit.record(
            actor=actor,
            action="execution.testnet_key",
            details={
                "market": market.value,
                "verified": check.ok,
                "stored": stored is not None,
                "hint": stored.api_key_hint if stored else None,
            },
        )
        return check, stored

    async def delete_key(self, market: Market, *, actor: str) -> bool:
        await self.disconnect(market)
        removed = await self.keys.delete("testnet", market)
        await self.audit.record(
            actor=actor, action="execution.testnet_key_deleted", details={"market": market.value}
        )
        return removed

    # --- Bağlantı ---------------------------------------------------------------------------

    async def connect(self, market: Market) -> MarketExecution:
        async with self._lock:
            if market in self.markets:
                return self.markets[market]
            loaded = await self.keys.load("testnet", market)
            if loaded is None:
                raise ExecutionUnavailable(f"{market.value} için test ağı anahtarı kayıtlı değil")
            api_key, signer = loaded
            endpoints = self.endpoints[market]
            rest = self._rest(market, api_key, signer)
            try:
                await rest.sync_time(endpoints.time_path)
                info_payload = await rest.request(
                    "GET", endpoints.exchange_info_path, weight=20, priority=Priority.HIGH
                )
                symbols = {
                    s.symbol: s
                    for s in parse_exchange_info(market, info_payload)
                    if s.quote_asset == self.settings.quote_asset
                }
                venue_cls = BinanceSpotVenue if market is Market.SPOT else BinanceFuturesVenue
                venue = venue_cls(
                    rest,
                    mode=TradingMode.TESTNET,
                    api_key=api_key,
                    signer=signer,
                    ws_url=endpoints.ws,
                    quote_asset=self.settings.quote_asset,
                )
            except Exception as exc:
                await rest.close()
                self.last_error[market] = f"bağlantı kurulamadı: {type(exc).__name__}: {exc}"[:300]
                raise ExecutionUnavailable(self.last_error[market]) from exc
            engine = TradingEngine(
                venue=venue,
                db=self.db,
                symbols=symbols.get,
                risk_gate=self.gate,
                engine_state=self.engine_state,
                fill_timeout_s=self.cfg.fill_timeout_s,
            )
            reconciler = Reconciler(engine, unknown_grace_s=self.cfg.unknown_order_grace_s)
            engine.on_stream_reset = lambda: reconciler.run("stream_reset")
            await engine.start()
            execution = MarketExecution(market, engine, rest, reconciler, symbols)
            await reconciler.run("startup")
            execution.task = asyncio.create_task(
                reconciler.run_forever(self.cfg.reconcile_interval_s, execution.stop),
                name=f"reconcile-{market.value}",
            )
            self.markets[market] = execution
            self.last_error.pop(market, None)
            if self.guard is not None:
                self.guard.attach(market)
            await self.audit.record(
                actor="system",
                action="execution.connected",
                details={"market": market.value, "mode": "testnet", "symbols": len(symbols)},
            )
            return execution

    async def connect_configured(self) -> None:
        """Anahtarı kayıtlı piyasalara bağlanır (açılışta). Hata motoru durdurmaz."""
        for market in self.cfg.markets:
            if await self.keys.info("testnet", market) is None:
                continue
            try:
                await self.connect(market)
            except ExecutionUnavailable as exc:
                logger.warning(
                    "Test ağı yürütücüsü bağlanamadı",
                    extra={"market": market.value, "error": str(exc)},
                )

    async def disconnect(self, market: Market) -> None:
        execution = self.markets.pop(market, None)
        if execution is None:
            return
        execution.stop.set()
        if execution.task is not None:
            execution.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await execution.task
        await execution.engine.stop()
        await execution.rest.close()
        if self.guard is not None:
            await self.guard.detach(market)

    async def close(self) -> None:
        self._guard_stop.set()
        if self._guard_task is not None:
            self._guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._guard_task
        for market in list(self.markets):
            await self.disconnect(market)

    def _get(self, market: Market) -> MarketExecution:
        execution = self.markets.get(market)
        if execution is None:
            raise ExecutionUnavailable(f"{market.value} test ağı yürütücüsü bağlı değil")
        return execution

    # --- İşlemler -------------------------------------------------------------------------------

    def _validate(self, intent: TradeIntent) -> None:
        # Diğer tüm kurallar (zorunlu stop, işlem başına risk, günlük zarar, kaldıraç, tasfiye
        # uzaklığı...) risk kapısındadır ve motor her açılışta onu çağırır.
        if self.trading_mode() is not TradingMode.TESTNET:
            raise ExecutionBlocked(
                "İşlem modu TESTNET değil: test ağı işlemi için önce işlem modunu TESTNET yapın"
            )

    async def open(self, intent: TradeIntent, *, actor: str) -> ManagedPosition:
        self._validate(intent)
        execution = self._get(intent.market)
        await self.audit.record(
            actor=actor,
            action="execution.open",
            details={
                "market": intent.market.value,
                "symbol": intent.symbol,
                "direction": intent.direction,
                "quantity": str(intent.quantity),
                "decision_id": intent.decision_id,
                "mode": "testnet",
            },
        )
        return await execution.engine.open(intent)

    async def close_position(
        self, market: Market, symbol: str, *, actor: str, reason: str = "kullanıcı"
    ) -> OrderRecord | None:
        execution = self._get(market)
        await self.audit.record(
            actor=actor,
            action="execution.close",
            details={"market": market.value, "symbol": symbol, "reason": reason},
        )
        return await execution.engine.close(symbol, reason=reason)

    async def close_all(self, *, reason: str, actor: str) -> int:
        """Acil durumda tüm test ağı pozisyonlarını kapatır."""
        closed = 0
        for execution in list(self.markets.values()):
            closed += await execution.engine.close_all(reason=reason, emergency=True)
        await self.audit.record(
            actor=actor, action="execution.close_all", details={"reason": reason, "closed": closed}
        )
        return closed

    async def reconcile(self, market: Market) -> ReconcileReport:
        return await self._get(market).reconciler.run("manual")

    # --- Durum --------------------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        markets: dict[str, Any] = {}
        for market in self.cfg.markets:
            stored = await self.keys.info("testnet", market)
            execution = self.markets.get(market)
            entry: dict[str, Any] = {
                "key_stored": stored is not None,
                "key_hint": stored.api_key_hint if stored else None,
                "connected": execution is not None,
                "error": self.last_error.get(market),
            }
            if execution is not None:
                venue = execution.engine.venue
                last = execution.reconciler.last
                entry.update(
                    stream_connected=bool(getattr(venue, "stream_connected", False)),
                    stream_errors=int(getattr(venue, "stream_errors", 0)),
                    open_positions=len(execution.engine.positions.positions),
                    open_orders=len(execution.engine.orders.open_records()),
                    order_stats=dict(execution.engine.orders.stats),
                    last_reconcile=last.as_dict() if last else None,
                )
            markets[market.value] = entry
        snapshot = self.monitor.last
        return {
            "environment": "testnet",
            "trading_mode": self.trading_mode().value,
            "live_locked": True,
            "markets": markets,
            "risk": {
                "limits": self.settings.risk.model_dump(mode="json"),
                "gate": dict(self.gate.stats),
                "guard": self.guard.last.as_dict() if self.guard and self.guard.last else None,
                "account": None
                if snapshot is None
                else {
                    "ts_ms": snapshot.ts_ms,
                    "day": snapshot.day,
                    "equity": str(snapshot.equity),
                    "day_start_equity": str(snapshot.day_start_equity),
                    "daily_loss_pct": round(float(snapshot.daily_loss_pct), 4),
                    "halted": snapshot.halted_at is not None,
                    "halt_reason": snapshot.halt_reason,
                    "open_positions": len(snapshot.positions),
                },
            },
        }

    def positions(self) -> list[dict[str, Any]]:
        rows = []
        for market, execution in self.markets.items():
            for symbol, position in execution.engine.positions.positions.items():
                managed = execution.engine.managed.get(symbol)
                rows.append(
                    {
                        "market": market.value,
                        "symbol": symbol,
                        "quantity": position.quantity,
                        "entry_price": position.entry_price,
                        "realized_pnl": position.realized_pnl,
                        "fees": position.fees,
                        "funding": position.funding,
                        "decision_id": position.decision_id,
                        "state": managed.state if managed else "unmanaged",
                        "take_profits_filled": managed.tp_filled if managed else 0,
                        "protected": execution.engine.has_stop(symbol),
                    }
                )
        return rows

    def orders(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        rows = []
        for market, execution in self.markets.items():
            records = (
                execution.engine.orders.open_records()
                if open_only
                else list(execution.engine.orders.records.values())
            )
            for r in records:
                rows.append(
                    {
                        "market": market.value,
                        "client_id": r.client_id,
                        "symbol": r.symbol,
                        "side": r.side.value,
                        "type": r.type.value,
                        "purpose": r.purpose,
                        "status": r.status.value,
                        "quantity": r.quantity,
                        "executed_qty": r.executed_qty,
                        "price": r.price,
                        "trigger_price": r.trigger_price,
                        "avg_price": r.avg_price,
                        "last_error": r.last_error,
                    }
                )
        return rows
