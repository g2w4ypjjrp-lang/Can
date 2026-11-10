"""Bulut servisi ayarları (ortam değişkenleri, ``ATI_`` önekli).

Gizli değerler (veritabanı parolası, lisans anahtarı "pepper"ı, ödeme sağlayıcı
anahtarları) yönetilen bir gizli bilgi deposundan (ör. AWS Secrets Manager / GCP Secret
Manager) ortam değişkeni olarak enjekte edilir; depoya asla yazılmaz.
"""

from __future__ import annotations

from typing import Literal, Self

from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SslMode = Literal["verify-full", "verify-ca", "require"]


def effective_dsn(dsn: str, sslmode: str | None) -> str:
    """Bağlantı adresi + (verilirse) TLS kipi. Yönetilen platformlar bağlantı adresini hazır verir;
    kip ayrı ayarla eklenir (adres değiştirilmeden)."""
    return dsn if sslmode is None else make_conninfo(dsn, sslmode=sslmode)


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATI_", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: SecretStr
    # Veritabanı TLS kipi (bağlantı adresindekinin yerine geçer). Üretimde sertifika doğrulamalı
    # TLS (verify-full) zorunludur. Yönetilen platformun özel ağında sunucu sertifikası kendinden
    # imzalıysa (ör. Render iç bağlantısı) "require" yalnızca burada açıkça seçilerek
    # kullanılabilir: trafik şifrelidir, sunucu kimliği doğrulanmaz (docs/06, kalan riskler).
    database_sslmode: SslMode | None = None
    # Süreç başına veritabanı bağlantı havuzu (yük testine göre ayarlanır; docs/05 Aşama 18).
    database_pool_max: int = Field(default=10, ge=2, le=100)
    # Web sitesi (Aşama 14): oturum çerezini kullanan istekler yalnızca bu kökenlerden kabul edilir.
    web_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    public_web_url: str = "http://localhost:3000"
    session_cookie_secure: bool = True
    session_days: int = 30
    # İstemci adresini X-Forwarded-For'dan almaya yetkili vekiller (yük dengeleyici).
    trusted_proxies: list[str] = ["127.0.0.1"]
    # İç adresleri bilinmeyen yük dengeleyici arkasında (yönetilen platform): önündeki vekil
    # sayısı. 0 değilse istemci adresi X-Forwarded-For'un sağdan bu kadarıncı değeridir; istemcinin
    # eklediği soldaki (sahte olabilecek) değerler yok sayılır. 0 ise ATI_TRUSTED_PROXIES geçerli.
    forwarded_hops: int = Field(default=0, ge=0, le=5)

    # Lisans sistemi (Aşama 15). Gizli değerler base64; gizli bilgi deposundan verilir.
    # Üretmek için: ``uv run ati-cloud-license gen-secrets``.
    license_pepper: SecretStr | None = None  # anahtar arama özeti (HMAC), >= 32 bayt
    license_kek: SecretStr | None = None  # anahtar şifreleme ana anahtarı (AES-256), 32 bayt
    license_kek_id: str = "local-1"  # KMS'e geçişte anahtar sürümü
    lease_signing_key: SecretStr | None = None  # kira imza anahtarı (Ed25519), 32 bayt
    lease_ttl_s: int = 24 * 3600  # kira geçerliliği; motor 6 saatte bir yeniler
    lease_offline_s: int = 72 * 3600  # sunucuya ulaşılamazsa tolerans (kira başlangıcından)
    device_resets_per_30d: int = 3  # müşterinin panelden kaldırabileceği cihaz sayısı (30 gün)
    max_request_skew_s: int = 300  # motor isteklerinde izin verilen saat farkı

    # Yönetici paneli (Aşama 16): ayrı alt alan adı, ayrı oturum, zorunlu 2FA.
    admin_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    admin_public_url: str = "http://localhost:3000"  # davet bağlantıları (üretim: admin. alt alanı)
    admin_session_hours: int = Field(default=8, ge=1, le=12)
    admin_secret_kek: SecretStr | None = (
        None  # TOTP sırları ve ödeme anahtarları (AES-256), 32 bayt
    )
    # Canlı ödeme yalnızca bu dağıtım ayarı açıkken (G3 onayı) ve panelde açık onayla açılabilir.
    payments_live_allowed: bool = False
    # Ödeme (Aşama 17): sağlayıcının tarayıcıyı geri gönderdiği ve bildirim yolladığı API adresi.
    public_api_url: str = "http://localhost:8080"
    # İndirme sayfası: Windows kurulum paketinin bulunabileceği alan adları. Yönetici paneli
    # (oturumu ele geçirilse bile) indirme bağlantısını başka bir siteye yönlendiremez.
    release_download_hosts: list[str] = ["canarslan.net.tr", "indir.canarslan.net.tr"]

    @property
    def database_dsn(self) -> str:
        return effective_dsn(self.database_url.get_secret_value(), self.database_sslmode)

    @property
    def licensing_configured(self) -> bool:
        return all((self.license_pepper, self.license_kek, self.lease_signing_key))

    @model_validator(mode="after")
    def _production_requires_tls(self) -> Self:
        if self.environment in ("staging", "production") and not self.session_cookie_secure:
            raise ValueError("staging/production ortamında oturum çerezi Secure olmalı")
        if self.environment in ("staging", "production"):
            insecure = [
                u for u in [self.public_web_url, *self.web_origins] if not u.startswith("https://")
            ]
            if insecure:
                raise ValueError(
                    "staging/production ortamında site adresi ve izinli kökenler HTTPS olmalı: "
                    + ", ".join(insecure)
                )
            admin_insecure = [
                u
                for u in [self.admin_public_url, *self.admin_origins, self.public_api_url]
                if not u.startswith("https://")
            ]
            if admin_insecure:
                raise ValueError(
                    "staging/production ortamında yönetici ve API adresleri HTTPS olmalı: "
                    + ", ".join(admin_insecure)
                )
            if self.admin_secret_kek is None:
                raise ValueError("staging/production ortamında ATI_ADMIN_SECRET_KEK zorunludur")
            if not self.licensing_configured:
                raise ValueError(
                    "staging/production ortamında lisans gizli değerleri zorunludur "
                    "(ATI_LICENSE_PEPPER, ATI_LICENSE_KEK, ATI_LEASE_SIGNING_KEY)"
                )
            sslmode = conninfo_to_dict(self.database_dsn).get("sslmode")
            private_network = sslmode == "require" and self.database_sslmode == "require"
            if sslmode not in ("verify-full", "verify-ca") and not private_network:
                raise ValueError(
                    "staging/production ortamında veritabanı bağlantısı sertifika doğrulamalı "
                    "TLS kullanmalı (sslmode=verify-full; yönetilen platformun özel ağında "
                    "ATI_DATABASE_SSLMODE=require)"
                )
        return self
