"""Özellik motoru, Futures bağlam verisi, veri kümesi, yürüyen pencere eğitimi ve ONNX kayıt
defteri: ileriye bakmama, sızıntısız bölme, öğrenilebilir/öğrenilemez sinyal ve dışa aktarım
eşleşmesi."""

from __future__ import annotations

import asyncio
import io
import json
import math
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from ati_engine.analysis.features import (
    ALL_FEATURES,
    BASE_FEATURES,
    FUTURES_FEATURES,
    WARMUP_BARS,
    Bar,
    FeatureEngine,
    FuturesContext,
)
from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.history.futures_data import FuturesDataSync, parse_funding, parse_metrics
from ati_engine.history.store import KlineStore
from ati_engine.ml.dataset import build_dataset
from ati_engine.ml.registry import ModelError, ModelRegistry
from ati_engine.ml.train import auc, train_model, walk_forward_splits
from ati_engine.storage.database import Database
from test_history import BASE, LISTING, FakeArchive

HOUR = 3_600_000
FIXTURE = Path(__file__).parent / "fixtures" / "binance" / "spot_btcusdt_1h_1500.json"


def real_rows() -> list[list[float]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [list(r) for r in data["rows"]]


def synthetic_rows(n: int, *, seed: int, signal: bool) -> list[tuple[Any, ...]]:
    """Rastgele yürüyüş. ``signal=True`` ise agresif alış oranı bir sonraki 4 saatin yönünü
    önceden belli eder (öğrenilebilir ilişki); aksi halde tamamen rastgele."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0, 0.01, n + 8)
    rows = []
    price = 100.0
    for i in range(n):
        future = shocks[i + 1 : i + 5].sum()
        ratio = 0.5 + (0.3 * np.tanh(future * 50) if signal else rng.uniform(-0.3, 0.3))
        open_ = price
        price *= math.exp(shocks[i])
        high = max(open_, price) * 1.002
        low = min(open_, price) * 0.998
        volume = float(rng.uniform(50, 150))
        quote = volume * price
        rows.append((i * HOUR, open_, high, low, price, volume, quote, quote * ratio))
    return rows


# --- Özellik motoru ----------------------------------------------------------------------------


def test_features_warmup_and_contract() -> None:
    engine = FeatureEngine()
    outputs = []
    for r in real_rows()[:400]:
        bar = Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7])
        outputs.append(engine.update(bar))
    assert all(o is None for o in outputs[: WARMUP_BARS - 1])
    last = outputs[-1]
    assert last is not None
    assert tuple(last) == ALL_FEATURES
    for name in BASE_FEATURES:
        assert math.isfinite(last[name]), name
    for name in FUTURES_FEATURES:
        assert math.isnan(last[name])  # bağlam verilmedi
    assert 0 <= last["rsi_14"] <= 1
    assert 0 <= last["taker_buy_ratio"] <= 1


def test_futures_features() -> None:
    engine = FeatureEngine()
    rows = real_rows()[:300]
    result = None
    for i, r in enumerate(rows):
        ctx = FuturesContext(
            funding_rate=0.0001,
            open_interest_usd=1e9 * (1 + i / 1000),
            top_long_short=2.0,
            global_long_short=1.0,
            taker_long_short=1.0,
        )
        result = engine.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]), ctx)
    assert result is not None
    assert result["funding_rate_bps"] == pytest.approx(1.0)
    assert result["oi_change_4"] == pytest.approx(math.log((1 + 299 / 1000) / (1 + 295 / 1000)))
    assert result["top_minus_global_log"] == pytest.approx(math.log(2.0))
    assert result["taker_long_short_log"] == pytest.approx(0.0)


def test_features_never_look_ahead() -> None:
    rows = real_rows()
    altered = [list(r) for r in rows]
    cut = 900
    rng = np.random.default_rng(4)
    for r in altered[cut:]:
        factor = float(1 + rng.normal(0, 0.03))
        r[1] *= factor
        r[2] *= factor * 1.01
        r[3] *= factor * 0.99
        r[4] *= factor
        r[5] *= 2

    def run(data: list[list[float]]) -> list[dict[str, float] | None]:
        engine = FeatureEngine()
        return [
            engine.update(Bar(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7])) for r in data
        ]

    a, b = run(rows), run(altered)
    assert json.dumps(a[:cut]) == json.dumps(b[:cut])  # nan dahil birebir
    assert json.dumps(a[cut:]) != json.dumps(b[cut:])


# --- Futures bağlam verisi -------------------------------------------------------------------


def zipped(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    return buffer.getvalue()


METRICS_HEADER = (
    "create_time,symbol,sum_open_interest,sum_open_interest_value,"
    "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,"
    "sum_taker_long_short_vol_ratio"
)


def test_parse_real_metrics_and_funding_lines() -> None:
    metrics = parse_metrics(
        zipped(
            METRICS_HEADER + "\n2026-11-05 00:10:00,BTCUSDT,96194.6290000000000000,"
            "7759010677.8255000000000000,1.48113767,1.91209800,1.39605885,1.44614400\n"
            "2026-11-05 00:15:00,BTCUSDT,1,2,,3,4,5\n"
        )
    )
    assert metrics[0] == (
        1793837400000,
        7759010677.8255,
        1.48113767,
        1.912098,
        1.39605885,
        1.446144,
    )
    assert metrics[1][2] is None  # boş alan
    funding = parse_funding(
        zipped("calc_time,funding_interval_hours,last_funding_rate\n1790812800001,8,0.00007981\n")
    )
    assert funding == [(1790812800001, 0.00007981, 8)]


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(tmp_path / "engine.db")
    await database.open()
    await database.migrate()
    yield database
    await database.close()


async def test_futures_context_asof_join_without_look_ahead(tmp_path: Path, db: Database) -> None:
    store = KlineStore(tmp_path / "h.duckdb")
    fake = FakeArchive()
    day0 = 1_793_836_800_000  # 2026-11-05 00:00
    lines = [METRICS_HEADER]
    for k in range(288):
        stamp = day0 + k * 300_000
        text = np.datetime64(stamp, "ms").astype("datetime64[s]").astype(str).replace("T", " ")
        lines.append(f"{text},BTCUSDT,1,{1000 + k},1,{1 + k / 100},1,1")
    key = "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-11-05.zip"
    fake.add(key, zipped("\n".join(lines) + "\n"))
    fkey = "data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-11.zip"
    fake.add(
        fkey,
        zipped(
            f"calc_time,funding_interval_hours,last_funding_rate\n{day0},8,0.0001\n"
            f"{day0 + 8 * HOUR},8,0.0003\n"
        ),
    )
    archive = fake.client()
    sync = FuturesDataSync(archive, store, db)
    report = await sync.sync("BTCUSDT")
    assert report.metrics_rows == 288 and report.funding_rows == 2
    # Mumlar: 2026-11-05 00:00'dan 1 saatlik, 26 saat (son 2 saatte metrik yok → bayat).
    rows = [
        (day0 + h * HOUR, 1.0, 1.0, 1.0, 1.0, 1.0, day0 + h * HOUR + HOUR - 1, 1.0, 1, 0.5, 0.5)
        for h in range(26)
    ]
    await store.insert("usdm_futures", "BTCUSDT", "1h", rows)
    joined = await store.bars_with_futures("BTCUSDT", "1h")
    assert len(joined) == 26
    # 00:00 mumu 00:59:59.999'da kapanır: o anda bilinen son metrik 00:55 kaydıdır (k=11),
    # 01:00 kaydı (gelecek) kullanılmaz.
    assert joined[0][9] == pytest.approx(1011)
    assert joined[0][8] == pytest.approx(0.0001)
    assert joined[8][8] == pytest.approx(0.0003)  # 08:00 funding'i 08:59 kapanışında bilinir
    assert joined[23][9] == pytest.approx(1287)
    assert joined[24][9] is None and joined[25][9] is None  # 15 dakikadan eski → kullanılmaz
    # Funding kaydı en fazla 9 saat geçerli: 08:00 kaydı 16:59 kapanışında hâlâ geçerli,
    # 17:59 kapanışında (9 saati aştı) kullanılmaz.
    assert joined[16][8] == pytest.approx(0.0003)
    assert joined[17][8] is None
    again = await sync.sync("BTCUSDT")
    assert again.metrics_files == 0 and again.funding_files == 1  # ay sürüyor: tekrar bakılır
    # Daha geriden başlayan yeni istek: önceki gün arşive eklenmiş → geriye doğru tamamlanır.
    prev_lines = [METRICS_HEADER, "2026-11-04 23:55:00,BTCUSDT,1,999,1,1,1,1"]
    fake.add(
        "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-11-04.zip",
        zipped("\n".join(prev_lines) + "\n"),
    )
    back = await sync.sync("BTCUSDT", since_ms=day0 - 86_400_000)
    assert back.metrics_files == 1 and back.metrics_rows == 1
    await archive.close()
    await store.close()


# --- Bölme ve metrikler ------------------------------------------------------------------------


def test_walk_forward_splits_are_ordered_with_embargo() -> None:
    times = np.arange(10_000, dtype=np.int64) * HOUR
    splits = walk_forward_splits(times, folds=4, embargo_ms=5 * HOUR)
    assert len(splits) == 4
    previous_end = -1
    for train, test in splits:
        assert times[train].max() + 5 * HOUR < times[test].min()  # ambargo
        assert times[test].min() > previous_end  # test dönemleri çakışmaz, ileri gider
        previous_end = int(times[test].max())


def test_auc_matches_definition() -> None:
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    p = rng.random(500)
    pairs = [(a, b) for a in p[y == 1] for b in p[y == 0]]
    expected = np.mean([1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs])
    assert auc(y, p) == pytest.approx(expected)
    assert auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])) == 1.0


# --- Eğitim: öğrenilebilir ve öğrenilemez veri ------------------------------------------------


def dataset_from(rows: list[tuple[Any, ...]]) -> Any:
    return build_dataset({"SYNUSDT": rows}, interval="1h", horizon=4, futures=False)


def test_dataset_labels_respect_gaps() -> None:
    rows = synthetic_rows(600, seed=1, signal=False)
    gap = [*rows[:400], *[(r[0] + 10 * HOUR, *r[1:]) for r in rows[400:]]]
    data = dataset_from(gap)
    fwd = dict(zip(data.times.tolist(), data.forward_return.tolist(), strict=True))
    t_before_gap = rows[397][0]  # 397+4 = 401 boşluğun ötesinde → etiket yok
    assert math.isnan(fwd[t_before_gap])
    t_ok = rows[395][0]
    assert fwd[t_ok] == pytest.approx(math.log(rows[399][4] / rows[395][4]))
    assert math.isnan(data.forward_return[-1])


def test_model_learns_real_signal_out_of_sample() -> None:
    data = dataset_from(synthetic_rows(9_000, seed=2, signal=True))
    _, report = train_model(data, side="long", cost=0.005, folds=3)
    assert report.oos["auc"] > 0.7
    assert report.oos["top_decile_net_return_pct"] > 0
    assert next(iter(report.feature_importance)) in {"taker_buy_ratio", "taker_buy_ratio_24"}


def test_model_finds_nothing_in_noise() -> None:
    """Bilgi yoksa örneklem dışı AUC ~0,5 kalmalı (sızıntı olsaydı yüksek çıkardı)."""
    data = dataset_from(synthetic_rows(9_000, seed=3, signal=False))
    _, report = train_model(data, side="long", cost=0.005, folds=3)
    assert 0.45 < report.oos["auc"] < 0.56


# --- Kayıt defteri ve ONNX ---------------------------------------------------------------------


def test_registry_onnx_parity_and_tamper_detection(tmp_path: Path) -> None:
    data = dataset_from(synthetic_rows(6_000, seed=5, signal=True))
    booster, report = train_model(data, side="short", cost=0.005, folds=2)
    registry = ModelRegistry(tmp_path / "models")
    labeled = data.labeled()
    sample = labeled.X.copy()
    sample[::7, 3] = np.nan  # eksik değerler de aynı işlenmeli
    meta = registry.save(
        booster,
        report,
        market="spot",
        symbols=["SYNUSDT"],
        interval="1h",
        horizon=4,
        feature_names=data.feature_names,
        train_start_ms=int(labeled.times.min()),
        train_end_ms=int(labeled.times.max()),
        parity_sample=sample,
    )
    assert meta.parity_max_abs_diff < 1e-4
    predictor = registry.load(meta.id)
    np.testing.assert_allclose(
        predictor.predict(sample[:500]), booster.predict(sample[:500]), atol=1e-4
    )
    assert [m.id for m in registry.list()] == [meta.id]
    onnx_path = tmp_path / "models" / meta.id / "model.onnx"
    raw = bytearray(onnx_path.read_bytes())
    raw[-10] ^= 0xFF
    onnx_path.write_bytes(bytes(raw))
    with pytest.raises(ModelError, match="SHA-256"):
        registry.load(meta.id)
    with pytest.raises(ModelError, match="Geçersiz"):
        registry.load("../etc")


# --- API ---------------------------------------------------------------------------------------


async def test_analysis_api_end_to_end(tmp_path: Path) -> None:
    settings = EngineSettings(
        data_dir=tmp_path / "data", log_to_console=False, api=LocalApiSettings(port=0)
    )
    engine = Engine(settings)
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=10)
    runtime = engine.runtime
    assert runtime is not None and runtime.history is not None and runtime.analysis is not None
    try:
        # Sahte arşiv: sentetik (öğrenilebilir) 1 saatlik veri günlük dosyalar halinde.
        from ati_engine.history.sync import HistorySync

        fake = FakeArchive()
        rows = synthetic_rows(24 * 220, seed=8, signal=True)
        base = 1_775_000_000_000 - 1_775_000_000_000 % 86_400_000
        prefix = "data/spot/daily/klines/SYNUSDT/1h/"
        for d in range(220):
            day_rows = rows[d * 24 : (d + 1) * 24]
            stamp = base + d * 86_400_000
            period = str(np.datetime64(stamp, "ms").astype("datetime64[D]"))
            lines = [
                f"{stamp + i * HOUR},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},{stamp + i * HOUR + HOUR - 1},"
                f"{r[6]},10,{r[7] / r[4]},{r[7]},0"
                for i, r in enumerate(day_rows)
            ]
            fake.add(f"{prefix}SYNUSDT-1h-{period}.zip", zipped("\n".join(lines) + "\n"))
        history = runtime.history
        await history.archive.close()
        history.archive = fake.client()
        history.sync = HistorySync(history.archive, history.store, runtime.db)
        headers = {"Authorization": f"Bearer {runtime.api_token}"}
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{engine.bound_port}", headers=headers
        ) as client:
            accepted = await client.post(
                "/v1/analysis/train",
                json={"market": "spot", "symbols": ["synusdt"], "interval": "1h", "horizon": 4},
            )
            assert accepted.status_code == 202, accepted.text
            job = accepted.json()
            for _ in range(600):
                jobs = (await client.get("/v1/analysis/jobs")).json()
                job = jobs[0]
                if job["state"] != "running":
                    break
                await asyncio.sleep(0.1)
            assert job["state"] == "done", job
            assert job["oos"]["auc"] > 0.6
            models = (await client.get("/v1/analysis/models")).json()
            assert models[0]["id"] == job["model_id"]
            assert "garanti etmez" in models[0]["disclaimer"]
            prediction = await client.get(
                "/v1/analysis/predict", params={"model_id": job["model_id"], "symbol": "SYNUSDT"}
            )
            assert prediction.status_code == 200, prediction.text
            assert 0 <= prediction.json()["probability"] <= 1
            snapshot = (
                await client.get("/v1/analysis/snapshot", params={"symbol": "SYNUSDT"})
            ).json()
            assert snapshot["indicators"]["rsi_14"] is not None
            assert snapshot["features"]["funding_rate_bps"] is None
            missing = await client.get(
                "/v1/analysis/predict", params={"model_id": "yok", "symbol": "SYNUSDT"}
            )
            assert missing.status_code == 404
            bad = await client.post(
                "/v1/analysis/train",
                json={"market": "spot", "symbols": ["SYNUSDT"], "with_futures": True},
            )
            assert bad.status_code == 422
    finally:
        runtime.request_shutdown()
        assert await asyncio.wait_for(task, timeout=15) == 0


_ = (BASE, LISTING)  # paylaşılan sahte arşiv sabitleri
