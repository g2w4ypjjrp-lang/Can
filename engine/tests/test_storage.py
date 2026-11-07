from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ati_engine.storage.audit import AuditLog
from ati_engine.storage.database import (
    Database,
    Migration,
    MigrationError,
    _split_sql,
    load_packaged_migrations,
)
from ati_engine.storage.settings_store import SettingsStore

EXPECTED_TABLES = {
    "schema_migrations",
    "settings",
    "secrets",
    "exchange_symbols",
    "history_sync_state",
    "strategies",
    "strategy_metrics",
    "decisions",
    "orders",
    "fills",
    "positions",
    "risk_events",
    "whale_events",
    "alerts",
    "audit_log",
}


async def test_migrations_create_schema(db: Database) -> None:
    rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
    assert {r[0] for r in rows} >= EXPECTED_TABLES
    journal = await db.fetchone("PRAGMA journal_mode")
    assert journal is not None and journal[0] == "wal"
    fk = await db.fetchone("PRAGMA foreign_keys")
    assert fk == (1,)


async def test_migrations_are_idempotent(db: Database) -> None:
    assert await db.migrate() == []


async def test_modified_migration_is_detected(tmp_path: Path) -> None:
    database = Database(tmp_path / "x.db")
    await database.open()
    try:
        await database.migrate([Migration(1, "a", "CREATE TABLE t (x INTEGER);")])
        with pytest.raises(MigrationError, match="değiştirilmiş"):
            await database.migrate([Migration(1, "a", "CREATE TABLE t (y INTEGER);")])
    finally:
        await database.close()


async def test_newer_database_is_rejected(tmp_path: Path) -> None:
    database = Database(tmp_path / "x.db")
    await database.open()
    try:
        await database.migrate(
            [Migration(1, "a", "CREATE TABLE t (x INTEGER);"), Migration(2, "b", "SELECT 1;")]
        )
        with pytest.raises(MigrationError, match="daha yeni"):
            await database.migrate([Migration(1, "a", "CREATE TABLE t (x INTEGER);")])
    finally:
        await database.close()


async def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    database = Database(tmp_path / "x.db")
    await database.open()
    try:
        with pytest.raises(sqlite3.OperationalError):
            await database.migrate(
                [Migration(1, "a", "CREATE TABLE t (x INTEGER);\nTHIS IS NOT SQL;")]
            )
        rows = await database.fetchall("SELECT name FROM sqlite_master WHERE name = 't'")
        assert rows == []
    finally:
        await database.close()


def test_sql_splitter_keeps_trigger_bodies() -> None:
    script = """
    -- yorum
    CREATE TABLE a (x INTEGER);
    CREATE TRIGGER t BEFORE DELETE ON a
    BEGIN
        SELECT RAISE(ABORT, 'no');
    END;
    """
    parts = _split_sql(script)
    assert len(parts) == 2
    assert "RAISE" in parts[1]


def test_packaged_migrations_are_ordered() -> None:
    migrations = load_packaged_migrations()
    assert [m.version for m in migrations] == sorted(m.version for m in migrations)
    assert migrations[0].version == 1


async def test_strict_tables_reject_wrong_types(db: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO alerts (ts, category, severity, title, body) VALUES ('dün', 'x', 'info', 't', 'b')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO alerts (ts, category, severity, title, body) VALUES (1, 'x', 'ölümcül', 't', 'b')"
        )


async def test_live_strategy_requires_recorded_approval(db: Database) -> None:
    """Strateji 'live' aşamasına kullanıcı onayı kaydı olmadan geçemez."""
    await db.execute(
        "INSERT INTO strategies (id, name, version, stage, params, created_at, stage_changed_at) "
        "VALUES ('m.v1', 'momentum', 1, 'paper', '{}', 1, 1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute("UPDATE strategies SET stage = 'live' WHERE id = 'm.v1'")
    await db.execute(
        "UPDATE strategies SET stage = 'live', approved_live_by = 'kullanıcı', approved_live_at = 2 "
        "WHERE id = 'm.v1'"
    )


async def test_only_one_open_position_per_symbol_side(db: Database) -> None:
    sql = (
        "INSERT INTO positions (id, mode, market, symbol, side, status, quantity, entry_price, opened_at) "
        "VALUES (?, 'paper', 'usdm_futures', 'BTCUSDT', 'LONG', ?, '1', '100', 1)"
    )
    await db.execute(sql, ("p1", "open"))
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(sql, ("p2", "open"))
    await db.execute("UPDATE positions SET status = 'closed', closed_at = 2 WHERE id = 'p1'")
    await db.execute(sql, ("p3", "open"))


async def test_settings_store_roundtrip(db: Database) -> None:
    store = SettingsStore(db)
    assert await store.get("x", "varsayılan") == "varsayılan"
    await store.set("x", {"a": [1, 2], "ğ": "ü"})
    assert await store.get("x") == {"a": [1, 2], "ğ": "ü"}
    await store.set("x", 5)
    assert await store.get("x") == 5


# --- Denetim kaydı -----------------------------------------------------------------------


async def test_audit_chain_verifies(audit: AuditLog) -> None:
    for i in range(5):
        await audit.record(actor="u", action=f"a{i}", details={"i": i})
    result = await audit.verify()
    assert result.ok
    assert result.checked == 5


async def test_audit_rows_are_immutable(audit: AuditLog, db: Database) -> None:
    await audit.record(actor="u", action="a")
    with pytest.raises(sqlite3.IntegrityError, match="değiştirilemez"):
        await db.execute("UPDATE audit_log SET actor = 'saldırgan'")
    with pytest.raises(sqlite3.IntegrityError, match="silinemez"):
        await db.execute("DELETE FROM audit_log")


async def test_audit_tamper_is_detected(audit: AuditLog, db: Database) -> None:
    for i in range(3):
        await audit.record(actor="u", action=f"a{i}")
    # Tetikleyiciyi atlatan bir saldırgan (dosyaya doğrudan erişim) senaryosu.
    await db.execute("DROP TRIGGER trg_audit_log_no_update")
    await db.execute("UPDATE audit_log SET actor = 'saldırgan' WHERE id = 2")
    result = await audit.verify()
    assert not result.ok
    assert result.broken_at_id == 2


async def test_audit_redacts_secrets(audit: AuditLog) -> None:
    await audit.record(
        actor="u", action="api_key.add", details={"api_key": "abc", "label": "ana hesap"}
    )
    entry = (await audit.recent(1))[0]
    assert entry["details"] == {"api_key": "***", "label": "ana hesap"}
