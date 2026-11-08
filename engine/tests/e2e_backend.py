"""Masaüstü arayüzünün uçtan uca testleri için arka uç (Playwright ``webServer`` olarak çalışır).

Gerçek motor; piyasa verisi sahte Binance yayın sunucusundan, test ağı işlemleri 2026 kurallarını
taklit eden sahte borsadan gelir. Hiçbir gerçek Binance adresine bağlanılmaz.

Kullanım::

    uv run python tests/e2e_backend.py --port 47999 --token e2e-belirtec --origin http://127.0.0.1:4173

SIGTERM/SIGINT ile düzgün kapanır.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from ati_engine.app import TOKEN_ENV, Engine
from ati_engine.config import (
    BinanceEndpoints,
    EngineSettings,
    HistorySettings,
    LocalApiSettings,
    MarketDataSettings,
)
from fake_binance import FakeBinance
from fake_exchange import FakeExchange

E2E_API_KEY = "E2eTestAnahtar0123456789abcdef"
E2E_SECRET = "E2eTestGizli0123456789abcdefXYZ"


async def main(args: argparse.Namespace) -> int:
    os.environ[TOKEN_ENV] = args.token
    market = await FakeBinance(interval_s=0.2).start()
    exchange = await FakeExchange(api_key=E2E_API_KEY, secret=E2E_SECRET).start()
    exchange.prices.update({"BTCUSDT": Decimal(100), "ETHUSDT": Decimal(50)})
    with tempfile.TemporaryDirectory(prefix="ati-e2e-") as tmp:
        settings = EngineSettings(
            data_dir=Path(tmp) / "data",
            log_to_console=False,
            api=LocalApiSettings(port=args.port, allowed_origins=args.origin),
            binance=BinanceEndpoints(
                **market.binance_endpoints(),
                futures_testnet_rest=exchange.rest_url,
                futures_testnet_ws_private=exchange.private_ws_url,
                spot_testnet_rest=exchange.rest_url,
                spot_testnet_ws_api=exchange.ws_api_url,
            ),
            market_data=MarketDataSettings(
                enabled=True,
                symbol_allowlist=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                focus_symbols=["BTCUSDT"],
                depth_snapshot_limit=100,
            ),
            history=HistorySettings(enabled=False),
        )
        engine = Engine(settings)
        task = asyncio.create_task(engine.run())
        await asyncio.wait_for(engine.ready.wait(), timeout=60)
        print(f"E2E arka ucu hazır: http://127.0.0.1:{engine.bound_port}", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        await asyncio.wait(
            {asyncio.create_task(stop.wait()), task}, return_when=asyncio.FIRST_COMPLETED
        )
        if engine.runtime is not None:
            engine.runtime.request_shutdown()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=15)
    await exchange.stop()
    await market.stop()
    return 0


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=47999)
    parser.add_argument("--token", default="e2e-belirtec-0123456789")
    parser.add_argument("--origin", action="append", default=["http://127.0.0.1:4173"])
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse())))
