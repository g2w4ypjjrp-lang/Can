from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Tüm gizli bilgiler ortam değişkenlerinden okunur; koda veya frontend'e girmez."""

    model_config = SettingsConfigDict(env_prefix="BC_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = Field(..., description="Supabase Postgres bağlantısı (pooler)")
    supabase_url: str = ""
    supabase_jwt_secret: str = ""  # eski HS256 projeleri için; boşsa JWKS kullanılır
    supabase_jwt_audience: str = "authenticated"
    cors_origins: list[str] = ["http://localhost:3000"]
    rate_limit_per_minute: int = 120
    db_pool_max: int = 10

    # --- AI çekirdeği ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    max_task_cost_usd: float = 2.0       # tek görevin harcayabileceği üst sınır
    max_active_tasks_per_org: int = 3    # eşzamanlı görev sınırı (kontrolsüz harcamayı önler)
    max_web_searches_per_call: int = 5
    inline_scheduler: bool = False      # Redis yokken zamanlayıcıyı API süreci içinde çalıştır (geliştirme)
    redis_url: str = ""                  # boşsa görevler API süreci içinde çalışır (geliştirme)


    etsy_keystring: str = ""                  # Etsy uygulama anahtarı (keystring)
    etsy_shared_secret: str = ""              # Etsy bunu x-api-key'de istiyorsa "keystring:secret" olarak gönderilir
    etsy_redirect_uri: str = ""               # ör. https://panel.ornek.com/integrations/etsy/callback

    @property
    def etsy_api_key(self) -> str:
        return f"{self.etsy_keystring}:{self.etsy_shared_secret}" if self.etsy_shared_secret else self.etsy_keystring

    google_client_id: str = ""                # Google Cloud > OAuth istemcisi (Web uygulaması)
    google_client_secret: str = ""
    youtube_redirect_uri: str = ""            # ör. https://panel.ornek.com/integrations/youtube/callback

    token_encryption_key: str = ""           # Fernet anahtarı; üretmek: python -m bizcenter.integrations.keygen
    task_timeout_minutes: int = 30           # bu süreden uzun "çalışıyor" kalan görev başarısız sayılır

    def production_problems(self) -> list[str]:
        """Production'da güvenli olmayan ayarları listeler (boşsa sorun yok)."""
        if self.environment != "production":
            return []
        p: list[str] = []
        if not self.supabase_url and not self.supabase_jwt_secret:
            p.append("BC_SUPABASE_URL (veya BC_SUPABASE_JWT_SECRET) gerekli")
        if self.supabase_url and not self.supabase_url.startswith("https://"):
            p.append("BC_SUPABASE_URL https:// ile başlamalı")
        if self.supabase_jwt_secret and len(self.supabase_jwt_secret) < 32:
            p.append("BC_SUPABASE_JWT_SECRET en az 32 karakter olmalı")
        if any(o == "*" or "localhost" in o or o.startswith("http://") for o in self.cors_origins):
            p.append("BC_CORS_ORIGINS yalnızca https:// alan adlarını içermeli")
        if not self.redis_url:
            p.append("BC_REDIS_URL gerekli (görevler çalışan süreçlerde yürütülür)")
        if not self.token_encryption_key:
            p.append("BC_TOKEN_ENCRYPTION_KEY gerekli (entegrasyon tokenları şifrelenir)")
        if self.inline_scheduler:
            p.append("BC_INLINE_SCHEDULER production'da kapalı olmalı (Celery beat kullanılır)")
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
