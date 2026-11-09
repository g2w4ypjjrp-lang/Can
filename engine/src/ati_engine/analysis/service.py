"""Analiz servisi: güncel gösterge/özellik dökümü, arka planda model eğitimi ve tahmin.

Eğitim kullanıcının bilgisayarında, işlem motorunu yavaşlatmadan ayrı bir iş parçacığında
yapılır (LightGBM çekirdeklerin yarısını kullanır). Aynı anda tek eğitim çalışır.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ati_engine.analysis.features import ALL_FEATURES, BASE_FEATURES, FeatureEngine
from ati_engine.core.models import Market
from ati_engine.history.archive import INTERVAL_MS
from ati_engine.history.futures_data import FuturesDataSync
from ati_engine.history.service import HistoryService
from ati_engine.ml.dataset import _bar, build_dataset, symbol_features
from ati_engine.ml.registry import ModelMeta, ModelRegistry
from ati_engine.ml.train import train_model

logger = logging.getLogger(__name__)

# Varsayılan gidiş-dönüş maliyetleri (log getiri): alıcı (taker) komisyonu iki kez + pay.
DEFAULT_COST = {Market.SPOT: 0.0025, Market.USDM_FUTURES: 0.0012}


@dataclass
class TrainJob:
    id: int
    market: Market
    symbols: list[str]
    interval: str
    horizon: int
    side: str
    with_futures: bool
    state: str = "running"
    started_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_ms: int | None = None
    stage: str = "veri eşitleniyor"
    model_id: str | None = None
    oos: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class AnalysisService:
    def __init__(self, history: HistoryService, registry: ModelRegistry) -> None:
        self.history = history
        self.registry = registry
        self.futures_sync = FuturesDataSync(history.archive, history.store, history.sync.db)
        self.jobs: dict[int, TrainJob] = {}
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    # --- Güncel gösterge dökümü ----------------------------------------------------------

    async def snapshot(self, market: Market, symbol: str, interval: str) -> dict[str, Any]:
        """Depodaki son mumlarla göstergeler ve model özellikleri (son kapanmış mum)."""
        rows = await self.history.bars(market, symbol, interval, tail=600)
        if len(rows) < 260:
            raise ValueError("Yeterli tarihsel veri yok; önce eşitleyin (en az 260 mum)")
        engine = FeatureEngine()
        features: dict[str, float] | None = None
        for row in rows:
            features = engine.update(_bar(_with_quote(row)))
        if features is None:
            raise ValueError("Göstergeler ısınmadı")
        last = rows[-1]
        macd = engine.macd.value
        bb = engine.bb.value
        stoch = engine.stoch.value
        ichi = engine.ichimoku.value
        fib = engine.fib.value
        indicators = {
            "close": float(last[4]),
            "ema_9": engine.ema9.value,
            "ema_21": engine.ema21.value,
            "ema_50": engine.ema50.value,
            "ema_200": engine.ema200.value,
            "rsi_14": engine.rsi.value,
            "macd": macd.macd if macd else None,
            "macd_signal": macd.signal if macd else None,
            "macd_hist": macd.hist if macd else None,
            "atr_14": engine.atr.value,
            "bb_upper": bb.upper if bb else None,
            "bb_middle": bb.middle if bb else None,
            "bb_lower": bb.lower if bb else None,
            "stoch_rsi_k": stoch.k if stoch else None,
            "stoch_rsi_d": stoch.d if stoch else None,
            "obv": engine.obv.value,
            "vwap": engine.vwap.value,
            "ichimoku_tenkan": ichi.tenkan if ichi else None,
            "ichimoku_kijun": ichi.kijun if ichi else None,
            "ichimoku_span_a": ichi.span_a if ichi else None,
            "ichimoku_span_b": ichi.span_b if ichi else None,
            "fib_swing_high": fib.swing_high if fib else None,
            "fib_swing_low": fib.swing_low if fib else None,
            "fib_levels": {str(k): v for k, v in fib.levels.items()} if fib else None,
        }
        return {
            "market": market.value,
            "symbol": symbol.upper(),
            "interval": interval,
            "bar_open_time_ms": int(last[0]),
            "indicators": indicators,
            "features": {k: (None if v != v else v) for k, v in features.items()},  # nan→None
        }

    # --- Eğitim ----------------------------------------------------------------------------

    def start_training(
        self,
        market: Market,
        symbols: Sequence[str],
        interval: str,
        *,
        horizon: int,
        side: str,
        with_futures: bool = False,
        since_ms: int | None = None,
        cost: float | None = None,
    ) -> TrainJob:
        if interval not in INTERVAL_MS:
            raise ValueError(f"Desteklenmeyen aralık: {interval}")
        if side not in {"long", "short"}:
            raise ValueError("side: long | short")
        if with_futures and market is not Market.USDM_FUTURES:
            raise ValueError("Futures özellikleri yalnızca usdm_futures piyasasında")
        if not 1 <= horizon <= 500:
            raise ValueError("horizon 1-500 arası olmalı")
        job = TrainJob(
            id=next(self._ids),
            market=market,
            symbols=[s.upper() for s in symbols],
            interval=interval,
            horizon=horizon,
            side=side,
            with_futures=with_futures,
        )
        self.jobs[job.id] = job
        task = asyncio.create_task(
            self._train(job, since_ms, DEFAULT_COST[market] if cost is None else cost),
            name=f"train-{job.id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _train(self, job: TrainJob, since_ms: int | None, cost: float) -> None:
        try:
            async with self._lock:
                per_symbol: dict[str, list[tuple[Any, ...]]] = {}
                for symbol in job.symbols:
                    job.stage = f"veri eşitleniyor: {symbol}"
                    await self.history.sync.sync_klines(job.market, symbol, job.interval)
                    if job.with_futures:
                        await self.futures_sync.sync(symbol, since_ms=since_ms)
                        rows = await self.history.store.bars_with_futures(
                            symbol, job.interval, start_ms=since_ms
                        )
                    else:
                        raw = await self.history.store.candles(
                            job.market.value, symbol, job.interval, start_ms=since_ms
                        )
                        rows = [_with_quote(r) for r in raw]
                    per_symbol[symbol] = rows
                job.stage = "özellikler hesaplanıyor"
                data = await asyncio.to_thread(
                    build_dataset,
                    per_symbol,
                    interval=job.interval,
                    horizon=job.horizon,
                    futures=job.with_futures,
                )
                job.stage = "model eğitiliyor (yürüyen pencere)"
                booster, report = await asyncio.to_thread(
                    train_model,
                    data,
                    side="long" if job.side == "long" else "short",
                    cost=cost,
                )
                job.stage = "ONNX dışa aktarma ve doğrulama"
                labeled = data.labeled()
                meta = await asyncio.to_thread(
                    self.registry.save,
                    booster,
                    report,
                    market=job.market.value,
                    symbols=job.symbols,
                    interval=job.interval,
                    horizon=job.horizon,
                    feature_names=data.feature_names,
                    train_start_ms=int(labeled.times.min()),
                    train_end_ms=int(labeled.times.max()),
                    parity_sample=labeled.X[-5000:],
                )
                job.model_id = meta.id
                job.oos = {k: v for k, v in report.oos.items() if k != "calibration"}
                job.state = "done"
                job.stage = "tamamlandı"
        except asyncio.CancelledError:
            job.state, job.error = "failed", "iptal edildi"
            raise
        except Exception as exc:
            job.state = "failed"
            job.error = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Model eğitimi başarısız", extra={"error": job.error})
        finally:
            job.finished_ms = int(time.time() * 1000)

    # --- Tahmin ----------------------------------------------------------------------------

    async def predict(self, model_id: str, symbol: str) -> dict[str, Any]:
        predictor = await asyncio.to_thread(self.registry.load, model_id)
        meta: ModelMeta = predictor.meta
        market = Market(meta.market)
        futures = tuple(meta.feature_names) == ALL_FEATURES
        if tuple(meta.feature_names) not in (ALL_FEATURES, BASE_FEATURES):
            raise ValueError("Modelin özellik listesi bu sürümle uyumsuz")
        if futures:
            rows = await self.history.store.bars_with_futures(symbol.upper(), meta.interval)
            rows = rows[-800:]
        else:
            raw = await self.history.bars(market, symbol, meta.interval, tail=800)
            rows = [_with_quote(r) for r in raw]
        times, vectors, _ = symbol_features(rows, futures=futures, names=tuple(meta.feature_names))
        if not vectors:
            raise ValueError("Yeterli tarihsel veri yok; önce eşitleyin")
        x = np.asarray(vectors[-1:], dtype=np.float32)
        probability = float(predictor.predict(x)[0])
        missing = [n for n, v in zip(meta.feature_names, vectors[-1], strict=True) if v != v]
        return {
            "model_id": meta.id,
            "symbol": symbol.upper(),
            "interval": meta.interval,
            "side": meta.side,
            "horizon_bars": meta.horizon,
            "bar_open_time_ms": times[-1],
            "probability": round(probability, 4),
            "base_rate": meta.report.get("oos", {}).get("base_rate"),
            "oos_auc": meta.report.get("oos", {}).get("auc"),
            "missing_features": missing,
            "disclaimer": meta.disclaimer,
        }

    def models(self) -> list[dict[str, Any]]:
        result = []
        for meta in self.registry.list():
            data = asdict(meta)
            report = data.pop("report", {})
            data["oos"] = {k: v for k, v in report.get("oos", {}).items() if k != "calibration"}
            data["calibration"] = report.get("oos", {}).get("calibration", [])
            data["top_features"] = dict(list(report.get("feature_importance", {}).items())[:10])
            result.append(data)
        return result

    async def wait(self) -> None:
        """Çalışan eğitimlerin bitmesini bekler (komut satırı kullanımı)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            # Bitmiş görevler burada çıkarılır (bkz. TradingEngine.settle: gather dönmeyebilir).
            self._tasks.difference_update([t for t in self._tasks if t.done()])

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def _with_quote(row: Sequence[Any]) -> tuple[Any, ...]:
    """``KlineStore.candles`` (11 sütun) veya ``resample`` (9 sütun) satırını özellik motorunun
    beklediği (zaman, açılış, en yüksek, en düşük, kapanış, hacim, kote hacim, agresif alış kote
    hacmi) biçimine getirir."""
    if len(row) >= 11:
        return (row[0], row[1], row[2], row[3], row[4], row[5], row[7], row[10])
    return (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[8])
