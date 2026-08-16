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

    # --- LLM provider selection ---
    # "claude" (default), "openai", or "gemini" — set the matching key below.
    # Gemini has a free tier: get a key at aistudio.google.com.
    llm_provider: str = "claude"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # --- Local models via Ollama (ARIA 2.0 model router) ---
    # Empty model name = that local tier is disabled.
    ollama_base_url: str = "http://localhost:11434"
    ollama_fast_model: str = "llama3.2:3b"      # routine work: classify, extract, summarise
    ollama_reasoning_model: str = ""            # optional bigger local model
    # When true, prefer local models even for REASON-class tasks (free + private,
    # at some quality cost). When false, REASON prefers cloud.
    prefer_local: bool = False
    # Chat and drafting on a local model: free and fully private, but a small
    # local model is noticeably weaker than a cloud one. Set false to send
    # conversation to the cloud provider instead. This is the single most
    # user-visible routing choice, so it gets its own switch.
    converse_local: bool = True

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

    # --- OpenClaw bridge (WhatsApp ingest) ---
    # Shared secret OpenClaw must present on the ingest webhook. Empty =
    # ingest disabled, so a misconfigured deployment fails closed rather
    # than accepting messages from any local process.
    openclaw_ingest_secret: str = ""

    # --- Inbound queue worker ---
    # The background drain that retries messages whose processing failed and
    # recovers anything left behind by a crash. Disabled in tests, which drive
    # the queue explicitly so behaviour is deterministic rather than timed.
    whatsapp_worker_enabled: bool = True
    whatsapp_worker_poll_seconds: float = 2.0

    # --- Proactive engine ---
    # ARIA noticing things without being asked. Five minutes is frequent
    # enough to catch a stalled queue while it still matters, and rare enough
    # that the checks cost nothing. Disabled in tests, which run them
    # explicitly so behaviour is deterministic rather than timed.
    proactive_enabled: bool = True
    proactive_interval_seconds: float = 300.0

    # --- Incoming email via IMAP (read-only inbox) ---
    # Gmail: imap.gmail.com, same address + App Password as SMTP.
    imap_host: str = ""
    imap_port: int = 993

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (cached so .env is parsed only once)."""
    return Settings()
