"""Olay döngüsü seçimi.

psycopg'nin asenkron sürücüsü Windows'un varsayılan ``ProactorEventLoop``'u ile çalışmaz
("Psycopg cannot use the 'ProactorEventLoop'"); kendi Windows sunucunuzda (VDS) API veritabanına
erişemez. Veritabanı kullanan süreçler bu yüzden ``SelectorEventLoop`` ile çalışır. Linux'ta zaten
varsayılan budur; davranış değişmez.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


def selector_loop_factory(use_subprocess: bool = False) -> Callable[[], asyncio.AbstractEventLoop]:
    """uvicorn ``loop`` ayarı için (``"ati_cloud.loop:selector_loop_factory"``)."""
    return asyncio.SelectorEventLoop


UVICORN_LOOP = "ati_cloud.loop:selector_loop_factory"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """``asyncio.run`` + SelectorEventLoop (komut satırı araçları)."""
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
