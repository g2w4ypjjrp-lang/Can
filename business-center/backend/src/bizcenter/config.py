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
    redis_url: str = ""                  # boşsa görevler API süreci içinde çalışır (geliştirme)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
