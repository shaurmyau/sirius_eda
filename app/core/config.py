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
    REPO_BACKEND: str = "postgres"

    # gRPC-микросервис delivery (Практическая работа № 6)
    DELIVERY_GRPC_HOST: str = "localhost"
    DELIVERY_GRPC_PORT: int = 50051
    DELIVERY_GRPC_TIMEOUT: float = 5.0
    # "grpc" | "sql" | "memory" — что использовать для delivery
    DELIVERY_BACKEND: str = "grpc"

    # RabbitMQ (Практическая работа № 7)
    RABBITMQ_URL: str = "amqp://sirius:sirius@localhost:5672/"

    # Кеширование (ЛР №4)
    CACHE_MENU_ALL_TTL: int = 300
    CACHE_MENU_CATEGORY_TTL: int = 600
    CACHE_STAMPEDE_LOCK_TIMEOUT: int = 10
    CACHE_STAMPEDE_WAIT_TIMEOUT: float = 5.0
    CACHE_STAMPEDE_RETRY_INTERVAL: float = 0.1


settings = Settings()
