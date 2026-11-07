"""Yerel emir defteri senkronizasyon algoritmaları (Spot ve USDⓈ-M Futures)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ati_engine.core.models import Market
from ati_engine.market.events import DepthDiff
from ati_engine.market.orderbook import (
    BookSynchronizer,
    DepthSnapshot,
    OrderBook,
    ResyncRequired,
    SnapshotTooOld,
    SyncState,
)

FIXTURES = Path(__file__).parent / "fixtures" / "binance"


def diff(
    market: Market,
    first: int,
    final: int,
    prev: int | None = None,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
) -> DepthDiff:
    return DepthDiff(
        market=market,
        event_time_ms=0,
        symbol="BTCUSDT",
        first_update_id=first,
        final_update_id=final,
        prev_final_update_id=prev,
        bids=bids or [],
        asks=asks or [],
    )


def snapshot(last: int) -> DepthSnapshot:
    return DepthSnapshot(
        last_update_id=last, bids=[(100.0, 1.0), (99.0, 2.0)], asks=[(101.0, 1.0), (102.0, 3.0)]
    )


# --- Spot -----------------------------------------------------------------------------------


def test_spot_normal_sync() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    s.on_diff(diff(Market.SPOT, 100, 105, bids=[(98.0, 9.0)]))  # anlık görüntüden eski
    s.on_diff(diff(Market.SPOT, 106, 110, bids=[(100.0, 5.0)]))
    s.on_diff(diff(Market.SPOT, 111, 115, asks=[(101.0, 0.0)]))
    assert s.state is SyncState.BUFFERING
    s.on_snapshot(snapshot(107))
    assert s.state is SyncState.SYNCED
    assert s.book.update_id == 115
    assert s.book.bids[100.0] == 5.0
    assert 98.0 not in s.book.bids  # atılan olay uygulanmadı
    assert 101.0 not in s.book.asks  # miktar 0 → seviye silindi
    assert s.book.best_ask() == (102.0, 3.0)


def test_spot_snapshot_older_than_buffer_is_refetched() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    s.on_diff(diff(Market.SPOT, 200, 205))
    with pytest.raises(SnapshotTooOld):
        s.on_snapshot(snapshot(150))
    assert s.state is SyncState.BUFFERING
    assert len(s.buffer) == 1  # tampon korunur
    s.on_snapshot(snapshot(202))
    assert s.state is SyncState.SYNCED
    assert s.book.update_id == 205


def test_spot_gap_forces_resync() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    s.on_diff(diff(Market.SPOT, 100, 110))
    s.on_snapshot(snapshot(105))
    with pytest.raises(ResyncRequired, match="kaçırıldı"):
        s.on_diff(diff(Market.SPOT, 120, 125))  # 111..119 kayıp
    assert s.state is SyncState.BUFFERING
    assert s.resyncs == 1
    assert s.book.bids == {}


def test_spot_stale_events_are_ignored() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    s.on_diff(diff(Market.SPOT, 100, 110))
    s.on_snapshot(snapshot(105))
    assert s.on_diff(diff(Market.SPOT, 95, 108)) is False
    assert s.book.update_id == 110


def test_crossed_book_forces_resync() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT")
    s.on_diff(diff(Market.SPOT, 100, 110))
    s.on_snapshot(snapshot(105))
    with pytest.raises(ResyncRequired, match="çaprazlandı"):
        s.on_diff(diff(Market.SPOT, 111, 112, bids=[(103.0, 1.0)]))


# --- USDⓈ-M Futures --------------------------------------------------------------------------


def test_futures_normal_sync() -> None:
    s = BookSynchronizer(market=Market.USDM_FUTURES, symbol="BTCUSDT")
    s.on_diff(diff(Market.USDM_FUTURES, 90, 100, prev=80))
    s.on_diff(diff(Market.USDM_FUTURES, 101, 110, prev=100, bids=[(100.0, 7.0)]))
    s.on_diff(diff(Market.USDM_FUTURES, 111, 120, prev=110))
    s.on_snapshot(snapshot(105))  # ilk işlenen: U=101 <= 105 <= u=110
    assert s.state is SyncState.SYNCED
    assert s.book.update_id == 120
    assert s.book.bids[100.0] == 7.0


def test_futures_first_event_must_overlap_snapshot() -> None:
    s = BookSynchronizer(market=Market.USDM_FUTURES, symbol="BTCUSDT")
    s.on_diff(diff(Market.USDM_FUTURES, 106, 110, prev=105))
    with pytest.raises(ResyncRequired, match="örtüşmüyor"):
        s.on_snapshot(snapshot(104))  # 104 < U=106


def test_futures_snapshot_newer_than_buffer_waits_for_overlapping_event() -> None:
    """Gerileme testi: anlık görüntü tüm tampondan yeniyse sonraki ilk canlı olay pu ile değil
    örtüşme koşuluyla doğrulanmalı; aksi halde defter sonsuz yeniden senkron döngüsüne girer."""
    s = BookSynchronizer(market=Market.USDM_FUTURES, symbol="BTCUSDT")
    s.on_diff(diff(Market.USDM_FUTURES, 90, 100, prev=80))
    s.on_snapshot(snapshot(150))
    assert s.state is SyncState.SYNCED
    assert s.on_diff(diff(Market.USDM_FUTURES, 101, 120, prev=100)) is False  # u < 150: eski
    assert s.on_diff(diff(Market.USDM_FUTURES, 140, 160, prev=139)) is True  # örtüşüyor
    assert s.on_diff(diff(Market.USDM_FUTURES, 161, 170, prev=160)) is True
    assert s.resyncs == 0
    assert s.book.update_id == 170


def test_futures_pu_mismatch_forces_resync() -> None:
    s = BookSynchronizer(market=Market.USDM_FUTURES, symbol="BTCUSDT")
    s.on_diff(diff(Market.USDM_FUTURES, 101, 110, prev=100))
    s.on_snapshot(snapshot(105))
    with pytest.raises(ResyncRequired, match="sıra bozuldu"):
        s.on_diff(diff(Market.USDM_FUTURES, 115, 120, prev=114))  # 110 bekleniyordu
    assert s.state is SyncState.BUFFERING


def test_buffer_is_bounded() -> None:
    s = BookSynchronizer(market=Market.SPOT, symbol="BTCUSDT", max_buffer=3)
    for i in range(10):
        s.on_diff(diff(Market.SPOT, i * 10, i * 10 + 9))
    assert len(s.buffer) == 3
    assert s.first_buffered_u() == 70


# --- Defter hesapları --------------------------------------------------------------------------


def test_order_book_metrics() -> None:
    book = OrderBook()
    book.reset(
        DepthSnapshot(
            last_update_id=1,
            bids=[(100.0, 2.0), (99.0, 1.0), (98.0, 0.0)],
            asks=[(101.0, 1.0), (102.0, 1.0)],
        )
    )
    assert 98.0 not in book.bids  # sıfır miktar baştan alınmaz
    assert book.top_bids(5) == [(100.0, 2.0), (99.0, 1.0)]
    assert book.top_asks(1) == [(101.0, 1.0)]
    bid, ask = 200.0 + 99.0, 101.0 + 102.0
    assert book.imbalance(10) == pytest.approx((bid - ask) / (bid + ask))
    assert not book.is_crossed()


def test_snapshot_from_real_rest_payload() -> None:
    payload = json.loads((FIXTURES / "spot_depth_snapshot.json").read_text())
    snap = DepthSnapshot.from_rest(payload)
    assert snap.last_update_id == payload["lastUpdateId"]
    assert len(snap.bids) == len(payload["bids"])
    book = OrderBook()
    book.reset(snap)
    best_bid, best_ask = book.best_bid(), book.best_ask()
    assert best_bid is not None
    assert best_ask is not None
    assert best_bid[0] < best_ask[0]
