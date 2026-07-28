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

    # Google Classroom import. Unset by default — the feature reports itself as
    # unavailable rather than failing at the first API call.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/v1/google/oauth/callback"
    # Fernet key protecting stored refresh tokens, which are live credentials to
    # a teacher's Drive. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    google_token_key: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_token_key)

    @property
    def frontend_url(self) -> str:
        """Where the OAuth callback bounces the browser back to.

        Reuses the first CORS origin, which is already the frontend in both dev
        and production, rather than adding another variable to keep in step.
        """
        origins = self.cors_origin_list
        return origins[0] if origins else "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
