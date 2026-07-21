"""Application settings (pydantic-settings).

``DATABASE_URL`` switches persistence (SQLite locally / Postgres in prod).
Secrets are :class:`SecretStr` so they cannot be printed or serialised by
accident, and the system runs fully in ``mock`` mode with ZERO providers
configured (spec §3.3, §20). LLM providers are abstracted per role (fast /
reasoning / critic / editor) and never hardcoded across the codebase.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = "development"
    app_name: str = "US Stock Watcher"
    app_version: str = "0.1.0"
    server_timezone: str = "America/New_York"

    # --- Persistence ---
    database_url: str = "sqlite+aiosqlite:///./us_watcher.db"
    redis_url: str = ""  # empty -> in-memory fakeredis (reported honestly at /health)

    # --- Market data ---
    market_data_provider: str = "yahoo"  # "yahoo" (keyless) | "mock"
    market_data_ttl_seconds: int = 60
    market_data_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # --- Macro (FRED keyless CSV by default; API key optional, unlocks ALFRED) ---
    fred_api_key: SecretStr = SecretStr("")

    # --- News ---
    news_provider: str = "google"  # "google" (keyless RSS) | "mock"
    news_retention_days: int = 21
    news_topics: list[str] = Field(
        default_factory=lambda: [
            "S&P 500 stock market",
            "Federal Reserve interest rates",
            "Nasdaq technology earnings",
            "AI semiconductor demand",
            "US Treasury yields",
        ]
    )
    # Per-stock news: additionally query Google News for the first N stock-universe
    # names (query = "<name> stock"), so the news_catalyst component can see
    # company-specific catalysts (product launches, guidance) — not just macro
    # themes. Each name is one extra RSS GET per sync; 0 disables per-stock news.
    news_stock_query_limit: int = 60

    # --- LLM provider abstraction (per role; mock when unset) ---
    agent_runtime: str = "mock"  # "mock" | "llm"
    # Concrete provider serving LLM prose when agent_runtime="llm":
    #   auto       -> anthropic when an API key is set, else claude_cli
    #   anthropic  -> Anthropic API (consumes API credits)
    #   claude_cli -> local `claude` CLI headless (billed to the owner's Claude
    #                 subscription; auth via CLAUDE_CODE_OAUTH_TOKEN or CLI login)
    #   mock       -> deterministic mock
    llm_provider: str = "auto"
    llm_reasoning_provider: str = "anthropic"
    llm_reasoning_model: str = "claude-opus-4-8"
    llm_fast_provider: str = "anthropic"
    llm_fast_model: str = "claude-haiku-4-5-20251001"
    llm_critic_provider: str = "anthropic"
    llm_critic_model: str = "claude-sonnet-4-6"
    llm_editor_provider: str = "anthropic"
    llm_editor_model: str = "claude-opus-4-8"
    anthropic_api_key: SecretStr = SecretStr("")
    agent_max_tokens: int = 2048
    agent_run_token_budget: int = 120_000

    # --- Claude Code CLI provider (subscription-billed; no API credits) ---
    claude_cli_path: str = "claude"
    # Long-lived headless token minted ONCE interactively via `claude setup-token`.
    # When empty the CLI falls back to its own stored login (if valid).
    claude_code_oauth_token: SecretStr = SecretStr("")
    # Subscription usage optimization: aliases resolve to the CLI's latest models.
    llm_cli_model: str = "sonnet"  # reasoning / critic / editor prose
    llm_cli_fast_model: str = "haiku"  # fast role
    llm_cli_timeout_seconds: int = 240

    # --- Web / HTTP ---
    # Local dev fronts (Next.js). Both 3000/3001 and localhost/127.0.0.1 so the
    # browser's origin is accepted regardless of which port/host the web uses.
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            f"http://{host}:{port}"
            for host in ("localhost", "127.0.0.1")
            for port in (3000, 3001, 3002, 3003)
        ]
    )

    # --- Operational security (protected endpoints) ---
    cron_secret: SecretStr = SecretStr("")
    admin_api_key: SecretStr = SecretStr("")
    rate_limit_per_minute: int = 120
    # Public "update now" button: minimum minutes between website-triggered runs.
    refresh_cooldown_minutes: int = 15

    # --- Notifications (optional; delivery skipped if unset) ---
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    # Public site URL used for "view full report" links in Telegram digests.
    public_base_url: str = "https://krw-watcher.tail3e31a9.ts.net:10000"
    premarket_brief_hour: int = 7
    closing_brief_hour: int = 18

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_provider_resolved(self) -> str:
        """Concrete provider after resolving ``auto``."""
        if self.llm_provider == "auto":
            return "anthropic" if self.anthropic_api_key.get_secret_value() else "claude_cli"
        return self.llm_provider

    @property
    def llm_enabled(self) -> bool:
        if self.agent_runtime != "llm":
            return False
        resolved = self.llm_provider_resolved
        if resolved == "anthropic":
            return bool(self.anthropic_api_key.get_secret_value())
        return resolved == "claude_cli"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_chat_id)

    @property
    def fred_keyed(self) -> bool:
        return bool(self.fred_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton (cached)."""
    return Settings()
