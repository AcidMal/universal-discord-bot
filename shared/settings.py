from __future__ import annotations

import uuid
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process env for bot, API, and Alembic. See `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://bot:bot@localhost:5432/bot"
    discord_token: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""
    public_url: str = "http://localhost:5173"
    node_id: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if not settings.node_id:
        settings.node_id = str(uuid.uuid4())
    return settings
