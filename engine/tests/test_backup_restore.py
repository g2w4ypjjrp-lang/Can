"""Aşama 18: felaket kurtarma — motor veritabanı yedeği ve geri yükleme.

Yedek motor çalışırken tutarlı olarak alınır (SQLite çevrimiçi yedekleme), bütünlüğü ve denetim
zinciri doğrulanır. Geri yükleme motor çalışırken reddedilir; mevcut veritabanı silinmez. Bozuk
yedek geri yüklenmez. Aynı bilgisayarda geri yüklenen kasadaki gizli bilgiler çözülür.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ati_engine.__main__ import main as cli
from ati_engine.app import Engine
from ati_engine.config import EngineSettings, LocalApiSettings
from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import Database


def settings(data_dir: Path) -> EngineSettings:
    return EngineSettings(
        data_dir=data_dir,
        log_to_console=False,
        heartbeat_interval_s=0.05,
        api=LocalApiSettings(port=0),
    )


async def start(data_dir: Path) -> tuple[Engine, asyncio.Task[int]]:
    engine = Engine(settings(data_dir))
    task = asyncio.create_task(engine.run())
    await asyncio.wait_for(engine.ready.wait(), timeout=20)
    return engine, task


async def stop(engine: Engine, task: asyncio.Task[int]) -> None:
    assert engine.runtime is not None
    engine.runtime.request_shutdown()
    assert await asyncio.wait_for(task, timeout=20) == 0


async def test_online_backup_and_guarded_restore(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    engine, task = await start(data_dir)
    runtime = engine.runtime
    assert runtime is not None
    await runtime.vault.put("test.gizli", "yedekte-kalmali-123")
    for i in range(25):
        await runtime.audit.record(actor="test", action="test.yedek", details={"i": i})

    # Motor çalışırken yedek (ayrı bir bağlantıyla, WAL sayesinde tutarlı).
    assert await asyncio.to_thread(cli, ["backup", "--data-dir", str(data_dir), "--keep", "2"]) == 0
    backups = sorted((data_dir / "backups").glob("engine-*.db"))
    assert len(backups) == 1
    backup = backups[0]
    # Motor çalışırken geri yükleme reddedilir.
    assert await asyncio.to_thread(cli, ["restore", str(backup), "--data-dir", str(data_dir)]) == 4

    # Yedekten sonra yapılan değişiklik geri yüklemede kaybolmalı.
    await runtime.vault.put("test.sonradan", "geri-yuklemede-olmamali")
    await stop(engine, task)

    assert await asyncio.to_thread(cli, ["restore", str(backup), "--data-dir", str(data_dir)]) == 0
    kept = list(data_dir.glob("*.geri-yukleme-oncesi-*"))
    assert len(kept) == 1, "mevcut veritabanı silinmemeli"

    engine, task = await start(data_dir)
    runtime = engine.runtime
    assert runtime is not None
    secret = await runtime.vault.get("test.gizli")
    assert secret is not None and secret.get_secret_value() == "yedekte-kalmali-123"
    assert await runtime.vault.get("test.sonradan") is None
    result = await AuditLog(runtime.db).verify()
    assert result.ok and result.checked >= 25
    await stop(engine, task)


async def test_backup_keeps_only_recent_copies(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    engine, task = await start(data_dir)
    await stop(engine, task)
    folder = data_dir / "backups"
    folder.mkdir(parents=True)
    for day in range(1, 6):
        (folder / f"engine-2026010{day}-000000.db").write_bytes(b"eski")
    assert await asyncio.to_thread(cli, ["backup", "--data-dir", str(data_dir), "--keep", "3"]) == 0
    remaining = sorted(p.name for p in folder.glob("engine-*.db"))
    assert len(remaining) == 3 and remaining[0] == "engine-20260104-000000.db"


@pytest.mark.parametrize("damage", ["truncated", "garbage"])
async def test_damaged_backup_is_refused(tmp_path: Path, damage: str) -> None:
    data_dir = tmp_path / "data"
    engine, task = await start(data_dir)
    await stop(engine, task)
    assert await asyncio.to_thread(cli, ["backup", "--data-dir", str(data_dir)]) == 0
    backup = next((data_dir / "backups").glob("engine-*.db"))
    raw = backup.read_bytes()
    bad = tmp_path / "bozuk.db"
    bad.write_bytes(
        raw[: len(raw) // 3] if damage == "truncated" else b"SQLite format 3\x00" + b"x" * 4096
    )
    before = (data_dir / "engine.db").read_bytes() if (data_dir / "engine.db").exists() else None
    code = await asyncio.to_thread(cli, ["restore", str(bad), "--data-dir", str(data_dir)])
    assert code != 0
    if before is not None:
        assert (data_dir / "engine.db").read_bytes() == before  # dokunulmadı


async def test_database_backup_is_consistent_snapshot(tmp_path: Path) -> None:
    db = Database(tmp_path / "a.db")
    await db.open()
    await db.migrate()
    await db.execute("CREATE TABLE t (x INTEGER)")
    await db.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1000)])
    size = await db.backup(tmp_path / "yedek" / "a.db")
    await db.close()
    assert size > 0 and not (tmp_path / "yedek" / "a.db.tmp").exists()
    copy = Database(tmp_path / "yedek" / "a.db")
    await copy.open()
    row = await copy.fetchone("SELECT count(*), sum(x) FROM t")
    await copy.close()
    assert row == (1000, sum(range(1000)))
