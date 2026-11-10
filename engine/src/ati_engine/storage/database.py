"""SQLite erişim katmanı.

* WAL modu: okuyucular yazarı engellemez; çökme sonrası tutarlılık korunur.
* Tek yazar iş parçacığı: ``sqlite3`` bağlantısı tek bir özel iş parçacığına aittir ve
  asyncio olay döngüsü hiçbir zaman disk G/Ç'si için bloke olmaz.
* ``foreign_keys=ON``, ``busy_timeout`` ve ``synchronous=NORMAL`` (WAL ile güvenli).
* Geçişler (migrations) ``storage/migrations/NNNN_ad.sql`` dosyalarından sırayla uygulanır;
  uygulanmış her geçişin SHA-256 özeti saklanır ve sonradan değiştirilmişse motor açılmaz.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

Params = Sequence[Any] | dict[str, Any]

_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


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


def load_packaged_migrations() -> list[Migration]:
    package = resources.files("ati_engine.storage.migrations")
    migrations: list[Migration] = []
    for entry in package.iterdir():
        match = _MIGRATION_RE.match(entry.name)
        if match:
            migrations.append(
                Migration(int(match.group(1)), match.group(2), entry.read_text(encoding="utf-8"))
            )
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise MigrationError("Aynı sürüm numarasına sahip birden fazla geçiş var")
    return migrations


class Database:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        self._conn: sqlite3.Connection | None = None
        self._thread_id: int | None = None

    @property
    def path(self) -> str:
        return self._path

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._call, fn)

    def _call(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._conn is None:
            raise RuntimeError("Veritabanı açık değil")
        assert self._thread_id == threading.get_ident(), "SQLite bağlantısı yanlış iş parçacığında"  # noqa: S101
        return fn(self._conn)

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._open_sync)

    def _open_sync(self) -> None:
        if self._conn is not None:
            return
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, isolation_level=None, check_same_thread=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        self._conn = conn
        self._thread_id = threading.get_ident()

    async def close(self) -> None:
        def _close(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA optimize")
            conn.close()

        if self._conn is not None:
            await self._run(_close)
            self._conn = None
        self._executor.shutdown(wait=True)

    async def backup(self, target: Path | str) -> int:
        """Çalışırken tutarlı anlık yedek (SQLite çevrimiçi yedekleme API'si). Önce geçici
        dosyaya yazılır, bütünlüğü denetlenir, sonra yerine taşınır (yarım yedek bırakılmaz).
        Yedeğin boyutunu döner."""
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = target_path.with_name(target_path.name + ".tmp")

        def _do(conn: sqlite3.Connection) -> int:
            tmp.unlink(missing_ok=True)
            dest = sqlite3.connect(str(tmp))
            try:
                conn.backup(dest)
                result = dest.execute("PRAGMA integrity_check").fetchone()
                if result is None or result[0] != "ok":
                    raise RuntimeError(f"Yedeğin bütünlük denetimi başarısız: {result}")
            finally:
                dest.close()
            tmp.replace(target_path)
            return target_path.stat().st_size

        return await self._run(_do)

    async def execute(self, sql: str, params: Params = ()) -> int:
        """Tek bir yazma komutu çalıştırır; etkilenen satır sayısını döner."""
        return await self._run(lambda c: c.execute(sql, params).rowcount)

    async def execute_returning_id(self, sql: str, params: Params = ()) -> int:
        def _do(c: sqlite3.Connection) -> int:
            cursor = c.execute(sql, params)
            if cursor.lastrowid is None:
                raise RuntimeError("Eklenen satırın kimliği alınamadı")
            return cursor.lastrowid

        return await self._run(_do)

    async def executemany(self, sql: str, rows: Iterable[Params]) -> None:
        data = list(rows)

        def _do(c: sqlite3.Connection) -> None:
            c.execute("BEGIN IMMEDIATE")
            try:
                c.executemany(sql, data)
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")

        await self._run(_do)

    async def fetchone(self, sql: str, params: Params = ()) -> tuple[Any, ...] | None:
        return await self._run(lambda c: c.execute(sql, params).fetchone())

    async def fetchall(self, sql: str, params: Params = ()) -> list[tuple[Any, ...]]:
        return await self._run(lambda c: c.execute(sql, params).fetchall())

    async def transaction(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """``fn`` bağlantıyı alır ve tek bir BEGIN IMMEDIATE ... COMMIT içinde çalışır."""

        def _do(c: sqlite3.Connection) -> T:
            c.execute("BEGIN IMMEDIATE")
            try:
                result = fn(c)
            except BaseException:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")
            return result

        return await self._run(_do)

    async def migrate(self, migrations: Sequence[Migration] | None = None) -> list[int]:
        """Bekleyen geçişleri uygular; uygulanan sürümleri döner."""
        items = list(migrations) if migrations is not None else load_packaged_migrations()
        return await self._run(lambda c: _apply_migrations(c, items))


def _apply_migrations(conn: sqlite3.Connection, migrations: list[Migration]) -> list[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT    NOT NULL,
            checksum    TEXT    NOT NULL,
            applied_at  INTEGER NOT NULL
        ) STRICT
        """
    )
    applied = {
        int(v): str(cs)
        for v, cs in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    }
    known = {m.version for m in migrations}
    unknown = sorted(set(applied) - known)
    if unknown:
        raise MigrationError(
            f"Veritabanı bu sürümden daha yeni geçişler içeriyor: {unknown}. "
            "Uygulamayı güncelleyin."
        )
    newly_applied: list[int] = []
    for migration in migrations:
        existing = applied.get(migration.version)
        if existing is not None:
            if existing != migration.checksum:
                raise MigrationError(
                    f"{migration.version:04d}_{migration.name} geçişi uygulandıktan sonra "
                    "değiştirilmiş (özet uyuşmuyor)."
                )
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split_sql(migration.sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, CAST(strftime('%s','now') AS INTEGER) * 1000)",
                (migration.version, migration.name, migration.checksum),
            )
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        newly_applied.append(migration.version)
    return newly_applied


def _split_sql(script: str) -> list[str]:
    """SQL betiğini ifadelere böler (tetikleyici gövdelerindeki ';' korunur)."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        candidate = "\n".join(buffer)
        if stripped.endswith(";") and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buffer = []
    if buffer and "\n".join(buffer).strip():
        raise MigrationError("Geçiş dosyası tamamlanmamış bir SQL ifadesi ile bitiyor")
    return statements
