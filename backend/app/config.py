from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "IGCSE Student Operating System"
    database_url: str = "postgresql+asyncpg://igcse:igcse@localhost:5432/igcse"

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg(cls, v: str) -> str:
        # Hosting providers (e.g. Render) hand out postgres:// URLs; the async
        # SQLAlchemy engine needs the asyncpg driver spelled out.
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"
    upload_dir: str = "uploads"
    cors_origins: str = "http://localhost:5173"
    # Disable only for plain-HTTP local dev/tests; production (HTTPS) should keep this True.
    refresh_cookie_secure: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
