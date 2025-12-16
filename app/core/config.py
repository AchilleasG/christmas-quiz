from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUIZ_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Direct URL override (takes precedence if set)
    database_url: str | None = None

    # Individual DB params (used if database_url is not provided)
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "christmas_quiz"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # Keep raw string to avoid JSON parsing issues for lists
    cors_origins_raw: str = Field(default="*")
    media_root: Path = Path("media")

    @property
    def assembled_db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw
        if not raw:
            return []
        return [part.strip() for part in raw.split(",") if part.strip()]


settings = Settings()
