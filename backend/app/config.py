from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fmp_api_key: str = ""
    anthropic_api_key: str = ""
    fundamentals_cache_hours: int = 24
    cors_origins: str = "http://localhost:5173"

    # Providers tried in order for quotes, history and search. Yahoo has no
    # published quota; FMP's free tier is 250 calls/day, so it sits behind as
    # the fallback. Set to "fmp" alone to disable Yahoo entirely.
    provider_order: str = "yahoo,fmp"

    # SQLite locally so the app runs with no signups; a Postgres URL in
    # production so accounts survive restarts and redeploys.
    database_url: str = "sqlite:///vantage.db"

    # --- accounts and email ---
    # Where magic-link emails point back to.
    app_base_url: str = "http://localhost:5173"
    # Any SMTP provider works (Resend, SendGrid, Mailgun, Postmark).
    # Unset means emails are logged instead of sent, so local dev needs no key.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "Vantage <onboarding@resend.dev>"

    # Shared secret for the scheduled alert sweep, so only your cron can run it.
    cron_secret: str = ""

    magic_link_ttl_minutes: int = 20
    session_ttl_days: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
