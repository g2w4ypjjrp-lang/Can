"""Alan (domain) modelleri.

Fiyat ve miktarlar her zaman ``Decimal`` olarak taşınır. Binance fiyatları metin olarak
gönderir ("76098.01000000"); bunları ``float``'a çevirmek emir gönderirken tick/step
yuvarlama hatalarına ve borsanın emri reddetmesine yol açar.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Decimal
from enum import StrEnum

import msgspec


class Market(StrEnum):
    SPOT = "spot"
    USDM_FUTURES = "usdm_futures"


class TradingMode(StrEnum):
    """İşlem modu. Varsayılan her zaman PAPER'dır (sanal işlem)."""

    PAPER = "paper"  # Sanal işlem: borsaya hiçbir emir gönderilmez.
    TESTNET = "testnet"  # Binance test ağı: gerçek para yok.
    LIVE = "live"  # Gerçek hesap: açık kullanıcı onayı ve tüm ön koşullar gerekir.


class EngineState(StrEnum):
    STARTING = "starting"
    SAFE_MODE = "safe_mode"  # Yeni pozisyon açılmaz; mevcut pozisyonlar yönetilir/kapatılabilir.
    RUNNING = "running"
    HALTED = "halted"  # Acil durdurma (kill switch) devrede.
    STOPPING = "stopping"
    STOPPED = "stopped"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    BOTH = "BOTH"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"  # Post-only (yalnızca futures)


class OrderStatus(StrEnum):
    PENDING_NEW = "PENDING_NEW"  # Yerelde oluşturuldu, borsa onayı bekleniyor.
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_ORDER_STATUSES


_TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


def _quantize_to_step(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    if step <= 0:
        raise ValueError("Adım (step/tick) pozitif olmalı")
    units = (value / step).to_integral_value(rounding=rounding)
    return (units * step).quantize(step)


def format_decimal(value: Decimal) -> str:
    """Borsaya gönderilecek sayıyı bilimsel gösterim olmadan yazar (1E+1 değil 10)."""
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


class SymbolInfo(msgspec.Struct, frozen=True, kw_only=True):
    """Bir işlem çiftinin borsa kuralları (exchangeInfo filtrelerinden türetilir)."""

    market: Market
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal

    def quantize_price(self, price: Decimal, *, side: Side) -> Decimal:
        """Fiyatı tick'e yuvarlar.

        Alış limit fiyatı aşağı, satış limit fiyatı yukarı yuvarlanır; böylece yuvarlama
        hiçbir zaman kullanıcı aleyhine daha kötü bir fiyat üretmez.
        """
        rounding = ROUND_DOWN if side is Side.BUY else ROUND_UP
        return _quantize_to_step(price, self.tick_size, rounding)

    def quantize_qty(self, qty: Decimal) -> Decimal:
        """Miktarı step'e aşağı yuvarlar (bakiyeyi asla aşmaz)."""
        return _quantize_to_step(qty, self.step_size, ROUND_DOWN)

    def validate_order(self, *, qty: Decimal, price: Decimal) -> list[str]:
        """Emrin borsa filtrelerine uyup uymadığını kontrol eder; hata listesi döner."""
        errors: list[str] = []
        if qty <= 0:
            errors.append("Miktar pozitif olmalı")
        if price <= 0:
            errors.append("Fiyat pozitif olmalı")
        if errors:
            return errors
        if qty != self.quantize_qty(qty):
            errors.append(f"Miktar step_size ({self.step_size}) katı değil")
        if (price / self.tick_size) % 1 != 0:
            errors.append(f"Fiyat tick_size ({self.tick_size}) katı değil")
        if qty < self.min_qty:
            errors.append(f"Miktar minimumun ({self.min_qty}) altında")
        if qty * price < self.min_notional:
            errors.append(f"Emir tutarı minimumun ({self.min_notional}) altında")
        return errors
