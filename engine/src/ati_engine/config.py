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

import base64
import hashlib
import ipaddress
import sys
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
    # Aşama 11 ek sınırları
    max_price_deviation_pct: Decimal = Field(default=Decimal("1.0"), gt=0, le=10)
    max_total_leverage: Decimal = Field(default=Decimal("3"), gt=0)  # toplam pozisyon / özsermaye
    maintenance_margin_rate: Decimal = Field(default=Decimal("0.01"), ge=0, lt=Decimal("0.5"))
    slippage_allowance_pct: Decimal = Field(default=Decimal("0.05"), ge=0, le=5)
    max_snapshot_age_s: float = Field(default=30.0, gt=0, le=600)
    approval_ttl_s: float = Field(default=60.0, gt=0, le=600)
    guard_interval_s: float = Field(default=5.0, gt=0, le=300)
    stream_grace_s: float = Field(default=30.0, ge=0, le=600)
    # Günlük zarar sınırında açık pozisyonları da kapat (varsayılan: kapatma; borsa tarafındaki
    # stoplar yerinde kalır, yalnızca yeni işlem durur).
    close_positions_on_daily_loss: bool = False

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
        if self.max_total_leverage > HARD_MAX_LEVERAGE:
            raise ValueError(f"Toplam kaldıraç en fazla {HARD_MAX_LEVERAGE}x olabilir")
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
    # Spot kullanıcı akışı: REST listenKey 2026-02-20'de kaldırıldı; WebSocket API aboneliği.
    spot_ws_api: str = "wss://ws-api.binance.com:443/ws-api/v3"
    # Test ortamı = Binance Demo Trading (sahte bakiye, gerçek piyasa verisi). Binance futures test
    # ağını Demo Trading'e taşıdı: testnet.binancefuture.com sitesi demo.binance.com'a yönlenir ve
    # yeni anahtarlar yalnızca demo.binance.com → API Yönetimi'nde oluşturulur. Adresler Binance
    # belgelerinden (2026-10-30): USDⓈ-M "testnet" REST demo-fapi, akış demo-fstream; Spot Demo Mode
    # REST demo-api, WebSocket API demo-ws-api. Eski test ağı anahtarı olan kullanıcı eski adresleri
    # ATI_BINANCE__* ortam değişkenleriyle verebilir (testnet.binancefuture.com,
    # testnet.binance.vision).
    spot_testnet_rest: str = "https://demo-api.binance.com"
    spot_testnet_ws_api: str = "wss://demo-ws-api.binance.com/ws-api/v3"
    futures_testnet_rest: str = "https://demo-fapi.binance.com"
    futures_testnet_ws_private: str = "wss://demo-fstream.binance.com/private"


class AutoTradeSettings(BaseModel):
    """Otomatik işlem (Aşama 11): eşik üstü fırsat sinyallerini Binance test ağında işleme
    dönüştürür. Varsayılan KAPALI; gerçek hesapla çalışmaz. Her işlem risk kapısından geçer."""

    enabled: bool = False
    markets: list[Market] = Field(default_factory=lambda: [Market.USDM_FUTURES])
    min_score: float = Field(default=70.0, ge=0, le=100)
    risk_per_trade_pct: Decimal = Field(
        default=Decimal("0.25"), gt=0, le=HARD_MAX_RISK_PER_TRADE_PCT
    )
    leverage: int = Field(default=2, ge=1, le=HARD_MAX_LEVERAGE)
    max_entries_per_hour: int = Field(default=4, ge=1, le=100)
    symbol_cooldown_s: float = Field(default=3600.0, ge=0)
    max_signal_age_s: float = Field(default=120.0, gt=0, le=3600)


PUBLIC_RELAY_URL = "wss://relay.canarslan.net.tr"


def _check_relay(value: str) -> str:
    if value.startswith("wss://"):
        return value.rstrip("/")
    loopback = ("ws://127.0.0.1", "ws://localhost", "ws://[::1]")
    if value.startswith(loopback):  # yalnızca yerel test için şifresiz
        return value.rstrip("/")
    raise ValueError("Aktarma servisi adresi wss:// ile başlamalı")


