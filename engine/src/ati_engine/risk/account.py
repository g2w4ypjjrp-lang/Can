"""Hesap anlık görüntüsü: özsermaye, açık pozisyonlar ve günlük zarar.

Değerler **borsadan** okunur (yerel kayıttan değil):

* Futures: cüzdan bakiyesi (kote varlık) + açık pozisyonların gerçekleşmemiş kâr/zararı.
* Spot: kote varlık bakiyesi + bu motorun açtığı pozisyonların güncel değeri. Hesaptaki diğer
  varlıklar (ör. test ağının verdiği hazır bakiyeler) özsermayeye katılmaz.

Gün başı özsermaye her işlem modu için UTC gününün ilk ölçümünde ``risk_daily`` tablosuna
yazılır ve gün boyunca değişmez; motorun yeniden başlatılması günlük zarar sayacını sıfırlamaz.
Para yatırma/çekme bu hesapta ayrıştırılmaz (test ağında yoktur); gerçek hesapta (G1/G2 sonrası)
ayrıca ele alınacaktır.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from ati_engine.core.models import Market, TradingMode, format_decimal
from ati_engine.execution.engine import TradingEngine
from ati_engine.storage.database import Database

ZERO = Decimal(0)


@dataclass(frozen=True)
class PositionExposure:
    market: Market
    symbol: str
    quantity: Decimal  # işaretli
    entry_price: Decimal
    mark_price: Decimal
    leverage: int
    liquidation_price: Decimal | None = None

    @property
    def notional(self) -> Decimal:
        return abs(self.quantity) * self.mark_price

    @property
    def liquidation_distance_pct(self) -> Decimal | None:
        if self.liquidation_price is None or self.mark_price <= 0:
            return None
        return abs(self.mark_price - self.liquidation_price) / self.mark_price * 100


@dataclass(frozen=True)
class AccountSnapshot:
    mode: TradingMode
    ts_ms: int
    day: str
    equity: Decimal
    day_start_equity: Decimal
    positions: tuple[PositionExposure, ...] = ()
    halted_at: int | None = None
    halt_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def daily_loss(self) -> Decimal:
        """Gün başından bu yana kayıp (kâr varsa 0)."""
        return max(self.day_start_equity - self.equity, ZERO)

    @property
    def daily_loss_pct(self) -> Decimal:
        if self.day_start_equity <= 0:
            return ZERO
        return self.daily_loss / self.day_start_equity * 100

    @property
    def total_notional(self) -> Decimal:
        return sum((p.notional for p in self.positions), ZERO)

    def age_s(self, now_ms: int | None = None) -> float:
        return ((now_ms or _now_ms()) - self.ts_ms) / 1000


def utc_day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


class AccountMonitor:
    def __init__(
        self,
        db: Database,
        *,
        mode: TradingMode,
        engines: Callable[[], Sequence[TradingEngine]],
        quote_asset: str = "USDT",
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.db = db
        self.mode = mode
        self.engines = engines
        self.quote = quote_asset
        self._clock = clock or _now_ms
        self.last: AccountSnapshot | None = None
        self._lock = asyncio.Lock()

    async def snapshot(self, *, max_age_s: float) -> AccountSnapshot:
        last = self.last
        if last is not None and last.age_s(self._clock()) <= max_age_s:
            return last
        return await self.refresh()

    async def refresh(self) -> AccountSnapshot:
        async with self._lock:
            now = self._clock()
            equity = ZERO
            exposures: list[PositionExposure] = []
            for engine in self.engines():
                venue = engine.venue
                balances = await venue.balances()
                quote = sum((b.free + b.locked for b in balances if b.asset == self.quote), ZERO)
                equity += quote
                if engine.market is Market.USDM_FUTURES:
                    for p in await venue.positions():
                        if p.quantity == 0:
                            continue
                        mark = await venue.price(p.symbol) or p.entry_price
                        unrealized = p.unrealized_pnl
                        if not unrealized:
                            unrealized = (mark - p.entry_price) * p.quantity
                        equity += unrealized
                        exposures.append(
                            PositionExposure(
                                market=engine.market,
                                symbol=p.symbol,
                                quantity=p.quantity,
                                entry_price=p.entry_price,
                                mark_price=mark,
                                leverage=p.leverage,
                                liquidation_price=p.liquidation_price,
                            )
                        )
                else:
                    for symbol, position in engine.positions.positions.items():
                        mark = await venue.price(symbol) or position.entry_price
                        equity += position.quantity * mark
                        exposures.append(
                            PositionExposure(
                                market=engine.market,
                                symbol=symbol,
                                quantity=position.quantity,
                                entry_price=position.entry_price,
                                mark_price=mark,
                                leverage=1,
                            )
                        )
            day = utc_day(now)
            row = await self._day_row(day, equity, now)
            snapshot = AccountSnapshot(
                mode=self.mode,
                ts_ms=now,
                day=day,
                equity=equity,
                day_start_equity=row[0],
                positions=tuple(exposures),
                halted_at=row[1],
                halt_reason=row[2],
            )
            self.last = snapshot
            return snapshot

    async def _day_row(
        self, day: str, equity: Decimal, now: int
    ) -> tuple[Decimal, int | None, str | None]:
        text = format_decimal(equity)
        await self.db.execute(
            """
            INSERT INTO risk_daily (mode, day, start_equity, last_equity, min_equity, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (mode, day) DO UPDATE SET
                last_equity = excluded.last_equity,
                min_equity = CASE WHEN CAST(excluded.last_equity AS REAL)
                                       < CAST(risk_daily.min_equity AS REAL)
                                  THEN excluded.last_equity ELSE risk_daily.min_equity END,
                updated_at = excluded.updated_at
            """,
            (self.mode.value, day, text, text, text, now),
        )
        row = await self.db.fetchone(
            "SELECT start_equity, halted_at, halt_reason FROM risk_daily "
            "WHERE mode = ? AND day = ?",
            (self.mode.value, day),
        )
        if row is None:  # pragma: no cover - az önce yazıldı
            raise RuntimeError("risk_daily satırı okunamadı")
        return Decimal(str(row[0])), row[1], row[2]

    async def halt_day(self, reason: str) -> bool:
        """Günü kilitler (günlük zarar sınırı). Zaten kilitliyse ``False``."""
        snapshot = self.last or await self.refresh()
        changed = await self.db.execute(
            """
            UPDATE risk_daily SET halted_at = ?, halt_reason = ?
            WHERE mode = ? AND day = ? AND halted_at IS NULL
            """,
            (self._clock(), reason[:300], self.mode.value, snapshot.day),
        )
        if changed:
            self.last = None  # sonraki okuma kilidi görsün
        return changed > 0


def _now_ms() -> int:
    return int(time.time() * 1000)
