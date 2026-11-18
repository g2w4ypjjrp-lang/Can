"""Yürütme servisi: işlem motorlarını (piyasa başına) kurar, mutabakatı çalıştırır ve yerel
API'ye işlem açma/kapama sunar. Her ortam (Demo Trading = ``testnet``, gerçek hesap = ``live``)
için ayrı bir servis örneği vardır: ayrı anahtarlar, ayrı hesap izleyicisi ve risk bekçisi.

Güvenlik kuralları (kod düzeyinde):

* Demo servisi gerçek Binance adresine, gerçek hesap servisi Binance dışı / Demo adresine
  bağlanamaz (yürütücüde denetlenir).
* İşlem açmak için işlem modu servisin ortamıyla aynı olmalı (Demo → TESTNET, gerçek → LIVE),
  motor RUNNING durumunda olmalı ve niyette zarar durdur bulunmalı; risk kapısı her açılışı
  denetler.
* Anahtar, saklanmadan önce salt-okunur imzalı bir istekle doğrulanır. Gerçek hesap anahtarında
  ayrıca yetkiler okunur: **para çekme veya transfer yetkisi açıksa REDDEDİLİR**. Doğrulanamayan
  anahtar saklanmaz; anahtarın kendisi denetim kaydına ve yanıtlara yazılmaz.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from ati_engine.config import EngineSettings
from ati_engine.core.bus import EventBus
from ati_engine.core.models import EngineState, Market, SymbolInfo, TradingMode
from ati_engine.exchange.rate_limit import Priority, WeightBudget
from ati_engine.exchange.rest import BinanceRestClient
from ati_engine.exchange.signing import RequestSigner
from ati_engine.execution.binance_venue import BinanceFuturesVenue, BinanceSpotVenue
from ati_engine.execution.engine import ManagedPosition, TradeIntent, TradingEngine
from ati_engine.execution.orders import OrderRecord
from ati_engine.execution.paper_live import LivePaperVenue, LiveSymbols, PriceSource
from ati_engine.execution.reconcile import Reconciler, ReconcileReport
from ati_engine.execution.venue import ExecutionBlocked
from ati_engine.market.discovery import parse_exchange_info
from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
from ati_engine.risk.account import AccountMonitor
from ati_engine.risk.gate import RiskGate
from ati_engine.risk.guard import RiskGuard
from ati_engine.safety.coordinator import SafetyCoordinator
from ati_engine.security.exchange_keys import (
    LIVE_KEY_HELP,
    ExchangeKeyStore,
    KeyCheck,
    StoredKey,
    check_live_key_policy,
    verify_key,
)
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from ati_engine.storage.settings_store import SettingsStore

logger = logging.getLogger(__name__)

# Sanal hesabın kalıcı kaydı (piyasa başına) ve kayıt aralığı.
PAPER_STATE_KEY = "paper.venue.{market}"
PAPER_SAVE_INTERVAL_S = 5.0


class ExecutionUnavailable(RuntimeError):
    """İstenen piyasa için yürütücü bağlı değil."""


Environment = Literal["testnet", "live", "paper"]
ENV_LABELS = {"testnet": "Demo Trading", "live": "gerçek hesap", "paper": "sanal hesap"}


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
    rest: BinanceRestClient | None  # sanal hesapta yok
    reconciler: Reconciler
    symbols: Mapping[str, SymbolInfo]
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
        environment: Environment = "testnet",
        paper_symbols: Callable[[Market], Mapping[str, SymbolInfo]] | None = None,
        paper_price: PriceSource | None = None,
        paper_balance: Decimal = Decimal(10_000),
    ) -> None:
        self.environment: Environment = environment
        self.mode = {
            "live": TradingMode.LIVE,
            "paper": TradingMode.PAPER,
        }.get(environment, TradingMode.TESTNET)
        # Sanal hesap: anahtar gerekmez; sembol kuralları ve fiyatlar piyasa verisinden.
        self.paper = environment == "paper"
        # Anahtar kasasındaki ortam adı (sanal hesapta anahtar işlemi yapılmaz).
        self._key_env: Literal["testnet", "live"] = "live" if environment == "live" else "testnet"
        self._paper_symbols = paper_symbols
        self._paper_price = paper_price
        self.paper_balance = paper_balance
        self._paper_task: asyncio.Task[None] | None = None
        self.label = ENV_LABELS[environment]
        self.settings = settings
        self.cfg = settings.execution
        self.db = db
        self.bus = bus
        self.audit = audit
        self.keys = keys
        self.trading_mode = trading_mode
        self.engine_state = engine_state
        b = settings.binance
        live = environment == "live"
        self.endpoints = endpoints or {
            Market.SPOT: TestnetEndpoints(
                b.spot_live_rest if live else b.spot_testnet_rest,
                b.spot_live_ws_api if live else b.spot_testnet_ws_api,
                "/api/v3/time",
                "/api/v3/exchangeInfo",
            ),
            Market.USDM_FUTURES: TestnetEndpoints(
                b.futures_live_rest if live else b.futures_testnet_rest,
                b.futures_live_ws_private if live else b.futures_testnet_ws_private,
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
            db, mode=self.mode, engines=engines, quote_asset=settings.quote_asset
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
                prefix="live." if live else ("paper." if environment == "paper" else ""),
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
        """Anahtarı doğrular; doğrulanırsa şifreli kasaya yazar. Gerçek hesap anahtarında önce
        yetkiler okunur: para çekme/transfer açıksa ya da işlem yetkisi yoksa saklanmaz."""
        from ati_engine.exchange.signing import HmacSigner

        if self.paper:
            raise ExecutionUnavailable("Sanal hesap anahtar gerektirmez")
        api_key, secret = api_key.strip(), secret.strip()
        warnings: list[str] = []
        blocked: list[str] = []
        if self.environment == "live":
            # Yetkiler spot adresinden okunur (futures anahtarı için de aynı uç nokta).
            spot = self._rest(Market.SPOT, api_key, HmacSigner(secret))
            try:
                with contextlib.suppress(Exception):
                    await spot.sync_time(self.endpoints[Market.SPOT].time_path)
                verdict = await check_live_key_policy(spot, markets=[market])
                blocked = [f.message for f in verdict.blocking]
                warnings = [f.message for f in verdict.warnings]
            except Exception as exc:
                code = getattr(exc, "code", None)
                blocked = [
                    f"Anahtarın yetkileri okunamadı ({code or type(exc).__name__}). {LIVE_KEY_HELP}"
                ]
            finally:
                await spot.close()
        if blocked:
            check = KeyCheck(False, " ".join(blocked))
        else:
            rest = self._rest(market, api_key, HmacSigner(secret))
            try:
                with contextlib.suppress(Exception):
                    await rest.sync_time(self.endpoints[market].time_path)
                check = await verify_key(
                    rest, market, help_text=LIVE_KEY_HELP if self.environment == "live" else None
                )
            finally:
                await rest.close()
            if check.ok and warnings:
                check = KeyCheck(True, f"{check.message}. Uyarı: {' '.join(warnings)}",
                                 check.can_trade)  # fmt: skip
        stored = None
        if check.ok:
            stored = await self.keys.store(self._key_env, market, api_key, secret)
        await self.audit.record(
            actor=actor,
            action=f"execution.{self.environment}_key",
            details={
                "market": market.value,
                "verified": check.ok,
                "stored": stored is not None,
                "hint": stored.api_key_hint if stored else None,
                "rejected_for": blocked[:3] if blocked else None,
            },
        )
        return check, stored

    async def delete_key(self, market: Market, *, actor: str) -> bool:
        await self.disconnect(market)
        removed = await self.keys.delete(self._key_env, market)
        await self.audit.record(
            actor=actor,
            action=f"execution.{self.environment}_key_deleted",
            details={"market": market.value},
        )
        return removed

    # --- Bağlantı ---------------------------------------------------------------------------

    async def _connect_paper(self, market: Market) -> MarketExecution:
        """Sanal hesap: borsaya emir gitmez; fiyatlar ve sembol kuralları piyasa verisinden."""
        source = self._paper_symbols
        price = self._paper_price
        if source is None or price is None:
            raise ExecutionUnavailable("Sanal hesap için piyasa verisi bağlı değil")
        symbols = LiveSymbols(lambda: source(market))
        venue = LivePaperVenue(
            market,
            price_source=price,
            # Toplam sanal bakiye piyasalara eşit bölünür (özsermaye toplamı ayar kadar kalır).
            initial_quote=self.paper_balance / max(1, len(self.cfg.markets)),
            quote_asset=self.settings.quote_asset,
        )
        stored = await SettingsStore(self.db).get(PAPER_STATE_KEY.format(market=market.value))
        if isinstance(stored, dict) and stored.get("version") == 1:
            try:
                venue.restore(stored)
            except Exception:  # bozuk kayıt: sanal hesap baştan başlar
                logger.warning("Sanal hesap kaydı okunamadı", extra={"market": market.value})
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
        if self.bus is not None:
            engine.on_trade = self.bus.publish
        await engine.start()
        execution = MarketExecution(market, engine, None, reconciler, symbols)
        await reconciler.run("startup")
        execution.task = asyncio.create_task(
            reconciler.run_forever(self.cfg.reconcile_interval_s, execution.stop),
            name=f"reconcile-paper-{market.value}",
        )
        self.markets[market] = execution
        if self.guard is not None:
            self.start_guard()
            self.guard.attach(market)
        if self._paper_task is None:
            self._paper_task = asyncio.create_task(self._paper_saver(), name="paper-save")
        await self.audit.record(
            actor="system",
            action="execution.connected",
            details={"market": market.value, "mode": "paper", "balance": str(self.paper_balance)},
        )
        return execution

    async def save_paper(self) -> None:
        """Değişen sanal hesapları kaydeder (bakiye, pozisyonlar, bekleyen emirler)."""
        store = SettingsStore(self.db)
        for market, execution in list(self.markets.items()):
            venue = execution.engine.venue
            if isinstance(venue, LivePaperVenue) and venue.dirty:
                venue.dirty = False
                await store.set(PAPER_STATE_KEY.format(market=market.value), venue.snapshot())

    async def _paper_saver(self) -> None:
        while True:
            await asyncio.sleep(PAPER_SAVE_INTERVAL_S)
            try:
                await self.save_paper()
            except Exception:  # kayıt hatası işlemleri durdurmaz; sonraki turda denenir
                logger.warning("Sanal hesap kaydedilemedi", exc_info=True)

    async def reset_paper(self, *, actor: str) -> dict[str, str]:
        """Sanal hesabı başlangıç bakiyesine döndürür (açık sanal pozisyon yokken)."""
        if not self.paper:
            raise ExecutionUnavailable("Yalnızca sanal hesap sıfırlanabilir")
        for execution in self.markets.values():
            if execution.engine.positions.positions:
                raise ExecutionBlocked("Açık sanal pozisyon varken sıfırlanamaz; önce kapatın")
        share = self.paper_balance / max(1, len(self.cfg.markets))
        balances: dict[str, str] = {}
        for market, execution in self.markets.items():
            venue = execution.engine.venue
            if isinstance(venue, LivePaperVenue):
                venue.reset(share)
                balances[market.value] = str(share)
        await self.save_paper()
        await self.audit.record(actor=actor, action="execution.paper_reset", details=balances)
        return balances

    async def feed_prices(self, prices: Mapping[str, float]) -> None:
        """Sanal hesap: canlı fiyatlar (anahtar ``"<piyasa>:<SEMBOL>"``) yürütücülere iletilir."""
        if not self.paper:
            return
        grouped: dict[str, dict[str, float]] = {}
        for key, value in prices.items():
            market, _, symbol = key.partition(":")
            grouped.setdefault(market, {})[symbol] = value
        for market, execution in list(self.markets.items()):
            venue = execution.engine.venue
            batch = grouped.get(market.value)
            if batch and isinstance(venue, LivePaperVenue):
                await venue.feed(batch)

    async def connect(self, market: Market) -> MarketExecution:
        async with self._lock:
            if market in self.markets:
                return self.markets[market]
            if self.paper:
                return await self._connect_paper(market)
            loaded = await self.keys.load(self._key_env, market)
            if loaded is None:
                raise ExecutionUnavailable(
                    f"{market.value} için {self.label} anahtarı kayıtlı değil"
                )
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
                    mode=self.mode,
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
            if self.bus is not None:
                engine.on_trade = self.bus.publish
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
                self.start_guard()  # ilk bağlantıda (gerçek hesap bekçisi ancak o zaman başlar)
                self.guard.attach(market)
            await self.audit.record(
                actor="system",
                action="execution.connected",
                details={
                    "market": market.value,
                    "mode": self.environment,
                    "symbols": len(symbols),
                },
            )
            return execution

    async def connect_configured(self) -> None:
        """Anahtarı kayıtlı piyasalara bağlanır (açılışta). Hata motoru durdurmaz."""
        for market in self.cfg.markets:
            if not self.paper and await self.keys.info(self._key_env, market) is None:
                continue
            try:
                await self.connect(market)
            except ExecutionUnavailable as exc:
                logger.warning(
                    "Yürütücü bağlanamadı",
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
        if execution.rest is not None:
            await execution.rest.close()
        if self.guard is not None:
            await self.guard.detach(market)

    async def close(self) -> None:
        if self._paper_task is not None:
            self._paper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._paper_task
            self._paper_task = None
            with contextlib.suppress(Exception):
                await self.save_paper()  # kapanırken son durum
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
            raise ExecutionUnavailable(f"{market.value} {self.label} yürütücüsü bağlı değil")
        return execution

    # --- İşlemler -------------------------------------------------------------------------------

    def _validate(self, intent: TradeIntent) -> None:
        # Diğer tüm kurallar (zorunlu stop, işlem başına risk, günlük zarar, kaldıraç, tasfiye
        # uzaklığı...) risk kapısındadır ve motor her açılışta onu çağırır.
        if self.trading_mode() is not self.mode:
            raise ExecutionBlocked(
                f"İşlem modu {self.label} değil: önce Ayarlar'dan işlem modunu seçin"
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
                "mode": self.environment,
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
        """Acil durumda bu ortamdaki tüm pozisyonları kapatır."""
        closed = 0
        for execution in list(self.markets.values()):
            closed += await execution.engine.close_all(reason=reason, emergency=True)
        await self.audit.record(
            actor=actor, action="execution.close_all", details={"reason": reason, "closed": closed}
        )
        return closed

    async def reconcile(self, market: Market) -> ReconcileReport:
        return await self._get(market).reconciler.run("manual")

    async def adopt_exchange(self, market: Market, *, actor: str) -> dict[str, Any]:
        """Yerel pozisyon kaydını borsadaki duruma eşitler (kullanıcı onaylı)."""
        execution = self._get(market)
        changed = await execution.reconciler.adopt_exchange()
        await self.audit.record(
            actor=actor,
            action="execution.reconcile_adopt",
            details={"market": market.value, "changed": changed},
        )
        last = execution.reconciler.last
        return {"changed": changed, "report": last.as_dict() if last else None}

    # --- Durum --------------------------------------------------------------------------------

    async def status(self) -> dict[str, Any]:
        markets: dict[str, Any] = {}
        for market in self.cfg.markets:
            stored = None if self.paper else await self.keys.info(self._key_env, market)
            execution = self.markets.get(market)
            entry: dict[str, Any] = {
                "key_stored": self.paper or stored is not None,
                "key_hint": "sanal hesap"
                if self.paper
                else (stored.api_key_hint if stored else None),
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
            "environment": self.environment,
            "trading_mode": self.trading_mode().value,
            "live_locked": not self.settings.live_trading_enabled,
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
                    # Binance cüzdanı (piyasa başına kote varlık): toplam, kullanılabilir,
                    # gerçekleşmemiş kâr/zarar. Ana ekranda "Binance bakiyesi" olarak gösterilir.
                    "wallets": [w.as_dict() for w in snapshot.wallets],
                    "ts_age_s": round(snapshot.age_s(), 1),
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
