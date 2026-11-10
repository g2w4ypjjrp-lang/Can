"""Olay döngüsü seçimi.

psycopg'nin asenkron sürücüsü Windows'un varsayılan ``ProactorEventLoop``'u ile çalışmaz
("Psycopg cannot use the 'ProactorEventLoop'"); kendi Windows sunucunuzda (VDS) API veritabanına
erişemez. Veritabanı kullanan süreçler bu yüzden ``SelectorEventLoop`` ile çalışır. Linux'ta zaten
varsayılan budur; davranış değişmez.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

# uvicorn ``loop`` ayarı: yerleşik adlar dışındaki değer "modül:nesne" olarak içe aktarılır ve
# döngü oluşturmak için argümansız çağrılır; SelectorEventLoop sınıfı doğrudan bu işi görür.
UVICORN_LOOP = "asyncio:SelectorEventLoop"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """``asyncio.run`` + SelectorEventLoop (komut satırı araçları)."""
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
