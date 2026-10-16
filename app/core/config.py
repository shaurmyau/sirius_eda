"""Настройки из .env (pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    SECRET_KEY: str = "dev-secret-change-me"
    DATABASE_URL: str = "postgresql+psycopg2://sirius:sirius@localhost:5432/sirius_food"
    REDIS_URL: str = "redis://localhost:6379"
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RATE_LIMIT_ENABLED: bool = True


settings = Settings()
