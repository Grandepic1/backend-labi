from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "backend-labi"
    APP_ENV: str = "development"  # development | production
    DEBUG: bool = True

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() == "production"

    @property
    def debug_mode(self) -> bool:
        """Effective debug flag — always off in production."""
        return self.DEBUG and not self.is_production

    @property
    def sql_echo(self) -> bool:
        """SQL statement logging — dev only, never in production."""
        return self.debug_mode

    @property
    def docs_url(self) -> str | None:
        return None if self.is_production else "/docs"

    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    # CORS — list your frontend domains here (comma-separated in .env):
    # FRONTEND_URLS=http://localhost:3000,https://app.example.com
    # Kept as a plain string because pydantic-settings JSON-decodes
    # list-typed env values before validators run; use cors_origins.
    FRONTEND_URLS: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        v = self.FRONTEND_URLS.strip()
        if v.startswith("["):
            import json

            return [str(o).rstrip("/") for o in json.loads(v)]
        return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]

    # Auth (JWT)
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # MySQL connection parts (matches existing .env keys)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "labi"

    # Full URL override, e.g. mysql+asyncmy://user:pass@host:3306/db
    # (a +pymysql URL is accepted too and converted as needed)
    DATABASE_URL: str | None = None

    def _auth(self) -> str:
        password = quote_plus(self.DB_PASSWORD) if self.DB_PASSWORD else ""
        if password:
            return f"{self.DB_USERNAME}:{password}@"
        return f"{self.DB_USERNAME}@" if self.DB_USERNAME else ""

    @property
    def sqlalchemy_database_url(self) -> str:
        """Sync URL (pymysql) — used by Alembic."""
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+asyncmy://", "+pymysql://")
        return (
            f"mysql+pymysql://{self._auth()}"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def sqlalchemy_async_url(self) -> str:
        """Async URL (asyncmy) — used by the FastAPI app."""
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+pymysql://", "+asyncmy://")
        return (
            f"mysql+asyncmy://{self._auth()}"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
