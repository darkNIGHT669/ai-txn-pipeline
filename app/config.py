from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AI Transaction Pipeline"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://txnuser:txnpass@db:5432/txndb"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://txnuser:txnpass@db:5432/txndb"

    # Redis / Celery
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/0"

    # Google Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # LLM retry config
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BASE_DELAY: float = 2.0  # seconds; doubles each retry

    # Upload
    UPLOAD_DIR: str = "/tmp/uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
