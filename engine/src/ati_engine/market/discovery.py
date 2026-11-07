"""Sembol keşfi ve sembol kayıt defteri.

``exchangeInfo`` yanıtı borsadaki her sembolün durumunu ve emir kurallarını (fiyat adımı,
miktar adımı, minimum emir tutarı) verir. Bu modül:

1. Yanıtı ``SymbolInfo`` nesnelerine çevirir (``parse_exchange_info``).
2. İzlenecek evreni seçer: ayarlardaki kote varlığı (USDT) ve Futures'ta sözleşme türü
   (varsayılan yalnızca kripto ``PERPETUAL``; altın/gümüş gibi ``TRADIFI_PERPETUAL`` ve vadeli
   kontratlar hariç).
3. Kalıcı kayıt defterini (``exchange_symbols`` tablosu) günceller ve farkları bulur:
   - **Yeni listeleme:** daha önce hiç görülmemiş, işlem gören sembol → ``SymbolListed``
   - **Kapanma / askıya alma:** işlem görürken durumu değişen ya da listeden kalkan sembol →
     ``SymbolDelisted``

İlk çalıştırmada (kayıt defteri boşken) bütün semboller "yeni" görünür; bu durumda olay
yayımlanmaz, yalnızca kayıt yapılır.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ati_engine.core.bus import EventBus
from ati_engine.core.clock import Clock, SystemClock
from ati_engine.core.models import Market, SymbolInfo
from ati_engine.market.events import SymbolDelisted, SymbolListed
from ati_engine.storage.database import Database


def _filters(raw: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(f["filterType"]): f for f in raw}


def _min_notional(market: Market, filters: Mapping[str, Mapping[str, Any]]) -> Decimal:
    if market is Market.SPOT:
        if "NOTIONAL" in filters:
            return Decimal(str(filters["NOTIONAL"].get("minNotional", "0")))
        if "MIN_NOTIONAL" in filters:
            return Decimal(str(filters["MIN_NOTIONAL"].get("minNotional", "0")))
        return Decimal(0)
    entry = filters.get("MIN_NOTIONAL", {})
    return Decimal(str(entry.get("notional", entry.get("minNotional", "0"))))


def parse_symbol(market: Market, raw: Mapping[str, Any]) -> SymbolInfo | None:
    """Tek bir exchangeInfo sembol kaydını çevirir; zorunlu filtreler yoksa ``None``."""
    filters = _filters(raw.get("filters", []))
    price = filters.get("PRICE_FILTER")
    lot = filters.get("LOT_SIZE")
    if price is None or lot is None:
        return None
    tick = Decimal(str(price["tickSize"]))
    step = Decimal(str(lot["stepSize"]))
    if tick <= 0 or step <= 0:
        return None
    return SymbolInfo(
        market=market,
        symbol=str(raw["symbol"]),
        base_asset=str(raw["baseAsset"]),
        quote_asset=str(raw["quoteAsset"]),
        status=str(raw["status"]),
        tick_size=tick,
        step_size=step,
        min_qty=Decimal(str(lot["minQty"])),
        min_notional=_min_notional(market, filters),
        contract_type=raw.get("contractType"),
        onboard_date_ms=raw.get("onboardDate"),
    )


def parse_exchange_info(market: Market, payload: Mapping[str, Any]) -> list[SymbolInfo]:
    result: list[SymbolInfo] = []
    for raw in payload.get("symbols", []):
        info = parse_symbol(market, raw)
        if info is not None:
            result.append(info)
    return result


@dataclass(frozen=True)
class UniverseFilter:
    """İzlenecek sembol evreni."""

    quote_asset: str = "USDT"
    futures_contract_types: frozenset[str] = frozenset({"PERPETUAL"})
    allowlist: frozenset[str] | None = None
    max_symbols: int | None = None
    excluded_bases: frozenset[str] = frozenset()

    def accepts(self, info: SymbolInfo) -> bool:
        if info.quote_asset != self.quote_asset or info.base_asset in self.excluded_bases:
            return False
        if (
            info.market is Market.USDM_FUTURES
            and info.contract_type not in self.futures_contract_types
        ):
            return False
        return self.allowlist is None or info.symbol in self.allowlist


@dataclass
class DiscoveryDiff:
    market: Market
    listed: list[SymbolInfo] = field(default_factory=list)
    delisted: list[SymbolInfo] = field(default_factory=list)
    initial: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.listed or self.delisted)


def _row(info: SymbolInfo) -> tuple[Any, ...]:
    return (
        info.market.value,
        info.symbol,
        info.base_asset,
        info.quote_asset,
        info.status,
        info.contract_type,
        str(info.tick_size),
        str(info.step_size),
        str(info.min_qty),
        str(info.min_notional),
        info.onboard_date_ms,
    )


class SymbolRegistry:
    """Borsa sembollerinin kalıcı kaydı ve izlenen evren."""

    def __init__(
        self,
        db: Database,
        bus: EventBus,
        *,
        universe: UniverseFilter | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._db = db
        self._bus = bus
        self._universe = universe or UniverseFilter()
        self._clock = clock or SystemClock()
        self._tracked: dict[Market, dict[str, SymbolInfo]] = {}

    @property
    def universe(self) -> UniverseFilter:
        return self._universe

    def tracked(self, market: Market) -> list[SymbolInfo]:
        """İzlenen (işlem gören ve evrene uyan) semboller; sembol adına göre sıralı."""
        symbols = sorted(self._tracked.get(market, {}).values(), key=lambda s: s.symbol)
        if self._universe.max_symbols is not None:
            symbols = symbols[: self._universe.max_symbols]
        return symbols

    def get(self, market: Market, symbol: str) -> SymbolInfo | None:
        return self._tracked.get(market, {}).get(symbol)

    async def apply(self, market: Market, symbols: Iterable[SymbolInfo]) -> DiscoveryDiff:
        now = self._clock.now_ms()
        incoming = {s.symbol: s for s in symbols}
        known_rows = await self._db.fetchall(
            "SELECT symbol, status, delisted_at, base_asset, quote_asset, contract_type "
            "FROM exchange_symbols WHERE market = ?",
            (market.value,),
        )
        known = {r[0]: r for r in known_rows}
        diff = DiscoveryDiff(market=market, initial=not known)

        for symbol, info in incoming.items():
            if not info.is_trading or not self._universe.accepts(info):
                continue
            previous = known.get(symbol)
            was_trading = previous is not None and previous[1] == "TRADING" and previous[2] is None
            if not was_trading:
                diff.listed.append(info)  # yeni listeleme veya yeniden işleme açılma

        for symbol, row in known.items():
            _, status, delisted_at, base, quote, contract_type = row
            if status != "TRADING" or delisted_at is not None:
                continue
            current = incoming.get(symbol)
            if current is not None and current.is_trading:
                continue
            snapshot = current or SymbolInfo(
                market=market,
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                status="REMOVED",
                tick_size=Decimal(1),
                step_size=Decimal(1),
                min_qty=Decimal(0),
                min_notional=Decimal(0),
                contract_type=contract_type,
            )
            if self._universe.accepts(snapshot):
                diff.delisted.append(snapshot)

        def _write(conn: sqlite3.Connection) -> None:
            conn.executemany(
                """
                INSERT INTO exchange_symbols (market, symbol, base_asset, quote_asset, status,
                    contract_type, tick_size, step_size, min_qty, min_notional, onboard_date,
                    filters, first_seen_at, last_seen_at, delisted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, NULL)
                ON CONFLICT(market, symbol) DO UPDATE SET
                    base_asset = excluded.base_asset,
                    quote_asset = excluded.quote_asset,
                    status = excluded.status,
                    contract_type = excluded.contract_type,
                    tick_size = excluded.tick_size,
                    step_size = excluded.step_size,
                    min_qty = excluded.min_qty,
                    min_notional = excluded.min_notional,
                    onboard_date = excluded.onboard_date,
                    last_seen_at = excluded.last_seen_at,
                    delisted_at = CASE
                        WHEN excluded.status = 'TRADING' THEN NULL
                        ELSE COALESCE(exchange_symbols.delisted_at, excluded.last_seen_at)
                    END
                """,
                [(*_row(info), now, now) for info in incoming.values()],
            )
            missing = [s for s in known if s not in incoming]
            conn.executemany(
                "UPDATE exchange_symbols SET delisted_at = COALESCE(delisted_at, ?) "
                "WHERE market = ? AND symbol = ?",
                [(now, market.value, s) for s in missing],
            )

        await self._db.transaction(_write)
        self._tracked[market] = {
            s.symbol: s for s in incoming.values() if s.is_trading and self._universe.accepts(s)
        }

        if not diff.initial:
            for info in diff.listed:
                await self._bus.publish(
                    SymbolListed(
                        market=market, symbol=info.symbol, onboard_date_ms=info.onboard_date_ms
                    )
                )
            for info in diff.delisted:
                await self._bus.publish(
                    SymbolDelisted(market=market, symbol=info.symbol, status=info.status)
                )
        return diff
