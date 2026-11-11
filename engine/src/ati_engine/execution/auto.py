"""Otomatik işlem: fırsat sinyallerini işleme dönüştürür.

Varsayılan olarak **kapalıdır**; kullanıcı açar. Seçili işlem moduna göre **Demo Trading**'de
ya da kullanıcı gerçek hesap modunu (onay ifadesiyle) açtıysa **gerçek hesapta** çalışır; sanal
modda işlem açmaz. Her işlem risk kapısından geçer; bu modül yalnızca niyet üretir:

1. Sinyal: eşik üstü ``OpportunityScored`` (yön, stop ve hedef seviyesiyle). Mum kapanışından
   bu yana ``max_signal_age_s``'den eski sinyal kullanılmaz.
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
from decimal import ROUND_DOWN, Decimal
from typing import Any

from ati_engine.config import AutoTradeSettings, RiskLimits
from ati_engine.core.events import TradeNotice
from ati_engine.core.models import Market, TradingMode
from ati_engine.execution.approval import RiskRejected
from ati_engine.execution.engine import TakeProfit, TradeIntent
from ati_engine.execution.service import ExecutionService
from ati_engine.execution.venue import ExecutionBlocked
from ati_engine.history.archive import INTERVAL_MS
from ati_engine.risk.gate import DEFAULT_FEES, size_for_risk
from ati_engine.scoring.live import OpportunityScored

logger = logging.getLogger(__name__)

# Kullanıcının uygulamadan değiştirebildiği bot ayarları (kalıcı; motor açılışında uygulanır).
SETTINGS_KEY = "autotrade.settings"
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

    @property
    def service(self) -> ExecutionService:
        return self._service if isinstance(self._service, ExecutionService) else self._service()

    def _skip(self, reason: str) -> None:
        self.skipped[reason] += 1

    async def on_opportunity(self, event: OpportunityScored) -> None:
        self.stats["signals"] += 1
        if not self.enabled:
            return self._skip("kapalı")
        mode = self.trading_mode()
        if mode is TradingMode.PAPER:
            return self._skip("mod_sanal")
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
        now = self._clock()
        close_ms = event.bar_open_time_ms + INTERVAL_MS.get(event.interval, 0)
        if (now - close_ms) / 1000 > self.cfg.max_signal_age_s:
            return self._skip("eski_sinyal")
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
            self._skip("miktar_küçük")
            return None
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
                f"oto-{'canli-' if self.trading_mode() is TradingMode.LIVE else ''}"
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

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
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
