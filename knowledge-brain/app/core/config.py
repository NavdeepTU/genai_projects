from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the app, loaded from environment variables.

    We read these from the environment (via a .env file locally) instead
    of hardcoding them so the same code can run in dev, tests, and
    production with different secrets/URLs — and so no secret ever
    gets committed to git.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str

    # Embedding provider
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"

    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50


@lru_cache
def get_settings() -> Settings:
    """Return the app's Settings, reading the environment only once.

    lru_cache means the first call reads and validates the environment,
    and every call after that reuses the same object instead of
    re-reading .env from disk each time.
    """
    return Settings()
