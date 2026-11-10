"""Komut satırı girişi.

Kullanım::

    ati-engine run                     # motoru başlat (varsayılan)
    ati-engine show-config             # etkin ayarları göster (gizli bilgi içermez)
    ati-engine export-protocol-schema  # paylaşılan protokol şemasını yazdır
    ati-engine verify-audit            # yerel denetim kaydı zincirini doğrula
    ati-engine history-sync --symbol BTCUSDT --market spot --interval 1m
                                       # Binance arşivinden tarihsel mumları indir/güncelle
    ati-engine history-replay --symbol BTCUSDT --days 30
                                       # balina radarını işlem arşivi üzerinde yeniden oynat
    ati-engine model-train --symbol BTCUSDT ETHUSDT --interval 1h --horizon 4 --side long
                                       # yürüyen pencereyle model eğit, ONNX olarak kaydet
    ati-engine score-calibrate --symbol BTCUSDT ETHUSDT
                                       # fırsat puanının geçmişteki maliyet sonrası sonucu
    ati-engine backtest --symbol BTCUSDT ETHUSDT --since 2021-01-01
                                       # tüm stratejiler + yürüyen pencere, kayıt defterine yaz
    ati-engine version
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ati_engine import __version__


def _cmd_run(args: argparse.Namespace) -> int:
    from ati_engine.app import Engine
    from ati_engine.config import EngineSettings
    from ati_engine.system.single_instance import AlreadyRunningError

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    if args.port is not None:
        settings.api.port = args.port
    try:
        return asyncio.run(Engine(settings).run())
    except AlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _cmd_show_config(args: argparse.Namespace) -> int:
    from ati_engine.config import EngineSettings, redacted_settings_dump

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    print(json.dumps(redacted_settings_dump(settings), indent=2, ensure_ascii=False))
    return 0


def _cmd_export_schema(args: argparse.Namespace) -> int:
    from ati_engine.protocol import build_protocol_schema

    text = json.dumps(build_protocol_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_verify_audit(args: argparse.Namespace) -> int:
    from ati_engine.config import EngineSettings
    from ati_engine.storage.audit import AuditLog
    from ati_engine.storage.database import Database

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]

    async def _verify() -> int:
        db = Database(settings.paths.database)
        await db.open()
        try:
            await db.migrate()
            result = await AuditLog(db).verify()
        finally:
            await db.close()
        if result.ok:
            print(f"Denetim kaydı sağlam ({result.checked} kayıt).")
            return 0
        print(
            f"Denetim kaydı zinciri {result.broken_at_id} numaralı kayıtta kırık!", file=sys.stderr
        )
        return 3

    return asyncio.run(_verify())


def _settings_for(args: argparse.Namespace) -> Any:
    from ati_engine.config import EngineSettings

    overrides: dict[str, object] = {}
    if getattr(args, "data_dir", None):
        overrides["data_dir"] = Path(args.data_dir)
    return EngineSettings(**overrides)  # type: ignore[arg-type]


def _cmd_backup(args: argparse.Namespace) -> int:
    """Motor veritabanının tutarlı yedeği (motor çalışırken de alınabilir)."""
    import time as _time

    from ati_engine.storage.audit import AuditLog
    from ati_engine.storage.database import Database

    settings = _settings_for(args)
    source = Path(settings.paths.database)
    if not source.exists():
        print(f"Veritabanı bulunamadı: {source}", file=sys.stderr)
        return 2
    folder = Path(args.output_dir) if args.output_dir else source.parent / "backups"
    target = folder / f"engine-{_time.strftime('%Y%m%d-%H%M%S')}.db"

    async def _backup() -> int:
        db = Database(source)
        await db.open()
        try:
            size = await db.backup(target)
        finally:
            await db.close()
        copy = Database(target)
        await copy.open()
        try:
            audit = await AuditLog(copy).verify()
        finally:
            await copy.close()
        if not audit.ok:
            print(f"Yedekteki denetim zinciri kırık ({audit.broken_at_id})", file=sys.stderr)
            return 3
        old = sorted(folder.glob("engine-*.db"))[: -args.keep] if args.keep > 0 else []
        for path in old:
            path.unlink(missing_ok=True)
        print(
            f"Yedek: {target} ({size / 2**20:.1f} MB, denetim kaydı {audit.checked} kayıt sağlam)"
        )
        return 0

    return asyncio.run(_backup())


def _cmd_restore(args: argparse.Namespace) -> int:
    """Yedeği geri yükler. Motor çalışıyorsa reddedilir; mevcut veritabanı silinmez, yanına
    taşınır. Şifreli kasa (API anahtarları, uzaktan kontrol ve lisans anahtarları) Windows'ta
    kullanıcıya bağlı DPAPI ile korunur: başka bilgisayarda/kullanıcıda geri yüklenen yedekte bu
    gizli bilgiler çözülemez; yeniden girilmeleri (eşleştirme, lisans etkinleştirme) gerekir."""
    import contextlib
    import shutil
    import sqlite3
    import tempfile
    import time as _time

    from ati_engine.storage.audit import AuditLog
    from ati_engine.storage.database import Database
    from ati_engine.system.single_instance import AlreadyRunningError, SingleInstanceLock

    settings = _settings_for(args)
    backup = Path(args.source)
    if not backup.is_file():
        print(f"Yedek bulunamadı: {backup}", file=sys.stderr)
        return 2
    lock = SingleInstanceLock(settings.paths.lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        print("Motor çalışıyor; geri yüklemeden önce kapatın.", file=sys.stderr)
        return 4
    try:
        with tempfile.TemporaryDirectory(prefix="ati-geri-yukleme-") as tmp:
            # Yedeğin kendisine dokunulmaz: geçici kopyası denetlenir ve o kopya yüklenir.
            candidate = Path(tmp) / "aday.db"
            shutil.copy2(backup, candidate)

            async def _check() -> bool:
                db = Database(candidate)
                try:
                    await db.open()
                    result = await db.fetchone("PRAGMA integrity_check")
                    audit = await AuditLog(db).verify()
                except (sqlite3.DatabaseError, RuntimeError):
                    return False
                finally:
                    with contextlib.suppress(sqlite3.DatabaseError):
                        await db.close()
                return bool(result and result[0] == "ok" and audit.ok)

            if not asyncio.run(_check()):
                print("Yedek bozuk veya denetim zinciri kırık; geri yüklenmedi.", file=sys.stderr)
                return 3
            target = Path(settings.paths.database)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                stamp = _time.strftime("%Y%m%d-%H%M%S")
                kept = target.with_name(f"{target.name}.geri-yukleme-oncesi-{stamp}")
                target.replace(kept)
                print(f"Mevcut veritabanı saklandı: {kept}")
            for suffix in ("-wal", "-shm"):
                Path(str(target) + suffix).unlink(missing_ok=True)
            shutil.copy2(candidate, target)
        print(f"Geri yüklendi: {backup} → {target}")
        return 0
    finally:
        lock.release()


def _cmd_history_sync(args: argparse.Namespace) -> int:
    from ati_engine.config import EngineSettings
    from ati_engine.core.models import Market
    from ati_engine.exchange.endpoints import endpoints_for
    from ati_engine.exchange.rate_limit import WeightBudget
    from ati_engine.exchange.rest import BinanceRestClient
    from ati_engine.history.archive import ArchiveClient
    from ati_engine.history.store import KlineStore
    from ati_engine.history.sync import HistorySync
    from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
    from ati_engine.storage.database import Database

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    settings.paths.ensure()

    async def _sync() -> int:
        import duckdb

        try:
            store = KlineStore(settings.paths.history_db)
        except duckdb.IOException:
            print(
                "Tarihsel veri dosyası kullanımda (motor çalışıyor olabilir). Motor çalışırken "
                "eşitleme için yerel API'yi kullanın: POST /v1/history/sync",
                file=sys.stderr,
            )
            return 4
        db = Database(settings.paths.database)
        await db.open()
        archive = ArchiveClient()
        market = Market(args.market)
        endpoints = endpoints_for(market, settings.binance)
        rest_client = BinanceRestClient(
            endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
        )
        try:
            await db.migrate()
            sync = HistorySync(archive, store, db, rest={market: (rest_client, endpoints)})
            for symbol in args.symbol:
                report = await sync.sync_klines(Market(args.market), symbol, args.interval)
                coverage = await store.coverage(args.market, report.symbol, args.interval)
                print(
                    json.dumps(
                        {
                            "symbol": report.symbol,
                            "files_listed": report.files_listed,
                            "files_downloaded": report.files_downloaded,
                            "files_skipped": report.files_skipped,
                            "rows_inserted": report.rows_inserted,
                            "rest_rows": report.rest_rows,
                            "gaps_checked": report.gaps_checked,
                            "gaps_rows": report.gaps_rows,
                            "mb_downloaded": round(report.bytes_downloaded / 1e6, 2),
                            "seconds": report.seconds,
                            "rows_total": coverage.rows,
                            "first_open_ms": coverage.first_open_ms,
                            "last_open_ms": coverage.last_open_ms,
                            "missing_candles": coverage.missing,
                        },
                        ensure_ascii=False,
                    )
                )
        finally:
            await archive.close()
            await rest_client.close()
            await store.close()
            await db.close()
        return 0

    return asyncio.run(_sync())


def _cmd_history_replay(args: argparse.Namespace) -> int:
    import time
    from dataclasses import asdict
    from datetime import UTC, date, datetime, timedelta

    from ati_engine.config import WhaleSettings
    from ati_engine.core.models import Market
    from ati_engine.history.archive import ArchiveClient, ArchiveNotFound
    from ati_engine.history.replay import WhaleReplay, aggtrades_key, iter_aggtrades

    market = Market(args.market)
    whales = WhaleSettings()
    floor = args.floor or (
        whales.spot_floor_usd if market is Market.SPOT else whales.futures_floor_usd
    )
    end = date.fromisoformat(args.end) if args.end else datetime.now(UTC).date() - timedelta(1)
    days = [end - timedelta(days=i) for i in range(args.days - 1, -1, -1)]

    async def _replay() -> str:
        archive = ArchiveClient()
        replay = WhaleReplay(
            market,
            args.symbol.upper(),
            floor_usd=floor,
            quantile=whales.quantile,
            min_samples=whales.min_samples,
        )
        try:
            for day in days:
                started = time.perf_counter()
                try:
                    data = await archive.download(aggtrades_key(market, args.symbol.upper(), day))
                except ArchiveNotFound:
                    replay.gap(day.isoformat())
                    print(f"{day}: arşivde yok, atlandı", file=sys.stderr)
                    continue
                before = replay.report.trades
                for row in iter_aggtrades(data):
                    replay.feed(*row)
                replay.report.days.append(day.isoformat())
                print(
                    f"{day}: {replay.report.trades - before:,} işlem, toplam balina "
                    f"{replay.report.whales}, {time.perf_counter() - started:.1f} sn",
                    file=sys.stderr,
                )
        finally:
            await archive.close()
        return json.dumps(asdict(replay.finish()), indent=2, ensure_ascii=False)

    text = asyncio.run(_replay())
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    return 0


def _cmd_model_train(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    import duckdb

    from ati_engine.analysis.service import AnalysisService
    from ati_engine.config import EngineSettings
    from ati_engine.core.models import Market
    from ati_engine.exchange.endpoints import endpoints_for
    from ati_engine.exchange.rate_limit import WeightBudget
    from ati_engine.exchange.rest import BinanceRestClient
    from ati_engine.history.service import HistoryService
    from ati_engine.history.store import KlineStore
    from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
    from ati_engine.ml.registry import ModelRegistry
    from ati_engine.storage.database import Database

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    settings.paths.ensure()
    market = Market(args.market)
    since_ms = (
        int(datetime.fromisoformat(args.since).replace(tzinfo=UTC).timestamp() * 1000)
        if args.since
        else None
    )

    async def _train() -> int:
        try:
            store = KlineStore(settings.paths.history_db)
        except duckdb.IOException:
            print(
                "Tarihsel veri dosyası kullanımda (motor çalışıyor olabilir). Motor çalışırken "
                "eğitim için yerel API'yi kullanın: POST /v1/analysis/train",
                file=sys.stderr,
            )
            return 4
        db = Database(settings.paths.database)
        await db.open()
        await db.migrate()
        endpoints = endpoints_for(market, settings.binance)
        rest = BinanceRestClient(
            endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
        )
        history = HistoryService(store, db, rest={market: (rest, endpoints)}, owned_rest=[rest])
        service = AnalysisService(history, ModelRegistry(settings.paths.models_dir))
        try:
            job = service.start_training(
                market,
                args.symbol,
                args.interval,
                horizon=args.horizon,
                side=args.side,
                with_futures=args.with_futures,
                since_ms=since_ms,
                cost=args.cost,
            )
            await service.wait()
        finally:
            await service.close()
            await history.close()
            await db.close()
        if job.state != "done" or job.model_id is None:
            print(f"Eğitim başarısız: {job.error}", file=sys.stderr)
            return 1
        model = next(m for m in service.models() if m["id"] == job.model_id)
        print(
            json.dumps(
                {
                    "model_id": job.model_id,
                    "oos": model["oos"],
                    "calibration": model["calibration"],
                    "top_features": model["top_features"],
                    "folds": [
                        {k: f[k] for k in ("fold", "test_start_ms", "n_test", "auc", "base_rate")}
                        for f in json.loads(
                            (settings.paths.models_dir / job.model_id / "meta.json").read_text(
                                encoding="utf-8"
                            )
                        )["report"]["folds"]
                    ],
                    "disclaimer": model["disclaimer"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    return asyncio.run(_train())


def _cmd_score_calibrate(args: argparse.Namespace) -> int:
    import duckdb

    from ati_engine.analysis.service import _with_quote
    from ati_engine.config import EngineSettings
    from ati_engine.core.models import Market
    from ati_engine.exchange.endpoints import endpoints_for
    from ati_engine.exchange.rate_limit import WeightBudget
    from ati_engine.exchange.rest import BinanceRestClient
    from ati_engine.history.archive import ArchiveClient
    from ati_engine.history.futures_data import FuturesDataSync
    from ati_engine.history.store import KlineStore
    from ati_engine.history.sync import HistorySync
    from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
    from ati_engine.scoring.calibration import ScoredBar, calibration_table, evaluate_history
    from ati_engine.scoring.costs import CostModel, CostSettingsView
    from ati_engine.scoring.score import OpportunityScorer
    from ati_engine.storage.database import Database

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    settings.paths.ensure()
    cfg = settings.scoring
    interval = args.interval or cfg.interval
    horizon = args.horizon or cfg.horizon_bars
    market = Market(args.market)
    futures = market is Market.USDM_FUTURES

    async def _run() -> dict[str, object] | None:
        try:
            store = KlineStore(settings.paths.history_db)
        except duckdb.IOException:
            print("Tarihsel veri dosyası kullanımda (motor çalışıyor olabilir).", file=sys.stderr)
            return None
        db = Database(settings.paths.database)
        await db.open()
        await db.migrate()
        endpoints = endpoints_for(market, settings.binance)
        rest = BinanceRestClient(
            endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
        )
        archive = ArchiveClient()
        sync = HistorySync(archive, store, db, rest={market: (rest, endpoints)})
        scorer = OpportunityScorer(
            weights=cfg.weights,
            cost_model=CostModel(
                CostSettingsView(
                    spot_taker_fee=cfg.spot_taker_fee,
                    futures_taker_fee=cfg.futures_taker_fee,
                    notional_usd=cfg.notional_usd,
                )
            ),
        )
        scored: list[ScoredBar] = []
        try:
            for symbol in args.symbol:
                symbol = symbol.upper()
                await sync.sync_klines(market, symbol, interval)
                if futures:
                    await FuturesDataSync(archive, store, db).sync(symbol)
                    rows = await store.bars_with_futures(symbol, interval)
                else:
                    rows = [_with_quote(r) for r in await store.candles("spot", symbol, interval)]
                result = await asyncio.to_thread(
                    evaluate_history,
                    rows,
                    market="spot" if not futures else "usdm_futures",
                    symbol=symbol,
                    interval=interval,
                    horizon=horizon,
                    scorer=scorer,
                    futures=futures,
                )
                print(f"{symbol}: {len(rows)} mum, {len(result)} yönlü puan", file=sys.stderr)
                scored.extend(result)
        finally:
            await archive.close()
            await rest.close()
            await store.close()
            await db.close()
        source = (
            f"{market.value} {'+'.join(s.upper() for s in args.symbol)} {interval}, ufuk "
            f"{horizon} mum; canlıya özgü balina/emir defteri bileşenleri hariç"
        )
        return calibration_table(scored, source=source)

    table = asyncio.run(_run())
    if table is None:
        return 4
    target = settings.paths.scoring_dir / f"calibration-{market.value}-{interval}-h{horizon}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(table, ensure_ascii=False, indent=2))
    print(f"Kaydedildi: {target}", file=sys.stderr)
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    import time
    from datetime import UTC, datetime

    import duckdb

    from ati_engine.backtest.engine import BacktestConfig
    from ati_engine.backtest.service import (
        SuiteOptions,
        ensure_strategies,
        prepare_records,
        run_suite,
    )
    from ati_engine.config import EngineSettings
    from ati_engine.core.models import Market
    from ati_engine.exchange.endpoints import endpoints_for
    from ati_engine.exchange.rate_limit import WeightBudget
    from ati_engine.exchange.rest import BinanceRestClient
    from ati_engine.history.archive import INTERVAL_MS
    from ati_engine.history.service import HistoryService
    from ati_engine.history.store import KlineStore
    from ati_engine.market.service import DEFAULT_WEIGHT_LIMIT
    from ati_engine.storage.database import Database
    from ati_engine.strategies.base import MarketKind

    overrides: dict[str, object] = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir)
    settings = EngineSettings(**overrides)  # type: ignore[arg-type]
    settings.paths.ensure()
    market = Market(args.market)
    futures = market is Market.USDM_FUTURES
    kind: MarketKind = "usdm_futures" if futures else "spot"
    since_ms = (
        int(datetime.fromisoformat(args.since).replace(tzinfo=UTC).timestamp() * 1000)
        if args.since
        else None
    )
    interval_ms = INTERVAL_MS[args.interval]
    config = BacktestConfig(
        market=kind,
        risk_per_trade=args.risk,
        max_positions=args.max_positions,
        max_leverage=args.leverage if futures else 1.0,
        max_hold_bars=args.max_hold,
    )

    async def _run() -> dict[str, object] | None:
        try:
            store = KlineStore(settings.paths.history_db)
        except duckdb.IOException:
            print("Tarihsel veri dosyası kullanımda (motor çalışıyor olabilir).", file=sys.stderr)
            return None
        db = Database(settings.paths.database)
        await db.open()
        await db.migrate()
        endpoints = endpoints_for(market, settings.binance)
        rest = BinanceRestClient(
            endpoints.rest_base, budget=WeightBudget(DEFAULT_WEIGHT_LIMIT[market])
        )
        history = HistoryService(store, db, rest={market: (rest, endpoints)}, owned_rest=[rest])
        try:
            started = time.perf_counter()
            data = await prepare_records(
                history,
                market.value,
                args.symbol,
                args.interval,
                since_ms=since_ms,
                progress=lambda m: print(m, file=sys.stderr),
            )
            print(f"Veri hazır ({time.perf_counter() - started:.1f} sn)", file=sys.stderr)
            await ensure_strategies(db)
            options = SuiteOptions(
                market=kind,
                interval=args.interval,
                interval_ms=interval_ms,
                walk_forward=not args.no_walk_forward,
                strategies=tuple(args.strategies) if args.strategies else None,
            )
            return await run_suite(
                data, options, config, db=db, progress=lambda m: print(m, file=sys.stderr)
            )
        finally:
            await history.close()
            await db.close()

    report = asyncio.run(_run())
    if report is None:
        return 4
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = settings.paths.backtests_dir / f"{stamp}-{market.value}-{args.interval}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Rapor: {target}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ati-engine", description="AI Trading Intelligence motoru"
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Motoru başlat")
    run.add_argument("--data-dir", help="Veri dizini (varsayılan: işletim sistemine göre)")
    run.add_argument("--port", type=int, help="Yerel API portu (0 = otomatik)")
    run.set_defaults(func=_cmd_run)

    show = sub.add_parser("show-config", help="Etkin ayarları göster")
    show.add_argument("--data-dir")
    show.set_defaults(func=_cmd_show_config)

    export = sub.add_parser("export-protocol-schema", help="Protokol JSON şemasını üret")
    export.add_argument("--output", help="Çıktı dosyası (varsayılan: stdout)")
    export.set_defaults(func=_cmd_export_schema)

    verify = sub.add_parser("verify-audit", help="Denetim kaydı zincirini doğrula")
    verify.add_argument("--data-dir")
    verify.set_defaults(func=_cmd_verify_audit)

    backup = sub.add_parser("backup", help="Veritabanını yedekle (motor çalışırken de olur)")
    backup.add_argument("--data-dir")
    backup.add_argument("--output-dir", help="Varsayılan: <veri klasörü>/backups")
    backup.add_argument("--keep", type=int, default=14, help="Saklanacak son yedek sayısı")
    backup.set_defaults(func=_cmd_backup)

    restore = sub.add_parser("restore", help="Yedeği geri yükle (motor kapalıyken)")
    restore.add_argument("source", help="Yedek dosyası")
    restore.add_argument("--data-dir")
    restore.set_defaults(func=_cmd_restore)

    history = sub.add_parser("history-sync", help="Binance arşivinden tarihsel mumları eşitle")
    history.add_argument("--data-dir")
    history.add_argument("--market", choices=["spot", "usdm_futures"], default="spot")
    history.add_argument("--symbol", nargs="+", required=True)
    history.add_argument("--interval", default="1m")
    history.set_defaults(func=_cmd_history_sync)

    replay = sub.add_parser(
        "history-replay", help="Balina radarını Binance işlem arşivi üzerinde yeniden oynat"
    )
    replay.add_argument("--market", choices=["spot", "usdm_futures"], default="spot")
    replay.add_argument("--symbol", required=True)
    replay.add_argument("--days", type=int, default=7)
    replay.add_argument("--end", help="Son gün (YYYY-AA-GG, varsayılan: dün)")
    replay.add_argument("--floor", type=float, help="Balina alt sınırı (USDT)")
    replay.add_argument("--report", help="JSON raporun yazılacağı dosya")
    replay.set_defaults(func=_cmd_history_replay)

    train = sub.add_parser("model-train", help="Yürüyen pencereyle model eğit (ONNX)")
    train.add_argument("--data-dir")
    train.add_argument("--market", choices=["spot", "usdm_futures"], default="spot")
    train.add_argument("--symbol", nargs="+", required=True)
    train.add_argument("--interval", default="1h")
    train.add_argument("--horizon", type=int, default=4, help="Etiket ufku (mum sayısı)")
    train.add_argument("--side", choices=["long", "short"], default="long")
    train.add_argument("--with-futures", action="store_true", help="Futures bağlam özellikleri")
    train.add_argument("--since", help="Başlangıç tarihi (YYYY-AA-GG)")
    train.add_argument("--cost", type=float, help="Gidiş-dönüş maliyet (ör. 0.0025)")
    train.set_defaults(func=_cmd_model_train)

    calibrate = sub.add_parser(
        "score-calibrate", help="Fırsat puanını geçmiş veride değerlendir ve kalibre et"
    )
    calibrate.add_argument("--data-dir")
    calibrate.add_argument("--market", choices=["spot", "usdm_futures"], default="spot")
    calibrate.add_argument("--symbol", nargs="+", required=True)
    calibrate.add_argument("--interval", help="Varsayılan: scoring.interval")
    calibrate.add_argument("--horizon", type=int, help="Varsayılan: scoring.horizon_bars")
    calibrate.set_defaults(func=_cmd_score_calibrate)

    backtest = sub.add_parser("backtest", help="Stratejileri geçmiş veride sına")
    backtest.add_argument("--data-dir")
    backtest.add_argument("--market", choices=["spot", "usdm_futures"], default="spot")
    backtest.add_argument("--symbol", nargs="+", required=True)
    backtest.add_argument("--interval", default="1h")
    backtest.add_argument("--since", help="Başlangıç tarihi (YYYY-AA-GG)")
    backtest.add_argument("--strategies", nargs="+", help="Yalnızca bu stratejiler")
    backtest.add_argument("--risk", type=float, default=0.01, help="İşlem başına risk oranı")
    backtest.add_argument("--max-positions", type=int, default=5)
    backtest.add_argument("--leverage", type=float, default=1.0, help="Yalnızca vadeli")
    backtest.add_argument("--max-hold", type=int, default=24, help="En uzun tutma (mum)")
    backtest.add_argument("--no-walk-forward", action="store_true")
    backtest.set_defaults(func=_cmd_backtest)

    version = sub.add_parser("version", help="Sürümü yazdır")
    version.set_defaults(func=lambda _: print(__version__) or 0)
    return parser


def _force_utf8_stdio() -> None:
    """Windows konsolu/borusu varsayılan olarak cp1252 gibi kod sayfaları kullanır ve
    Türkçe karakterlerde (ı, ş, ğ) ``UnicodeEncodeError`` ile çöker. Çıktı ve loglar
    her zaman UTF-8 yazılır; kodlanamayan karakter çökme yerine değiştirilir."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(["run", *(argv or [])])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
