"""Application configuration.

All settings come from environment variables (loaded from the `.env` file in
the repo root during development). This is the ONLY place in the codebase that
reads the environment — everything else imports `settings` from here, so there
is a single source of truth and no secret is ever hard-coded.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file lives at the repo root (two levels above apps/api).
_ENV_FILE = Path(__file__).resolve().parents[3].parent / ".env"


class Settings(BaseSettings):
    """Typed application settings.

    Each field is validated on startup: if a required value is missing or has
    the wrong type, the app fails loudly at boot instead of mysteriously later.
    """

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://aria:aria_dev_password@localhost:5432/aria"
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM provider selection (Phase 5) ---
    # "claude" (default) or "openai" — set the matching API key below.
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.1"

    # --- Auth (Phase 4) ---
    # If aria_password is empty, auth is DISABLED (local dev mode).
    # Set both in .env to require login.
    aria_password: str = ""
    secret_key: str = "dev-only-secret-change-me"  # signs JWTs; override in .env

    # --- Outgoing email via SMTP (Phase 4) ---
    # For Gmail: smtp.gmail.com / 587 / your address / an App Password
    # (Google account -> Security -> 2-Step Verification -> App passwords).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""

    # --- Incoming email via IMAP (read-only inbox) ---
    # Gmail: imap.gmail.com, same address + App Password as SMTP.
    imap_host: str = ""
    imap_port: int = 993

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (cached so .env is parsed only once)."""
    return Settings()
