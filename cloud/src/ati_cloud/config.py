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

    @model_validator(mode="after")
    def _production_requires_tls(self) -> Self:
        if self.environment in ("staging", "production") and not self.session_cookie_secure:
            raise ValueError("staging/production ortamında oturum çerezi Secure olmalı")
        if self.environment in ("staging", "production"):
            url = urlparse(self.database_url.get_secret_value())
            sslmode = parse_qs(url.query).get("sslmode", [""])[0]
            if sslmode not in ("verify-full", "verify-ca"):
                raise ValueError(
                    "staging/production ortamında veritabanı bağlantısı sertifika doğrulamalı "
                    "TLS kullanmalı (sslmode=verify-full)"
                )
        return self
