"""Motor ayarları.

Öncelik sırası (yüksekten düşüğe): kod içi parametre > ortam değişkeni (``ATI_`` önekli,
iç içe alanlar için ``__``) > ``config.toml`` > varsayılan değerler.

Bu dosyada hiçbir gizli bilgi (API anahtarı, belirteç) tutulmaz; gizli bilgiler
``security.vault`` ile şifrelenerek SQLite'ta saklanır.

Güvenli varsayılanlar:
* ``trading_mode`` = PAPER (sanal işlem).
* ``live_trading_enabled`` = False. Gerçek işlem için kullanıcının bunu ayar dosyasında
  bilerek açması *ve* çalışma anında onay ifadesini girmesi gerekir.
* Yerel API yalnızca loopback adresine bağlanabilir.
"""

from __future__ import annotations

import ipaddress
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from ati_engine.core.models import Market, TradingMode
from ati_engine.system.paths import DataPaths, default_data_dir

# Ürün seviyesinde, kullanıcı ayarıyla aşılamayan üst sınırlar.
HARD_MAX_LEVERAGE = 20
HARD_MAX_RISK_PER_TRADE_PCT = Decimal("5")
HARD_MAX_DAILY_LOSS_PCT = Decimal("20")


class RiskLimits(BaseModel):
    """Risk sınırları. Risk motoru (Aşama 11) bu değerleri işlem motorundan bağımsız uygular."""

    max_risk_per_trade_pct: Decimal = Field(default=Decimal("0.5"), gt=0)
    max_daily_loss_pct: Decimal = Field(default=Decimal("2.0"), gt=0)
    max_open_positions: int = Field(default=3, ge=1, le=50)
    max_leverage: int = Field(default=3, ge=1)
    min_liquidation_distance_pct: Decimal = Field(default=Decimal("15"), gt=0, le=100)

    @field_validator("max_risk_per_trade_pct")
    @classmethod
    def _cap_trade_risk(cls, value: Decimal) -> Decimal:
        if value > HARD_MAX_RISK_PER_TRADE_PCT:
            raise ValueError(f"İşlem başına risk en fazla %{HARD_MAX_RISK_PER_TRADE_PCT} olabilir")
        return value

    @field_validator("max_daily_loss_pct")
    @classmethod
    def _cap_daily_loss(cls, value: Decimal) -> Decimal:
        if value > HARD_MAX_DAILY_LOSS_PCT:
            raise ValueError(f"Günlük zarar sınırı en fazla %{HARD_MAX_DAILY_LOSS_PCT} olabilir")
        return value

    @field_validator("max_leverage")
    @classmethod
    def _cap_leverage(cls, value: int) -> int:
        if value > HARD_MAX_LEVERAGE:
            raise ValueError(f"Kaldıraç en fazla {HARD_MAX_LEVERAGE}x olabilir")
        return value

    @model_validator(mode="after")
    def _daily_vs_trade(self) -> Self:
        if self.max_daily_loss_pct < self.max_risk_per_trade_pct:
            raise ValueError("Günlük zarar sınırı, işlem başına riskten küçük olamaz")
        return self


class LocalApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=47821, ge=0, le=65535)  # 0 = işletim sistemi seçer (testler)
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["tauri://localhost", "http://tauri.localhost"]
    )

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value == "localhost":
            return "127.0.0.1"
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("Yerel API host'u bir IP adresi olmalı") from exc
        if not address.is_loopback:
            raise ValueError(
                "Yerel API yalnızca loopback (127.0.0.1 / ::1) adresine bağlanabilir. "
                "Uzaktan erişim bulut aktarma katmanı ve uçtan uca imzalı komutlarla yapılır."
            )
        return value


