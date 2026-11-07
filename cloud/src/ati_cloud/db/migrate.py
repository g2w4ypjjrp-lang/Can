"""PostgreSQL geçiş çalıştırıcısı.

* Her geçiş kendi işleminde (transaction) uygulanır; hata olursa tamamen geri alınır.
* Uygulanan geçişin SHA-256 özeti saklanır; dosya sonradan değiştirilirse hata verilir.
* ``pg_advisory_lock`` ile aynı anda yalnızca bir örnek geçiş uygular (çoklu örnekli
  yönetilen dağıtımlarda yarış durumunu önler).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from importlib import resources

import psycopg

_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_LOCK_ID = 0x41544901  # "ATI" + 1


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def load_migrations() -> list[Migration]:
    package = resources.files("ati_cloud.db.migrations")
    items: list[Migration] = []
    for entry in package.iterdir():
        match = _MIGRATION_RE.match(entry.name)
        if match:
            items.append(
                Migration(int(match.group(1)), match.group(2), entry.read_text(encoding="utf-8"))
            )
    items.sort(key=lambda m: m.version)
    versions = [m.version for m in items]
    if len(versions) != len(set(versions)):
        raise MigrationError("Aynı sürüm numarasına sahip birden fazla geçiş var")
    return items


def _ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     integer PRIMARY KEY,
            name        text NOT NULL,
            checksum    text NOT NULL,
            applied_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def pending(conn: psycopg.Connection, migrations: list[Migration]) -> list[Migration]:
    """Bekleyen geçişleri döner. Salt okumadır; tablo yoksa hepsi bekliyor sayılır."""
    exists = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL").fetchone()
    applied: dict[int, str] = {}
    if exists and exists[0]:
        applied = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
    unknown = sorted(set(applied) - {m.version for m in migrations})
    if unknown:
        raise MigrationError(f"Veritabanında bu sürümde olmayan geçişler var: {unknown}")
    result: list[Migration] = []
    for migration in migrations:
        checksum = applied.get(migration.version)
        if checksum is None:
            result.append(migration)
        elif checksum != migration.checksum:
            raise MigrationError(
                f"{migration.version:04d}_{migration.name} uygulandıktan sonra değiştirilmiş"
            )
    return result


def apply_migrations(dsn: str, migrations: list[Migration] | None = None) -> list[int]:
    items = migrations if migrations is not None else load_migrations()
    applied: list[int] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_ID,))
        try:
            _ensure_table(conn)
            for migration in pending(conn, items):
                with conn.transaction():
                    conn.execute(migration.sql.encode("utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, checksum) "
                        "VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                applied.append(migration.version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_ID,))
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ati-cloud-migrate")
    parser.add_argument("--check", action="store_true", help="Yalnızca bekleyen geçişleri listele")
    args = parser.parse_args(argv)
    dsn = os.environ.get("ATI_DATABASE_URL")
    if not dsn:
        print("ATI_DATABASE_URL tanımlı değil", file=sys.stderr)
        return 2
    if args.check:
        with psycopg.connect(dsn, autocommit=True) as conn:
            todo = pending(conn, load_migrations())
        for migration in todo:
            print(f"bekliyor: {migration.version:04d}_{migration.name}")
        return 1 if todo else 0
    for version in apply_migrations(dsn):
        print(f"uygulandı: {version:04d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
