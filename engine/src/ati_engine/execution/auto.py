"""Otomatik işlem: fırsat sinyallerini işleme dönüştürür.

Varsayılan olarak **kapalıdır**; kullanıcı açar. Seçili işlem moduna göre **Sanal hesapta**
(borsaya emir gitmez, canlı fiyatlar), **Demo Trading**'de ya da kullanıcı gerçek hesap modunu
(onay ifadesiyle) açtıysa **gerçek hesapta** çalışır. Her işlem risk kapısından geçer; bu modül
yalnızca niyet üretir:

1. Sinyal: eşik üstü ``OpportunityScored`` (yön, stop ve hedef seviyesiyle). Mum kapanışından
   bu yana ``max_signal_age_s``'den eski sinyal kullanılmaz.
   Bu süre içinde fiyat stop uzaklığının yarısından fazla kaymışsa (kaçmış ya da ters gitmiş)
   giriş yapılmaz. Bot açıldığında son mumun hâlâ taze sinyalleri hemen değerlendirilir.
2. Fiyat dönüşümü: test ağı fiyatı gerçek piyasadan farklıdır. Sinyalin stop ve hedef
   **uzaklıkları (yüzde)** test ağındaki güncel fiyata uygulanır.
3. Boyutlandırma: zarar durdurda kayıp (komisyon ve kayma payı dahil) özsermayenin
   ``risk_per_trade_pct``'i olacak şekilde; miktar borsa adımına aşağı yuvarlanır.
4. Kademeli kâr alma: hedef 1R'den uzaksa yarısı 1R'de alınır (ardından stop girişe çekilir),
   kalanı hedefte.
5. Sınırlar: saatte en fazla ``max_entries_per_hour`` giriş, sembol başına bekleme süresi.

Karar kimliği sinyalden türetilir (piyasa, sembol, mum zamanı): aynı sinyal iki kez işleme
dönüşmez.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from collections.abc import Callable
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from ati_engine.config import AutoTradeSettings, RiskLimits
from ati_engine.core.events import TradeNotice
from ati_engine.core.models import Market, TradingMode
from ati_engine.execution.approval import RiskRejected
from ati_engine.execution.engine import TakeProfit, TradeIntent
from ati_engine.execution.service import ExecutionService
from ati_engine.execution.venue import ExecutionBlocked
from ati_engine.history.archive import INTERVAL_MS
from ati_engine.risk.gate import DEFAULT_FEES, size_for_risk, trade_risk
from ati_engine.scoring.live import OpportunityScored

logger = logging.getLogger(__name__)

# Karar kimliği hesaba göre ayrılır (aynı sinyal farklı hesaplarda çakışmasın).
MODE_PREFIX = {TradingMode.LIVE: "canli-", TradingMode.PAPER: "sanal-"}

# Sinyal fiyatından bu kadar R (stop uzaklığı) kaymış fiyatla giriş yapılmaz.
MAX_DRIFT_R = Decimal("0.5")

# Kullanıcının uygulamadan değiştirebildiği bot ayarları (kalıcı; motor açılışında uygulanır).
SETTINGS_KEY = "autotrade.settings"
# Karar aralığı (fırsat puanının mum aralığı): kalıcı, motor yeniden başlayınca uygulanır.
DECISION_INTERVAL_KEY = "scoring.interval"
DECISION_INTERVALS = ("1m", "5m", "15m", "1h")
# Bot açık/kapalı (kalıcı). Gerçek para modu açılışta hiçbir zaman geri yüklenmediği için bot,
# yeniden başlatmadan sonra gerçek hesapta ancak kullanıcı gerçek parayı yeniden onaylayınca girer.
ENABLED_KEY = "autotrade.enabled"
EDITABLE = (
    "markets",
    "min_score",
    "risk_per_trade_pct",
    "leverage",
    "max_entries_per_hour",
    "symbol_cooldown_s",
    "trailing_runner",
    "max_consecutive_losses",
    "loss_pause_minutes",
    "small_account_min_order",
    "min_reward_risk",
    "min_quote_volume_usdt",
)


def merged_settings(
    base: AutoTradeSettings, limits: RiskLimits, changes: dict[str, Any]
) -> AutoTradeSettings:
    """Değişiklikleri temel ayarlara uygular. Risk sınırları üst sınırdır; aşılamaz (ValueError)."""
    data = base.model_dump(mode="json")
    data.update({k: v for k, v in changes.items() if k in EDITABLE})
    cfg = AutoTradeSettings.model_validate(data)
    if not cfg.markets:
        raise ValueError("En az bir piyasa seçin")
    if cfg.risk_per_trade_pct > limits.max_risk_per_trade_pct:
        raise ValueError(
            f"İşlem başına risk, risk sınırını (%{limits.max_risk_per_trade_pct}) aşamaz"
        )
    if cfg.leverage > limits.max_leverage:
        raise ValueError(f"Kaldıraç, risk sınırını ({limits.max_leverage}x) aşamaz")
    return cfg


class AutoTrader:
    def __init__(
        self,
        *,
        settings: AutoTradeSettings,
        limits: RiskLimits,
        service: ExecutionService | Callable[[], ExecutionService],
        trading_mode: Callable[[], TradingMode],
        clock: Callable[[], int] | None = None,
        interval: str = "1h",
        market_price: Callable[[Market, str], float | None] | None = None,
    ) -> None:
        self.cfg = settings
        self.defaults = settings
        self.limits = limits
        # Tek servis (testler) ya da işlem moduna göre Demo / gerçek hesap servisini veren işlev.
        self._service = service
        self.trading_mode = trading_mode
        self.enabled = settings.enabled
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._entries: deque[int] = deque()
        self._last_entry: dict[tuple[Market, str], int] = {}
        self.skipped: Counter[str] = Counter()
        self.stats = {"signals": 0, "opened": 0, "rejected": 0, "failed": 0}
        self.recent: deque[dict[str, Any]] = deque(maxlen=50)
        # Kayıp serisi: botun açtığı pozisyonların kapanış sonuçları (kısmi kapanışlar toplanır).
        self._open_pnl: dict[tuple[str, str, str], Decimal] = {}  # (mod, piyasa, sembol)
        self.loss_streak = 0
        self.paused_until_ms: int | None = None
        self.results = {"wins": 0, "losses": 0}
        # Puanlama aralığı (sonraki karar zamanı) ve gerçek piyasa fiyatı (kayma denetimi).
        self.interval = interval
        self._market_price = market_price
        # Son sinyaller (bot kapalıyken de): açılışta yeniden değerlendirme ve "en yakın adaylar".
        self._latest: dict[tuple[Market, str], OpportunityScored] = {}

    @property
    def service(self) -> ExecutionService:
        return self._service if isinstance(self._service, ExecutionService) else self._service()

    def _skip(self, reason: str) -> None:
        self.skipped[reason] += 1

    def max_signal_age_s(self) -> float:
        """Sinyalin geçerlilik süresi: ayar, ama mum aralığının dörtte birini (en az 60 sn)
        aşmaz; 1 saatte 15 dk, 15 dakikada ~4 dk, 1 dakikada 60 sn."""
        step_s = INTERVAL_MS.get(self.interval, 3_600_000) / 1000
        return min(self.cfg.max_signal_age_s, max(60.0, step_s / 4))

    def _close_ms(self, event: OpportunityScored) -> int:
        return event.bar_open_time_ms + INTERVAL_MS.get(event.interval, 0)

    def _remember(self, event: OpportunityScored) -> None:
        self._latest[(event.market, event.symbol)] = event
        step = INTERVAL_MS.get(self.interval, 3_600_000)
        horizon = self._clock() - 2 * step - int(self.max_signal_age_s() * 1000)
        for key in [k for k, e in self._latest.items() if self._close_ms(e) < horizon]:
            del self._latest[key]

    def _drifted(self, event: OpportunityScored) -> bool:
        """Sinyalden bu yana gerçek piyasa fiyatı stop uzaklığının yarısından fazla kaydı mı."""
        if self._market_price is None or not event.stop_price or event.price <= 0:
            return False
        current = self._market_price(event.market, event.symbol)
        if not current or current <= 0:
            return False
        signal = Decimal(str(event.price))
        stop_pct = abs(signal - Decimal(str(event.stop_price))) / signal
        move = abs(Decimal(str(current)) - signal) / signal
        return stop_pct > 0 and move > stop_pct * MAX_DRIFT_R

    async def on_opportunity(self, event: OpportunityScored) -> None:
        self.stats["signals"] += 1
        self._remember(event)
        await self._consider(event)

    async def replay(self) -> int:
        """Bot açıldığında son mumun hâlâ taze sinyallerini (yüksek puan önce) değerlendirir;
        böylece bir sonraki saat başı beklenmez. Açılan işlem sayısını döner."""
        before = self.stats["opened"]
        for event in sorted(self._latest.values(), key=lambda e: e.score, reverse=True):
            await self._consider(event)
        return self.stats["opened"] - before

    async def _consider(self, event: OpportunityScored) -> None:
        if not self.enabled:
            return self._skip("kapalı")
        mode = self.trading_mode()
        if event.market not in self.cfg.markets:
            return self._skip("piyasa")
        if event.score < self.cfg.min_score:
            return self._skip("puan")
        if self.paused_until_ms is not None:
            if self._clock() < self.paused_until_ms:
                return self._skip("kayıp_serisi_molası")
            self.paused_until_ms = None
            self.loss_streak = 0
        if event.direction not in ("long", "short"):
            return self._skip("yön")
        if event.market is Market.SPOT and event.direction == "short":
            return self._skip("spot_short")
        if not event.stop_price or not event.target_price or event.price <= 0:
            return self._skip("seviye_yok")
        risk = abs(event.price - event.stop_price)
        if risk <= 0 or abs(event.target_price - event.price) / risk < self.cfg.min_reward_risk:
            return self._skip("kazanç_oranı_düşük")
        volume = event.quote_volume_24h
        if volume is not None and volume < self.cfg.min_quote_volume_usdt:
            return self._skip("hacim_düşük")
        now = self._clock()
        close_ms = self._close_ms(event)
        if (now - close_ms) / 1000 > self.max_signal_age_s():
            return self._skip("eski_sinyal")
        if self._drifted(event):
            return self._skip("fiyat_kaçtı")
        while self._entries and now - self._entries[0] > 3_600_000:
            self._entries.popleft()
        if len(self._entries) >= self.cfg.max_entries_per_hour:
            return self._skip("saatlik_sınır")
        key = (event.market, event.symbol)
        last = self._last_entry.get(key)
        if last is not None and (now - last) / 1000 < self.cfg.symbol_cooldown_s:
            return self._skip("bekleme")
        execution = self.service.markets.get(event.market)
        if execution is None:
            return self._skip("bağlı_değil")
        info = execution.symbols.get(event.symbol)
        if info is None or not info.is_trading:
            return self._skip("test_ağında_yok")
        if event.symbol in execution.engine.positions.positions:
            return self._skip("açık_pozisyon")
        try:
            intent = await self._intent(event, execution, info)
        except Exception as exc:
            logger.warning("Otomatik işlem niyeti kurulamadı", extra={"error": repr(exc)})
            return self._skip("hazırlık_hatası")
        if intent is None:
            return None
        self._entries.append(now)
        self._last_entry[key] = now
        entry: dict[str, Any] = {
            "ts_ms": now,
            "market": event.market.value,
            "symbol": event.symbol,
            "direction": event.direction,
            "score": event.score,
            "decision_id": intent.decision_id,
            "quantity": str(intent.quantity),
        }
        try:
            managed = await self.service.open(intent, actor="autotrader")
        except RiskRejected as exc:
            self.stats["rejected"] += 1
            entry.update(result="rejected", reasons=[r.code for r in exc.decision.reasons])
        except ExecutionBlocked as exc:
            self.stats["rejected"] += 1
            entry.update(result="blocked", reasons=[str(exc)[:200]])
        except Exception as exc:
            self.stats["failed"] += 1
            entry.update(result="error", reasons=[type(exc).__name__])
            logger.error("Otomatik işlem açılamadı", extra={"error": repr(exc)})
        else:
            if managed.state == "open":
                self.stats["opened"] += 1
                self._open_pnl[(mode.value, event.market.value, event.symbol)] = Decimal(0)
            entry.update(result=managed.state, filled=str(managed.filled_qty))
        self.recent.appendleft(entry)
        return None

    async def on_trade_notice(self, notice: TradeNotice) -> None:
        """Botun açtığı pozisyonların sonucu: kısmi kapanışlar toplanır, pozisyon tamamen
        kapanınca kazanç/kayıp sayılır. Art arda ``max_consecutive_losses`` kayıpta mola."""
        key = (notice.mode, notice.market, notice.symbol)
        if notice.action != "closed" or key not in self._open_pnl:
            return
        self._open_pnl[key] += Decimal(notice.net_pnl or "0")
        execution = self.service.markets.get(Market(notice.market))
        if execution is not None and execution.engine.mode.value != notice.mode:
            execution = None
        if execution is not None and notice.symbol in execution.engine.positions.positions:
            return  # kısmi kapanış (ör. ilk hedef); pozisyon sürüyor
        pnl = self._open_pnl.pop(key)
        if pnl < 0:
            self.results["losses"] += 1
            self.loss_streak += 1
            limit = self.cfg.max_consecutive_losses
            if limit and self.loss_streak >= limit and self.paused_until_ms is None:
                self.paused_until_ms = self._clock() + self.cfg.loss_pause_minutes * 60_000
                logger.warning(
                    "Art arda kayıp: bot yeni girişlere mola verdi",
                    extra={"streak": self.loss_streak, "minutes": self.cfg.loss_pause_minutes},
                )
        else:
            self.results["wins"] += 1
            self.loss_streak = 0

    async def _intent(
        self, event: OpportunityScored, execution: Any, info: Any
    ) -> TradeIntent | None:
        price = await execution.engine.venue.price(event.symbol)
        if price is None or price <= 0:
            self._skip("fiyat_yok")
            return None
        direction = 1 if event.direction == "long" else -1
        signal = Decimal(str(event.price))
        stop_pct = abs(signal - Decimal(str(event.stop_price))) / signal
        target_pct = abs(Decimal(str(event.target_price)) - signal) / signal
        if stop_pct <= 0 or target_pct <= 0:
            self._skip("seviye_yok")
            return None
        stop = price * (1 - direction * stop_pct)
        target = price * (1 + direction * target_pct)
        snapshot = await self.service.monitor.snapshot(max_age_s=self.limits.max_snapshot_age_s)
        equity = min(snapshot.equity, snapshot.day_start_equity)
        risk_pct = min(self.cfg.risk_per_trade_pct, self.limits.max_risk_per_trade_pct)
        qty = size_for_risk(
            equity=equity,
            risk_pct=risk_pct,
            entry=price,
            stop=stop,
            fee_rate=self.service.gate.fees.get(event.market, DEFAULT_FEES[event.market]),
            slippage_pct=self.limits.slippage_allowance_pct,
            step=info.step_size,
        )
        if qty < info.min_qty or qty * price < info.min_notional:
            bumped = self._min_order(event.market, info, price, stop, equity)
            if bumped is None:
                self._skip("miktar_küçük")
                return None
            qty = bumped
        one_r = price * (1 + direction * stop_pct)
        take_profits: tuple[TakeProfit, ...]
        trailing: Decimal | None = None
        activation: Decimal | None = None
        if target_pct > stop_pct * Decimal("1.2"):
            if self.cfg.trailing_runner and event.market is Market.USDM_FUTURES:
                # Yarısı 1R'de alınır; kalan yarı iz süren stopla taşınır (geri çekilme payı
                # 1R uzaklığı kadar, %0,2-%5 arası). Zarar durdur ilk hedeften sonra girişe çekilir.
                take_profits = (TakeProfit(one_r, Decimal("0.5")),)
                trailing = min(max(stop_pct * 100, Decimal("0.2")), Decimal(5)).quantize(
                    Decimal("0.1"), rounding=ROUND_DOWN
                )
                activation = one_r
            else:
                take_profits = (
                    TakeProfit(one_r, Decimal("0.5")),
                    TakeProfit(target, Decimal("0.5")),
                )
        else:
            take_profits = (TakeProfit(target, Decimal(1)),)
        return TradeIntent(
            decision_id=(
                f"oto-{MODE_PREFIX.get(self.trading_mode(), '')}"
                f"{event.market.value}-{event.symbol}-{event.bar_open_time_ms}"
            ),
            market=event.market,
            symbol=event.symbol,
            direction=direction,
            quantity=qty,
            reference_price=price,
            stop_loss=stop,
            take_profits=take_profits,
            trailing_callback_pct=trailing,
            trailing_activation=activation,
            leverage=self.cfg.leverage if event.market is Market.USDM_FUTURES else None,
            reason=f"otomatik: puan {event.score:.0f}; " + "; ".join(event.reasons[:3]),
            strategy_id=None,
            opportunity_score=event.score,
            signals=tuple(event.reasons[:10]),
        )

    def candidates(self, limit: int = 5) -> list[dict[str, Any]]:
        """Son kapanan mumun en yüksek puanlı sinyalleri (eşik altı olanlar dahil)."""
        if not self._latest:
            return []
        latest_close = max(self._close_ms(e) for e in self._latest.values())
        rows = [e for e in self._latest.values() if self._close_ms(e) == latest_close]
        rows.sort(key=lambda e: e.score, reverse=True)
        now = self._clock()
        return [
            {
                "market": e.market.value,
                "symbol": e.symbol,
                "direction": e.direction,
                "score": round(e.score, 1),
                "close_ms": self._close_ms(e),
                "age_s": max(0, (now - self._close_ms(e)) // 1000),
                "fresh": (now - self._close_ms(e)) / 1000 <= self.max_signal_age_s(),
            }
            for e in rows[:limit]
        ]

    def next_decision_ms(self) -> int:
        step = INTERVAL_MS.get(self.interval, 3_600_000)
        return (self._clock() // step + 1) * step

    def _min_order(
        self, market: Market, info: Any, price: Decimal, stop: Decimal, equity: Decimal
    ) -> Decimal | None:
        """Küçük hesap: risk payıyla hesaplanan miktar borsanın en küçük emrinin altındaysa en
        küçük emir kullanılır; ancak o emrin riski risk sınırını (işlem başına en çok %X) aşmıyorsa.
        Kapatma emirleri (reduce-only) en küçük tutar kuralından muaftır."""
        if not self.cfg.small_account_min_order or equity <= 0 or price <= 0:
            return None
        step = info.step_size if info.step_size > 0 else Decimal("0.001")
        need = max(info.min_qty, info.min_notional * Decimal("1.05") / price)
        qty: Decimal = (need / step).to_integral_value(rounding=ROUND_UP) * step
        risk = trade_risk(
            quantity=qty,
            entry=price,
            stop=stop,
            fee_rate=self.service.gate.fees.get(market, DEFAULT_FEES[market]),
            slippage_pct=self.limits.slippage_allowance_pct,
        )
        if risk / equity * 100 > self.limits.max_risk_per_trade_pct:
            self._skip("bakiye_küçük")
            return None
        return qty

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "interval": self.interval,
            "signal_valid_s": int(self.max_signal_age_s()),
            "next_decision_ms": self.next_decision_ms(),
            "candidates": self.candidates(),
            "environment": {
                TradingMode.LIVE: "live",
                TradingMode.TESTNET: "testnet",
                TradingMode.PAPER: "paper",
            }[self.trading_mode()],
            "settings": self.cfg.model_dump(mode="json"),
            "defaults": {
                k: v for k, v in self.defaults.model_dump(mode="json").items() if k in EDITABLE
            },
            "limits": {
                "max_risk_per_trade_pct": str(self.limits.max_risk_per_trade_pct),
                "max_leverage": self.limits.max_leverage,
            },
            "stats": dict(self.stats),
            "skipped": dict(self.skipped),
            "entries_last_hour": len(self._entries),
            "loss_streak": self.loss_streak,
            "paused_until_ms": self.paused_until_ms,
            "results": dict(self.results),
            "recent": list(self.recent),
            "disclaimer": (
                "GERÇEK PARA ile işlem yapılır; kayıp riski vardır."
                if self.trading_mode() is TradingMode.LIVE
                else "Demo Trading işlemleridir; gerçek para kullanılmaz."
            )
            + " Sonuçlar garanti değildir ve gelecekteki performansı göstermez.",
        }
