from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./sti.db"
    auth_secret: str = "development-only-change-me"
    cookie_secure: bool = False
    explanation_url: str | None = None
    explanation_model: str = "local-model"

    model_config = SettingsConfigDict(env_prefix="STI_", env_file=".env.local")


@lru_cache
def get_settings() -> Settings:
    return Settings()
