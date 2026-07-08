"""App settings, loaded from the environment / .env.

Secrets stay out of code; .env is gitignored. Precedence is
pydantic-settings' own: real env vars beat the .env file — the
test suite relies on that to blank credentials. The .env path is
anchored to the repo root so the app behaves the same regardless
of the working directory it was launched from.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, extra="ignore"
    )

    database_url: str = (
        "postgresql+asyncpg://localhost:5432/knowaplan"
    )
    stripe_secret_key: str = ""
    test_planner_account_id: str = ""


def get_settings() -> Settings:
    # Read lazily so tests can patch the environment first
    return Settings()
