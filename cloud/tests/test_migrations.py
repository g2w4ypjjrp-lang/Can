from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from ati_cloud.db.migrate import (
    Migration,
    MigrationError,
    apply_migrations,
    load_migrations,
    pending,
)


def test_full_schema_applies_on_empty_database(empty_dsn: str) -> None:
    applied = apply_migrations(empty_dsn)
    assert applied == [m.version for m in load_migrations()]
    # İkinci çalıştırma hiçbir şey yapmaz.
    assert apply_migrations(empty_dsn) == []
    with psycopg.connect(empty_dsn) as conn:
        assert pending(conn, load_migrations()) == []


def test_pending_is_read_only(empty_dsn: str) -> None:
    with psycopg.connect(empty_dsn, autocommit=True) as conn:
        todo = pending(conn, load_migrations())
        assert [m.version for m in todo] == [m.version for m in load_migrations()]
        exists = conn.execute("SELECT to_regclass('schema_migrations')").fetchone()
        assert exists == (None,)


def test_modified_migration_detected(empty_dsn: str) -> None:
    apply_migrations(empty_dsn, [Migration(1, "a", "CREATE TABLE t (x int);")])
    with pytest.raises(MigrationError, match="değiştirilmiş"):
        apply_migrations(empty_dsn, [Migration(1, "a", "CREATE TABLE t (y int);")])


def test_failed_migration_rolls_back(empty_dsn: str) -> None:
    with pytest.raises(psycopg.errors.SyntaxError):
        apply_migrations(empty_dsn, [Migration(1, "a", "CREATE TABLE t (x int); BOZUK SQL;")])
    with psycopg.connect(empty_dsn) as conn:
        assert conn.execute("SELECT to_regclass('t')").fetchone() == (None,)
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone() == (0,)


def test_seed_data(scalar: Callable[..., Any]) -> None:
    # 1 deneme + 5 süre x 3 cihaz limiti
    assert scalar("SELECT count(*) FROM license_plans") == 16
    assert scalar("SELECT count(*) FROM license_plans WHERE is_active") == 0
    assert scalar("SELECT count(*) FROM license_plans WHERE duration_days IS NULL") == 3
    assert scalar("SELECT device_limit FROM license_plans WHERE code = 'lifetime_3dev'") == 3
    assert scalar(
        "SELECT count(*) FROM admin_role_permissions WHERE role_code = 'super_admin'"
    ) == scalar("SELECT count(*) FROM admin_permissions")
    # Destek rolü para iadesi veya lisans anahtarı görüntüleme yetkisine sahip değil.
    assert (
        scalar(
            "SELECT count(*) FROM admin_role_permissions WHERE role_code = 'support' "
            "AND permission_code IN ('payment.refund', 'license.reveal_key')"
        )
        == 0
    )


def test_plan_cannot_be_activated_without_price(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE license_plans SET is_active = true WHERE code = 'd30_1dev'")
    conn.execute(
        "UPDATE license_plans SET is_active = true, price_minor = 4900 WHERE code = 'd30_1dev'"
    )