class BinanceEndpoints(BaseModel):
    """Binance uç noktaları. Adresler yapılandırılabilir; borsa adres değiştirdiğinde
    yeni sürüm beklemeden güncellenebilir.

    USDⓈ-M Futures WebSocket adresleri 2026'da /public, /market ve /private olarak
    ayrılmıştır; eski /ws ve /stream adresleri kullanılmaz.
    """

    spot_rest: str = "https://api.binance.com"
    spot_market_data_rest: str = "https://data-api.binance.vision"
    spot_ws: str = "wss://stream.binance.com:9443"
    spot_market_data_ws: str = "wss://data-stream.binance.vision"
    futures_rest: str = "https://fapi.binance.com"
    futures_ws_public: str = "wss://fstream.binance.com/public"
    futures_ws_market: str = "wss://fstream.binance.com/market"
    futures_ws_private: str = "wss://fstream.binance.com/private"
    historical_data: str = "https://data.binance.vision"
    # Test ağı adresleri Aşama 10'da Binance belgelerine göre yeniden doğrulanacak.
    spot_testnet_rest: str = "https://testnet.binance.vision"
    futures_testnet_rest: str = "https://testnet.binancefuture.com"


class MarketDataSettings(BaseModel):
    """Piyasa verisi motoru (Aşama 2).

    Katmanlar:
    * Katman 0 - pazar geneli: Spot ``!miniTicker@arr``; Futures ``!ticker@arr``,
      ``!markPrice@arr@1s``, ``!forceOrder@arr``.
    * Katman 1 - izlenen her sembol: ``@kline_<aralık>`` ve (açıksa) ``@aggTrade``.
    * Katman 2 - odak sembolleri: ``@depth@100ms`` + REST anlık görüntüsü ile yerel emir defteri.
    """

    enabled: bool = True
    kline_intervals: list[str] = Field(default_factory=lambda: ["1m"])
    include_agg_trades: bool = True
    streams_per_connection: int = Field(default=200, ge=1, le=1024)
    focus_symbols: list[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    )
    depth_snapshot_limit: int = Field(default=1000, ge=5, le=5000)
    discovery_interval_s: float = Field(default=300.0, ge=10)
    stale_after_s: float = Field(default=30.0, ge=2)
    futures_contract_types: list[str] = Field(default_factory=lambda: ["PERPETUAL"])
    symbol_allowlist: list[str] | None = None
    max_symbols: int | None = Field(default=None, ge=1)

    @field_validator("kline_intervals")
    @classmethod
    def _valid_intervals(cls, value: list[str]) -> list[str]:
        allowed = {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ValueError(f"Geçersiz mum aralığı: {bad}")
        return value

    @field_validator("focus_symbols", "symbol_allowlist")
    @classmethod
    def _upper(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [v.strip().upper() for v in value if v.strip()]


class EngineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATI_",
        env_nested_delimiter="__",
        extra="forbid",
        validate_default=True,
    )

    data_dir: Path = Field(default_factory=default_data_dir)
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    markets: list[Market] = Field(default_factory=lambda: [Market.SPOT, Market.USDM_FUTURES])
    quote_asset: str = "USDT"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    log_to_console: bool = True

    heartbeat_interval_s: float = Field(default=1.0, gt=0, le=60)
    loop_lag_warning_ms: float = Field(default=250.0, gt=0)

    risk: RiskLimits = Field(default_factory=RiskLimits)
    api: LocalApiSettings = Field(default_factory=LocalApiSettings)
    binance: BinanceEndpoints = Field(default_factory=BinanceEndpoints)
    market_data: MarketDataSettings = Field(default_factory=MarketDataSettings)

    @property
    def paths(self) -> DataPaths:
        return DataPaths(self.data_dir)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_file = _resolve_config_file(init_settings, env_settings)
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if toml_file is not None:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_file))
        return tuple(sources)


def _resolve_config_file(
    init_settings: PydanticBaseSettingsSource, env_settings: PydanticBaseSettingsSource
) -> Path | None:
    data_dir = init_settings().get("data_dir") or env_settings().get("data_dir")
    root = Path(data_dir) if data_dir else default_data_dir()
    candidate = DataPaths(root).config_file
    return candidate if candidate.is_file() else None


def redacted_settings_dump(settings: EngineSettings) -> dict[str, object]:
    """Loglanabilir ayar özeti (ayarlarda gizli bilgi yoktur; yine de yalnızca JSON uyumlu)."""
    return settings.model_dump(mode="json")
