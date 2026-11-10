"""Aşama 11: otomatik işlem (fırsat sinyali → test ağı işlemi, risk kapısından geçerek)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ati_engine.config import AutoTradeSettings, BinanceEndpoints, EngineSettings
from ati_engine.core.events import TradeNotice
from ati_engine.core.models import EngineState, Market, TradingMode
from ati_engine.execution.auto import AutoTrader
from ati_engine.execution.service import ExecutionService
from ati_engine.scoring.live import OpportunityScored
from ati_engine.security.exchange_keys import ExchangeKeyStore
from ati_engine.security.vault import AesGcmCipher, SecretVault
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database
from fake_exchange import FakeExchange

D = Decimal
API_KEY = "TestAnahtar0123456789abcdef"
SECRET = "TestGizli0123456789abcdefXYZ"


@pytest.fixture
async def exchange() -> AsyncIterator[FakeExchange]:
    fake = await FakeExchange(api_key=API_KEY, secret=SECRET).start()
    fake.prices.update({"BTCUSDT": D(100), "ETHUSDT": D(50)})
    yield fake
    await fake.stop()


@pytest.fixture
async def service(
    tmp_path: Path, db: Database, exchange: FakeExchange
) -> AsyncIterator[tuple[ExecutionService, list[TradingMode]]]:
    settings = EngineSettings(
        data_dir=tmp_path / "data",
        log_to_console=False,
        binance=BinanceEndpoints(
            futures_testnet_rest=exchange.rest_url,
            futures_testnet_ws_private=exchange.private_ws_url,
        ),
    )
    mode = [TradingMode.TESTNET]
    keys = ExchangeKeyStore(SecretVault(db, AesGcmCipher(AesGcmCipher.generate_key())))
    await keys.store("testnet", Market.USDM_FUTURES, API_KEY, SECRET)
    svc = ExecutionService(
        settings=settings,
        db=db,
        audit=AuditLog(db),
        keys=keys,
        trading_mode=lambda: mode[0],
        engine_state=lambda: EngineState.RUNNING,
    )
    await svc.connect(Market.USDM_FUTURES)
    yield svc, mode
    await svc.close()


def signal(**kw: Any) -> OpportunityScored:
    now = int(time.time() * 1000)
    values: dict[str, Any] = {
        "market": Market.USDM_FUTURES,
        "symbol": "BTCUSDT",
        "interval": "1h",
        "bar_open_time_ms": now - 3_600_000,  # az önce kapanan mum
        "direction": "long",
        "score": 78.0,
        "price": 75_000.0,  # gerçek piyasa fiyatı; test ağı 100
        "stop_price": 73_500.0,  # %2 aşağı
        "target_price": 78_000.0,  # %4 yukarı
        "reward_risk": 2.0,
        "cost_pct": 0.1,
        "reasons": ["trend", "hacim"],
    }
    values.update(kw)
    return OpportunityScored(**values)


def trader(svc: ExecutionService, mode: list[TradingMode], **kw: Any) -> AutoTrader:
    return AutoTrader(
        settings=AutoTradeSettings(enabled=True, **kw),
        limits=svc.settings.risk,
        service=svc,
        trading_mode=lambda: mode[0],
    )


def active_algos(exchange: FakeExchange) -> list[tuple[str, str, str]]:
    return sorted(
        (a["type"], a["triggerPrice"], a["quantity"])
        for a in exchange.algo_orders.values()
        if a["algoStatus"] == "NEW"
    )


async def test_signal_becomes_risk_sized_testnet_trade(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange, db: Database
) -> None:
    svc, mode = service
    auto = trader(svc, mode, trailing_runner=False)  # iki sabit hedef (iz süren stop ayrı test)
    await auto.on_opportunity(signal())
    assert auto.stats["opened"] == 1, auto.status()
    # Risk: 100.000 x %0,25 = 250; birim kayıp 2 + 100 x (0,0005 x 2 + 0,0005) = 2,15
    qty = exchange.futures_positions["BTCUSDT"][0]
    assert qty == D("116.279")
    # Uzaklıklar test ağı fiyatına uygulandı: stop %2 (98), 1R'de yarısı (102), hedef %4 (104).
    assert active_algos(exchange) == [
        ("STOP_MARKET", "98", "0"),
        ("TAKE_PROFIT_MARKET", "102", "58.139"),
        ("TAKE_PROFIT_MARKET", "104", "58.14"),
    ]
    leverage = [r[2] for r in exchange.requests if r[1] == "/fapi/v1/leverage"]
    assert leverage == [{**leverage[0], "symbol": "BTCUSDT", "leverage": "2"}]
    row = await db.fetchone(
        "SELECT risk_verdict, opportunity_score, signals FROM decisions WHERE id LIKE 'oto-%'"
    )
    assert row is not None and row[0] == "approved" and row[1] == 78.0 and "trend" in row[2]

    await auto.on_opportunity(signal())  # aynı sinyal tekrar: ikinci işlem yok
    assert auto.stats["opened"] == 1 and auto.skipped["bekleme"] == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"score": 65.0}, "puan"),
        ({"direction": "neutral"}, "yön"),
        ({"stop_price": None}, "seviye_yok"),
        ({"bar_open_time_ms": int(time.time() * 1000) - 4 * 3_600_000}, "eski_sinyal"),
        ({"market": Market.SPOT}, "piyasa"),
        ({"symbol": "XYZUSDT"}, "test_ağında_yok"),
    ],
)
async def test_unsuitable_signals_are_skipped(
    service: tuple[ExecutionService, list[TradingMode]],
    exchange: FakeExchange,
    change: dict[str, Any],
    reason: str,
) -> None:
    svc, mode = service
    auto = trader(svc, mode)
    await auto.on_opportunity(signal(**change))
    assert auto.skipped[reason] == 1 and auto.stats["opened"] == 0
    assert exchange.futures_positions == {}


async def test_disabled_or_wrong_mode_never_trades(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    off = AutoTrader(
        settings=AutoTradeSettings(),  # varsayılan kapalı
        limits=svc.settings.risk,
        service=svc,
        trading_mode=lambda: mode[0],
    )
    await off.on_opportunity(signal())
    assert off.skipped["kapalı"] == 1
    mode[0] = TradingMode.PAPER
    auto = trader(svc, mode)
    await auto.on_opportunity(signal())
    assert auto.skipped["mod_testnet_değil"] == 1
    assert exchange.futures_positions == {}


async def test_hourly_entry_limit(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    auto = trader(svc, mode, max_entries_per_hour=1)
    await auto.on_opportunity(signal())
    await auto.on_opportunity(signal(symbol="ETHUSDT", price=4000.0, stop_price=3920.0))
    assert auto.stats["opened"] == 1 and auto.skipped["saatlik_sınır"] == 1


async def test_gate_rejection_is_reported_not_retried(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    await svc.monitor.refresh()
    await svc.monitor.halt_day("test: günlük zarar")
    auto = trader(svc, mode)
    await auto.on_opportunity(signal())
    assert auto.stats["rejected"] == 1 and exchange.futures_positions == {}
    (entry,) = auto.status()["recent"]
    assert entry["result"] == "rejected" and "daily_halt" in entry["reasons"]
    assert "garanti değildir" in auto.status()["disclaimer"]


async def test_trailing_runner_takes_half_at_1r_and_trails_the_rest(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    auto = trader(svc, mode)  # varsayılan: iz süren stop açık (Futures)
    await auto.on_opportunity(signal())
    assert auto.stats["opened"] == 1, auto.status()
    algos = active_algos(exchange)
    assert ("STOP_MARKET", "98", "0") in algos
    assert ("TAKE_PROFIT_MARKET", "102", "58.139") in algos  # yarısı 1R'de
    assert not any(a[0] == "TAKE_PROFIT_MARKET" and a[1] == "104" for a in algos)
    trailing = [r[2] for r in exchange.requests
                if r[1] == "/fapi/v1/algoOrder" and r[2].get("type") == "TRAILING_STOP_MARKET"]  # fmt: skip
    assert len(trailing) == 1
    assert D(trailing[0]["callbackRate"]) == D("2.0")  # geri çekilme payı = 1R uzaklığı (%2)
    assert D(trailing[0]["activatePrice"]) == D(102)  # 1R'de devreye girer


def notice(action: str, pnl: str | None = None, symbol: str = "BTCUSDT") -> TradeNotice:
    return TradeNotice(market="usdm_futures", mode="testnet", symbol=symbol, action=action,
                       side="long", quantity="1", price="100", net_pnl=pnl)  # fmt: skip


async def test_loss_streak_pauses_new_entries(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    clock = [int(time.time() * 1000)]
    auto = AutoTrader(
        settings=AutoTradeSettings(enabled=True, max_consecutive_losses=2, loss_pause_minutes=60,
                                   symbol_cooldown_s=0),
        limits=svc.settings.risk,
        service=svc,
        trading_mode=lambda: mode[0],
        clock=lambda: clock[0],
    )  # fmt: skip
    # Botun açmadığı pozisyonların sonucu sayılmaz.
    await auto.on_trade_notice(notice("closed", "-5", symbol="ETHUSDT"))
    assert auto.loss_streak == 0
    for pnl in ("-3", "-4"):
        auto._open_pnl[("usdm_futures", "BTCUSDT")] = D(0)
        await auto.on_trade_notice(notice("closed", pnl))
    assert auto.loss_streak == 2 and auto.paused_until_ms == clock[0] + 3_600_000
    await auto.on_opportunity(signal(bar_open_time_ms=clock[0] - 3_600_000))
    assert auto.skipped["kayıp_serisi_molası"] == 1 and auto.stats["opened"] == 0
    assert auto.status()["loss_streak"] == 2 and auto.status()["results"]["losses"] == 2
    # Mola bitince seri sıfırlanır ve bot yeniden girebilir.
    clock[0] += 3_600_001
    await auto.on_opportunity(signal(bar_open_time_ms=clock[0] - 3_600_000))
    assert auto.stats["opened"] == 1 and auto.loss_streak == 0 and auto.paused_until_ms is None


async def test_partial_close_is_summed_until_position_closes(
    service: tuple[ExecutionService, list[TradingMode]], exchange: FakeExchange
) -> None:
    svc, mode = service
    auto = trader(svc, mode)
    await auto.on_opportunity(signal())
    assert ("usdm_futures", "BTCUSDT") in auto._open_pnl
    # İlk hedef kârla (pozisyon sürüyor) → sonuç henüz sayılmaz.
    await auto.on_trade_notice(notice("closed", "10"))
    assert auto.results == {"wins": 0, "losses": 0}
    # Kalan kısım girişte (komisyonla hafif eksi) kapanır: toplam artı → kazanç.
    exchange.futures_positions.pop("BTCUSDT", None)
    svc.markets[Market.USDM_FUTURES].engine.positions.positions.pop("BTCUSDT", None)
    await auto.on_trade_notice(notice("closed", "-0.5"))
    assert auto.results == {"wins": 1, "losses": 0} and auto.loss_streak == 0
