"""Veritabanı erişimi.

Kullanıcı istekleri `user_tx` içinde `authenticated` rolüne ve kullanıcının JWT iddialarına
geçilerek çalışır; böylece Supabase RLS kuralları backend üzerinden de aynen uygulanır.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .auth import CurrentUser


class Database:
    def __init__(self, url: str, max_size: int = 10) -> None:
        self.pool = AsyncConnectionPool(
            url, min_size=1, max_size=max_size, open=False,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=10)

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        async with self.pool.connection() as conn:
            await conn.execute("select 1")
        return True

    @asynccontextmanager
    async def user_tx(self, user: CurrentUser) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "select set_config('request.jwt.claims', %s, true)",
                (json.dumps({"sub": user.id, "role": "authenticated", "email": user.email}),),
            )
            await conn.execute("set local role authenticated")
            yield conn
