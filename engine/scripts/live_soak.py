"""Gerçek Binance verisiyle dayanıklılık (soak) testi.

Motoru tüm izlenen sembollerle süreç içinde çalıştırır ve şunları ölçer:
* Veri kaybı: her sembolün aggTrade kimliği (``a``) ardışık artmalıdır; atlama = kayıp mesaj.
* Emir defteri yeniden senkron sayısı (sıra boşluğu tespiti).
* Bağlantı kopmaları, hazırlık koşulu değişimleri, motor durum geçişleri.
* Olay döngüsü gecikmesi (p99, maksimum) ve mesaj hızları.

Kullanım (yalnızca herkese açık piyasa verisi; API anahtarı gerekmez)::

    uv run python scripts/live_soak.py --seconds 600 --report soak.json
    # Futures REST'in coğrafi engelli olduğu ortamlarda:
    uv run python scripts/live_soak.py --futures-rest https://www.binance.com
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.core.bus import OverflowPolicy
from ati_engine.core.events import EngineStateChanged, ReadinessChanged
from ati_engine.market.events import AggTrade, OrderBookResynced, StreamConnectionChanged


async def soak(args: argparse.Namespace) -> dict[str, object]:
    data_dir = Path(args.data_dir or tempfile.mkdtemp(prefix="ati-soak-"))
    overrides: dict[str, object] = {}
    if args.futures_rest:
        overrides["futures_rest"] = args.futures_rest
    settings = EngineSettings(
        data_dir=data_dir,
        log_to_console=False,
        api=LocalApiSettings(port=0),
        binance={
            **EngineSettings.model_fields["binance"].default_factory().model_dump(),
            **overrides,
        },  # type: ignore[misc]
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=60)
    runtime = engine.runtime
    if runtime is None:
        raise RuntimeError("motor başlatılamadı")

    last_trade: dict[tuple[str, str], int] = {}
    seen_ids: dict[tuple[str, str], set[int]] = defaultdict(set)
    recovered = 0
    gaps: dict[str, int] = defaultdict(int)
    gap_examples: list[str] = []
    duplicates = 0
    trades = 0
    resyncs: list[str] = []
    disconnects: list[str] = []
    states: list[str] = []
    readiness: list[str] = []

    def on_trade(event: AggTrade) -> None:
        nonlocal trades, duplicates, recovered
        key = (event.market.value, event.symbol)
        seen_ids[key].add(event.trade_id)
        if event.recovered:
            recovered += 1
            return
        trades += 1
        prev = last_trade.get(key)
        if prev is not None:
            if event.trade_id <= prev:
                duplicates += 1
                return
            if event.trade_id != prev + 1:
                gaps[event.market.value] += 1
                if len(gap_examples) < 10:
                    gap_examples.append(f"{key}: {prev} -> {event.trade_id}")
        last_trade[key] = event.trade_id

    bus = runtime.bus
    bus.subscribe(
        AggTrade, on_trade, name="soak-trades", maxsize=500_000, policy=OverflowPolicy.BLOCK
    )
    bus.subscribe(
        OrderBookResynced,
        lambda e: resyncs.append(f"{e.market.value}:{e.symbol}:{e.reason}"),
        name="soak-resync",
    )
    bus.subscribe(
        StreamConnectionChanged,
        lambda e: disconnects.append(f"{e.connection}:{e.reason}") if not e.connected else None,
        name="soak-conn",
    )
    bus.subscribe(
        EngineStateChanged,
        lambda e: states.append(f"{e.previous.value}->{e.current.value}: {e.reason}"),
        name="soak-state",
    )
    bus.subscribe(
        ReadinessChanged,
        lambda e: readiness.append(f"{e.condition}={e.ready}: {e.detail}"),
        name="soak-ready",
    )

    start = time.monotonic()
    lag_samples: list[float] = []
    running_since: float | None = None
    while time.monotonic() - start < args.seconds:
        await asyncio.sleep(5)
        lag_samples.append(runtime.loop_monitor.p99_ms())
        if running_since is None and runtime.safety.state.can_open_positions():
            running_since = time.monotonic() - start
        if args.verbose:
            print(
                f"[{time.monotonic() - start:6.0f}s] durum={runtime.safety.state.state.value} "
                f"işlem={trades} boşluk={dict(gaps)} "
                f"lag_p99={runtime.loop_monitor.p99_ms():.1f}ms",
                flush=True,
            )

    # Bekleyen geri doldurmaların bitmesini bekle (en fazla 60 sn).
    for _ in range(120):
        if all(s.gaps.stats.pending == 0 for s in runtime.market_data.values()):
            break
        await asyncio.sleep(0.5)
    missing_after_backfill = 0
    missing_examples: list[str] = []
    for key, ids in seen_ids.items():
        missing = max(ids) - min(ids) + 1 - len(ids)
        if missing:
            missing_after_backfill += missing
            if len(missing_examples) < 10:
                missing_examples.append(f"{key}: {missing}")

    markets = {m.value: s.status() for m, s in runtime.market_data.items()}
    # Kapanış sırasında oluşan olaylar rapora karışmasın diye listeler burada kopyalanır
    # (yeni adlarla: olay işleyicileri özgün listelere yazmaya devam eder).
    snap_resyncs, snap_disconnects = list(resyncs), list(disconnects)
    snap_states, snap_readiness = list(states), list(readiness)
    report = {
        "duration_s": round(time.monotonic() - start, 1),
        "time_to_running_s": running_since,
        "final_state": runtime.safety.state.state.value,
        "agg_trades": trades,
        "symbols_with_trades": len(last_trade),
        "agg_trade_gaps": dict(gaps),
        "agg_trade_gap_examples": gap_examples,
        "agg_trade_duplicates": duplicates,
        "recovered_trades": recovered,
        "missing_after_backfill": missing_after_backfill,
        "missing_examples": missing_examples,
        "order_book_resyncs": snap_resyncs,
        "disconnects": snap_disconnects,
        "engine_state_changes": snap_states,
        "readiness_changes": snap_readiness,
        "loop_lag_p99_ms_max_window": round(max(lag_samples, default=0.0), 2),
        "loop_lag_max_ms": round(runtime.loop_monitor.max_ms, 2),
        "markets": {
            name: {
                "tracked_symbols": st["tracked_symbols"],
                "streams": st["streams"],
                "connections": len(st["connections"]),
                "reconnects": sum(c.reconnects for c in runtime.market_data[m].streams.connections),
                "message_rates_per_s": st["message_rates_per_s"],
                "books": [
                    (b["symbol"], b["state"], b["resyncs"], b["applied"]) for b in st["order_books"]
                ],
                "rest_budget": st["rest_budget"],
                "trade_gaps": st["trade_gaps"],
            }
            for m, (name, st) in zip(runtime.market_data, markets.items(), strict=True)
        },
    }
    runtime.request_shutdown()
    await asyncio.wait_for(task, timeout=30)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--futures-rest")
    parser.add_argument("--data-dir")
    parser.add_argument("--report")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(soak(args))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