class RemoteSettings(BaseModel):
    """Uzaktan kontrol (Aşama 13): telefon ↔ aktarma servisi ↔ motor, uçtan uca imzalı.

    Kullanıcı masaüstü uygulamasında "Telefondan kontrol"ü açana kadar kapalıdır; seçim motor
    veritabanında saklanır. ``relay_url`` verilirse o servis kullanılır ve kullanıcı kapatmadıkça
    açık başlar (kendi aktarma servisi, testler). Verilmezse açıldığında ``public_relay_url``
    kullanılır. Aktarma servisi komut üretemez; yalnızca şifreli ve imzalı iletileri taşır."""

    relay_url: str | None = None
    public_relay_url: str = PUBLIC_RELAY_URL
    snapshot_interval_s: float = Field(default=15.0, ge=2, le=600)
    max_clock_skew_s: float = Field(default=120.0, ge=10, le=600)
    pairing_ttl_s: float = Field(default=300.0, ge=30, le=3600)

    @field_validator("relay_url")
    @classmethod
    def _secure_relay(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return _check_relay(value)

    @field_validator("public_relay_url")
    @classmethod
    def _secure_public_relay(cls, value: str) -> str:
        return _check_relay(value)

    @property
    def effective_relay_url(self) -> str:
        return self.relay_url or self.public_relay_url


# Canlı lisans sunucusunun (api.canarslan.net.tr) kira imza açık anahtarı. 2026-11-10'da
# ``GET /v1/licenses/signing-key`` ile alındı; kimlik, anahtarın SHA-256 özetinin ilk 16
# karakteridir (doğrulayıcı aşağıda). Sunucunun anahtarı değişirse yeni sürüm çıkarılmalıdır.
PRODUCTION_LICENSE_KEYS = {"73301409473f0267": "fRiURwqgi6+JvVpB3ngv2LEGWExGhasGyK7z9kjY8VA="}


def is_release_build() -> bool:
    """Kurulum paketindeki (PyInstaller) motor mu? Kaynaktan çalıştırmada (geliştirme, test)
    yanlıştır."""
    return bool(getattr(sys, "frozen", False))


class NotifySettings(BaseModel):
    """Bildirimler. Telegram adresi yalnızca testlerde değiştirilir."""

    telegram_api: str = "https://api.telegram.org"

    @field_validator("telegram_api")
    @classmethod
    def _secure_telegram(cls, value: str) -> str:
        if value.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            return value.rstrip("/")
        raise ValueError("Telegram adresi https:// ile başlamalı")


class LicenseSettings(BaseModel):
    """Lisans (Aşama 15). Kira, buluttaki lisans servisinin Ed25519 anahtarıyla imzalanır;
    güvenilir açık anahtar(lar) sürüme gömülür.

    Kurulum paketinde (``is_release_build``) lisans **her zaman zorunludur** ve yalnızca
    ``PRODUCTION_LICENSE_KEYS`` güvenilir sayılır; ortam değişkeni ya da ayar dosyasıyla
    kapatılamaz (bkz. ``EngineSettings._release_license``). Kaynaktan çalıştırmada (geliştirme,
    testler) varsayılan kapalıdır."""

    server_url: str = "https://api.canarslan.net.tr"
    # kid -> base64 Ed25519 açık anahtarı (``ati-cloud-license public-key`` çıktısı).
    trusted_keys: dict[str, str] = Field(default_factory=dict)
    # Açıkken geçerli kira olmadan yeni işlem açılmaz ve telefon sınırı uygulanır.
    enforce: bool = False
    renew_interval_s: float = Field(default=6 * 3600.0, ge=60, le=24 * 3600)
    retry_interval_s: float = Field(default=300.0, ge=10, le=3600)
    request_timeout_s: float = Field(default=15.0, ge=1, le=120)
    # Parmak izi kaynağını değiştirir (testler, klonlanmış sanal makineler). Lisans paylaşımına
    # yaramaz: aynı parmak izi + farklı cihaz anahtarı diğer kurulumun kirasını geçersiz kılar.
    fingerprint_override: str | None = None

    @field_validator("server_url")
    @classmethod
    def _secure_server(cls, value: str) -> str:
        if value.startswith(("https://", "http://127.0.0.1", "http://localhost", "http://[::1]")):
            return value.rstrip("/")
        raise ValueError("Lisans sunucusu adresi https:// ile başlamalı")

    @field_validator("trusted_keys")
    @classmethod
    def _valid_keys(cls, value: dict[str, str]) -> dict[str, str]:
        for kid, public in value.items():
            raw = base64.b64decode(public, validate=True)
            if len(raw) != 32 or hashlib.sha256(raw).hexdigest()[:16] != kid:
                raise ValueError(f"Geçersiz kira anahtarı: {kid}")
        return value

    @model_validator(mode="after")
    def _enforce_needs_keys(self) -> Self:
        if self.enforce and not self.trusted_keys:
            raise ValueError("Lisans zorunluluğu için en az bir güvenilir kira anahtarı gerekir")
        return self


class ExecutionSettings(BaseModel):
    """Emir yürütme (Aşama 10). Gerçek hesap (LIVE) bu sürümde kilitlidir; yürütücü yalnızca
    Binance test ağında, kullanıcı test ağı anahtarını girdiğinde çalışır."""

    testnet_enabled: bool = True  # test ağı anahtarı kayıtlıysa yürütücü kurulur
    markets: list[Market] = Field(default_factory=lambda: [Market.USDM_FUTURES, Market.SPOT])
    fill_timeout_s: float = Field(default=30.0, gt=0, le=300)
    reconcile_interval_s: float = Field(default=60.0, ge=5, le=3600)
    unknown_order_grace_s: float = Field(default=60.0, ge=0, le=3600)
    recv_window_ms: int = Field(default=5000, ge=1000, le=60_000)


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
    # Stabil coin / fiat tabanlı pariteler (ör. USDCUSDT) işlem fırsatı taşımaz; evrene alınmaz.
    excluded_base_assets: list[str] = Field(
        default_factory=lambda: [
            "USDC",
            "FDUSD",
            "TUSD",
            "USDP",
            "DAI",
            "USDS",
            "USDE",
            "USDEB",
            "USD1",
            "RLUSD",
            "BFUSD",
            "XUSD",
            "RWUSD",
            "PYUSD",
            "BUSD",
            "EUR",
            "EURI",
            "AEUR",
        ]
    )

    @field_validator("kline_intervals")
    @classmethod
    def _valid_intervals(cls, value: list[str]) -> list[str]:
        allowed = {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}
        bad = [v for v in value if v not in allowed]
        if bad:
            raise ValueError(f"Geçersiz mum aralığı: {bad}")
        return value

    @field_validator("focus_symbols", "symbol_allowlist", "excluded_base_assets")
    @classmethod
    def _upper(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [v.strip().upper() for v in value if v.strip()]


class ScannerSettings(BaseModel):
    """Coin tarama sistemi (Aşama 3) eşikleri.

    Z-skorlar sembolün kendi geçmişine göredir: BTC için %1'lik hareket olağanüstü olabilirken
    küçük bir coin için sıradandır. Tüm tutarlar kote varlık (USDT) cinsindendir.
    """

    enabled: bool = True
    baseline_minutes: int = Field(default=240, ge=30, le=1440)
    min_baseline_minutes: int = Field(default=30, ge=10)
    warmup: bool = True  # açılışta son ``baseline_minutes`` mumu REST'ten yükle
    volume_z_threshold: float = Field(default=4.0, gt=0)
    volume_min_quote: float = Field(default=50_000, ge=0)
    price_z_threshold: float = Field(default=5.0, gt=0)
    price_min_move_pct: float = Field(default=1.0, ge=0)
    imbalance_threshold: float = Field(default=0.6, gt=0, le=1)
    imbalance_min_quote: float = Field(default=100_000, ge=0)
    liquidity_drop_pct: float = Field(default=50.0, gt=0, lt=100)
    signal_cooldown_s: float = Field(default=300.0, ge=0)
    tick_interval_s: float = Field(default=1.0, gt=0, le=10)


class ScoringSettings(BaseModel):
    """Fırsat puanı (Aşama 7). Puan tek başına emir üretmez."""

    enabled: bool = True
    interval: Literal["15m", "30m", "1h", "2h", "4h"] = "1h"
    horizon_bars: int = Field(default=4, ge=1, le=100)
    warmup_bars: int = Field(default=300, ge=220, le=1000)
    publish_min_score: float = Field(default=60.0, ge=0, le=100)
    weights: dict[str, float] = Field(default_factory=dict)
    spot_taker_fee: float = Field(default=0.001, ge=0, le=0.01)
    futures_taker_fee: float = Field(default=0.0005, ge=0, le=0.01)
    notional_usd: float = Field(default=1_000.0, gt=0)
    # {"spot": {"long": "<model kimliği>", "short": "<model kimliği>"}}
    models: dict[str, dict[str, str]] = Field(default_factory=dict)


class PaperSettings(BaseModel):
    """Sanal işlem yarışması (Aşama 9). Gerçek emir göndermez."""

    enabled: bool = True
    initial_equity: float = Field(default=10_000.0, gt=0)
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.05)
    max_positions: int = Field(default=5, ge=1, le=50)
    max_hold_bars: int = Field(default=24, ge=1, le=10_000)
    futures_leverage: float = Field(default=1.0, ge=1.0, le=5.0)
    score_threshold: float = Field(default=65.0, ge=0, le=100)
    min_quote_volume_24h: float = Field(default=20_000_000.0, ge=0)
    min_notional: float = Field(default=10.0, gt=0)
    # Hedef uzaklığı, tahmini gidiş-dönüş maliyetin en az bu katı olmalı.
    min_target_cost_ratio: float = Field(default=2.0, ge=0)
    competitors: list[str] = Field(default_factory=list)  # boş: tüm stratejiler + puan


class HistorySettings(BaseModel):
    """Tarihsel veri (Aşama 5): Binance arşivi + DuckDB deposu."""

    enabled: bool = True
    download_concurrency: int = Field(default=6, ge=1, le=16)


class OnchainSettings(BaseModel):
    """Zincir üstü büyük transfer izleme. Varsayılan KAPALI (onay kapısı G4: sağlayıcı seçimi)."""

    enabled: bool = False
    provider: Literal["blockchair_ethereum"] = "blockchair_ethereum"
    min_usd: float = Field(default=5_000_000, ge=0)
    interval_s: float = Field(default=120.0, ge=30)
    labels_file: Path | None = None  # {zincir: {adres: borsa}} JSON dosyası


class WhaleSettings(BaseModel):
    """Balina radarı (Aşama 4). Tutarlar kote varlık (USDT) cinsindendir."""

    enabled: bool = True
    spot_floor_usd: float = Field(default=50_000, gt=0)
    futures_floor_usd: float = Field(default=100_000, gt=0)
    quantile: float = Field(default=0.999, gt=0.9, lt=1)
    min_samples: int = Field(default=2_000, ge=100)
    mega_multiple: float = Field(default=5.0, ge=1)
    mega_min_usd: float = Field(default=1_000_000, ge=0)
    cluster_window_s: int = Field(default=300, ge=30)
    cluster_min_count: int = Field(default=3, ge=2)
    cluster_min_usd: float = Field(default=500_000, ge=0)
    wall_levels: int = Field(default=50, ge=10, le=500)
    wall_multiple: float = Field(default=8.0, ge=2)
    spot_wall_min_usd: float = Field(default=250_000, ge=0)
    futures_wall_min_usd: float = Field(default=500_000, ge=0)
    wall_max_distance_pct: float = Field(default=2.0, gt=0, le=20)
    wall_min_lifetime_s: float = Field(default=5.0, ge=1)
    liquidation_min_usd: float = Field(default=100_000, ge=0)
    cascade_window_s: int = Field(default=60, ge=10)
    cascade_min_usd: float = Field(default=1_000_000, ge=0)
    cascade_min_count: int = Field(default=3, ge=2)
    positioning: bool = True
    positioning_interval_s: float = Field(default=300.0, ge=60)
    positioning_top_n: int = Field(default=20, ge=1, le=100)
    positioning_shift_pts: float = Field(default=5.0, gt=0)
    alert_cooldown_s: float = Field(default=300.0, ge=0)
    onchain: OnchainSettings = Field(default_factory=OnchainSettings)


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
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    whales: WhaleSettings = Field(default_factory=WhaleSettings)
    history: HistorySettings = Field(default_factory=HistorySettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    paper: PaperSettings = Field(default_factory=PaperSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    autotrade: AutoTradeSettings = Field(default_factory=AutoTradeSettings)
    remote: RemoteSettings = Field(default_factory=RemoteSettings)
    license: LicenseSettings = Field(default_factory=LicenseSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)

    @model_validator(mode="after")
    def _release_license(self) -> Self:
        """Kurulum paketinde lisans zorunluluğu ve güvenilir anahtar değiştirilemez: aksi hâlde
        ortam değişkeniyle kapatılabilir ya da sahte bir lisans sunucusunun anahtarı
        eklenebilirdi."""
        if is_release_build():
            self.license = self.license.model_copy(
                update={"enforce": True, "trusted_keys": dict(PRODUCTION_LICENSE_KEYS)}
            )
        return self

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
