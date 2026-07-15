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
    # Browser-side key for the /r/ Payment Element island. Not a
    # secret and cannot move money; still env-configured, never
    # hardcoded.
    stripe_publishable_key: str = ""
    # The planner's Stripe Connect (Standard) CONNECTED account —
    # the account that RECEIVES the group's money (destination
    # charges point transfer_data.destination at it). NOT the
    # platform's own account id: Stripe rejects a destination of
    # self. Test-mode acct for the demo; live acct at dogfood.
    planner_account_id: str = ""
    # Gate for the public create-event page: on a deployed host,
    # event creation routes real money into the planner's Stripe,
    # so strangers must not mint events. Unset = creation refused
    # (fail closed).
    create_password: str = ""


def get_settings() -> Settings:
    # Read lazily so tests can patch the environment first
    return Settings()
