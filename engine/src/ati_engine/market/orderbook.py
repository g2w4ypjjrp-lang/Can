"""Yerel emir defteri ve Binance senkronizasyon algoritmaları.

Binance'in belgelediği adımlar birebir uygulanır:

**Spot** (``How to manage a local order book correctly``):
 1. Akış tamponlanır; ilk olayın ``U`` değeri not edilir.
 2. REST anlık görüntüsü alınır. ``lastUpdateId < ilk U`` ise anlık görüntü eskidir → tekrar al.
 3. Tampondaki ``u <= lastUpdateId`` olaylar atılır.
 4. Güncelleme kuralı: ``u < defter_id`` → yok say; ``U > defter_id + 1`` → olay kaçırıldı,
    defteri at ve baştan senkronla; aksi halde uygula, ``defter_id = u``.

**USDⓈ-M Futures**:
 1. Akış tamponlanır, anlık görüntü (limit 1000) alınır.
 2. ``u < lastUpdateId`` olaylar atılır.
 3. İşlenen ilk olay ``U <= lastUpdateId <= u`` koşulunu sağlamalıdır.
 4. Sonraki her olayın ``pu`` değeri bir önceki olayın ``u`` değerine eşit olmalıdır; değilse
    baştan senkronla.

Her iki piyasada miktarlar mutlaktır; miktarı 0 olan seviye silinir. Defterde olmayan bir
seviyenin silinmesi normaldir.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from ati_engine.core.models import Market
from ati_engine.market.events import DepthDiff


@dataclass(frozen=True)
class DepthSnapshot:
    last_update_id: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]

    @classmethod
    def from_rest(cls, payload: dict[str, object]) -> DepthSnapshot:
        def levels(key: str) -> list[tuple[float, float]]:
            raw = payload.get(key) or []
            assert isinstance(raw, list)  # noqa: S101
            return [(float(p), float(q)) for p, q in raw]

        last = payload["lastUpdateId"]
        assert isinstance(last, int)  # noqa: S101
        return cls(last_update_id=last, bids=levels("bids"), asks=levels("asks"))


class OrderBook:
    """Fiyat → miktar sözlükleri. En iyi seviyeler gerektiğinde yığın (heap) ile seçilir."""

    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.update_id = 0

    def reset(self, snapshot: DepthSnapshot) -> None:
        self.bids = {p: q for p, q in snapshot.bids if q > 0}
        self.asks = {p: q for p, q in snapshot.asks if q > 0}
        self.update_id = snapshot.last_update_id

    @staticmethod
    def _apply_side(side: dict[float, float], levels: Iterable[tuple[float, float]]) -> None:
        for price, qty in levels:
            if qty == 0:
                side.pop(price, None)
            else:
                side[price] = qty

    def apply(self, diff: DepthDiff) -> None:
        self._apply_side(self.bids, diff.bids)
        self._apply_side(self.asks, diff.asks)
        self.update_id = diff.final_update_id

    def best_bid(self) -> tuple[float, float] | None:
        if not self.bids:
            return None
        price = max(self.bids)
        return price, self.bids[price]

    def best_ask(self) -> tuple[float, float] | None:
        if not self.asks:
            return None
        price = min(self.asks)
        return price, self.asks[price]

    def top_bids(self, n: int) -> list[tuple[float, float]]:
        return [(p, self.bids[p]) for p in heapq.nlargest(n, self.bids)]

    def top_asks(self, n: int) -> list[tuple[float, float]]:
        return [(p, self.asks[p]) for p in heapq.nsmallest(n, self.asks)]

    def notional(self, levels: list[tuple[float, float]]) -> float:
        return sum(p * q for p, q in levels)

    def imbalance(self, n: int = 10) -> float:
        """-1 (tamamen satış baskısı) ile +1 (tamamen alış baskısı) arası."""
        bid = self.notional(self.top_bids(n))
        ask = self.notional(self.top_asks(n))
        total = bid + ask
        return 0.0 if total == 0 else (bid - ask) / total

    def is_crossed(self) -> bool:
        bb, ba = self.best_bid(), self.best_ask()
        return bb is not None and ba is not None and bb[0] >= ba[0]


class SyncState(StrEnum):
    BUFFERING = "buffering"  # anlık görüntü bekleniyor
    SYNCED = "synced"


class ResyncRequired(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SnapshotTooOld(Exception):
    pass


@dataclass
class BookSynchronizer:
    """Tek bir sembolün defterini Binance algoritmasına göre senkron tutar.

    Kullanım: her ``DepthDiff`` için ``on_diff``; durum BUFFERING ise çağıran anlık görüntüyü
    alıp ``on_snapshot`` çağırır. ``ResyncRequired`` yükselirse defter atılmıştır; çağıran
    yeni anlık görüntü almalıdır.
    """

    market: Market
    symbol: str
    max_buffer: int = 5_000
    book: OrderBook = field(default_factory=OrderBook)
    state: SyncState = SyncState.BUFFERING
    buffer: list[DepthDiff] = field(default_factory=list)
    resyncs: int = 0
    applied: int = 0
    # Futures: anlık görüntüden sonraki ilk olay pu ile değil örtüşme koşuluyla doğrulanır.
    _awaiting_first: bool = False

    def _reset(self, reason: str) -> None:
        self.state = SyncState.BUFFERING
        self.book = OrderBook()
        self.buffer = []
        self.resyncs += 1
        raise ResyncRequired(reason)

    def on_diff(self, diff: DepthDiff) -> bool:
        """Olayı işler. Defter güncellendiyse True döner."""
        if self.state is SyncState.BUFFERING:
            self.buffer.append(diff)
            if len(self.buffer) > self.max_buffer:
                self.buffer = self.buffer[-self.max_buffer :]
            return False
        return self._apply_live(diff)

    def _apply_live(self, diff: DepthDiff) -> bool:
        book = self.book
        if self.market is Market.SPOT:
            if diff.final_update_id < book.update_id:
                return False
            if diff.first_update_id > book.update_id + 1:
                self._reset(
                    f"olay kaçırıldı: U={diff.first_update_id} > defter_id+1={book.update_id + 1}"
                )
        else:
            if diff.final_update_id < book.update_id:
                return False
            if self._awaiting_first:
                if not diff.first_update_id <= book.update_id <= diff.final_update_id:
                    self._reset(
                        f"ilk olay anlık görüntüyle örtüşmüyor: U={diff.first_update_id}, "
                        f"u={diff.final_update_id}, lastUpdateId={book.update_id}"
                    )
                self._awaiting_first = False
            elif diff.prev_final_update_id != book.update_id:
                self._reset(
                    f"sıra bozuldu: pu={diff.prev_final_update_id} != önceki u={book.update_id}"
                )
        book.apply(diff)
        self.applied += 1
        if book.is_crossed():
            self._reset("defter çaprazlandı (en iyi alış >= en iyi satış)")
        return True

    def first_buffered_u(self) -> int | None:
        return self.buffer[0].first_update_id if self.buffer else None

    def on_snapshot(self, snapshot: DepthSnapshot) -> None:
        """Anlık görüntüyü uygular ve tamponu işler.

        Spot'ta anlık görüntü ilk tamponlanan olaydan eskiyse ``SnapshotTooOld`` yükselir
        (çağıran yeniden almalıdır).
        """
        first_u = self.first_buffered_u()
        if self.market is Market.SPOT and first_u is not None and snapshot.last_update_id < first_u:
            raise SnapshotTooOld(
                f"anlık görüntü ({snapshot.last_update_id}) ilk olaydan ({first_u}) eski"
            )
        self.book = OrderBook()
        self.book.reset(snapshot)
        pending = self.buffer
        self.buffer = []
        last = snapshot.last_update_id
        if self.market is Market.SPOT:
            pending = [d for d in pending if d.final_update_id > last]
        else:
            pending = [d for d in pending if d.final_update_id >= last]
            self._awaiting_first = True
        self.state = SyncState.SYNCED
        for diff in pending:
            self._apply_live(diff)
