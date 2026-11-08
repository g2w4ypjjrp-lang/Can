"""Bulut servisi ayarları (ortam değişkenleri, ``ATI_`` önekli).

Gizli değerler (veritabanı parolası, lisans anahtarı "pepper"ı, ödeme sağlayıcı
anahtarları) yönetilen bir gizli bilgi deposundan (ör. AWS Secrets Manager / GCP Secret
Manager) ortam değişkeni olarak enjekte edilir; depoya asla yazılmaz.
"""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import parse_qs, urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATI_", extra="ignore")

    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: SecretStr
    # Web sitesi (Aşama 14): oturum çerezini kullanan istekler yalnızca bu kökenlerden kabul edilir.
    web_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    public_web_url: str = "http://localhost:3000"
    session_cookie_secure: bool = True
    session_days: int = 30
    # İstemci adresini X-Forwarded-For'dan almaya yetkili vekiller (yük dengeleyici).
    trusted_proxies: list[str] = ["127.0.0.1"]

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
            if not self.licensing_configured:
                raise ValueError(
                    "staging/production ortamında lisans gizli değerleri zorunludur "
                    "(ATI_LICENSE_PEPPER, ATI_LICENSE_KEK, ATI_LEASE_SIGNING_KEY)"
                )
            url = urlparse(self.database_url.get_secret_value())
            sslmode = parse_qs(url.query).get("sslmode", [""])[0]
            if sslmode not in ("verify-full", "verify-ca"):
                raise ValueError(
                    "staging/production ortamında veritabanı bağlantısı sertifika doğrulamalı "
                    "TLS kullanmalı (sslmode=verify-full)"
                )
        return self
