import re

from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalise_origin(origin: str) -> str:
    origin = origin.strip().rstrip("/")
    if origin and "://" not in origin:
        origin = f"https://{origin}"
    return origin


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
    # Resend over HTTPS. Preferred on hosting that blocks outbound SMTP ports
    # to deter spam -- which most free tiers do, and where SMTP simply times
    # out. Port 443 is never blocked, so this works where SMTP cannot.
    resend_api_key: str = ""

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
        """Exact origins allowed to call the API.

        A bare hostname is read as https, because that is what someone pastes
        when they copy their site's address out of a hosting dashboard.
        Wildcard entries are handled by `cors_origin_regex` instead.
        """
        if self.cors_origins.strip() == "*":
            return ["*"]

        origins = []
        for origin in self.cors_origins.split(","):
            origin = _normalise_origin(origin)
            if origin and "*" not in origin:
                origins.append(origin)
        return origins

    @property
    def cors_origin_regex(self) -> str | None:
        """Pattern for wildcard entries like `https://*.onrender.com`.

        Hosting providers hand out generated subdomains, and a preview deploy
        gets a different one each time. Matching a pattern keeps credentials
        working there without opening the API to every origin on the internet,
        which is what a bare `*` would do.
        """
        if self.cors_origins.strip() == "*":
            return None

        patterns = []
        for origin in self.cors_origins.split(","):
            origin = _normalise_origin(origin)
            if not origin or "*" not in origin:
                continue
            # A `*` stands for one label, so `*.example.com` cannot also match
            # `evil.com.example.com.attacker.net`.
            patterns.append(re.escape(origin).replace(r"\*", r"[^./]+"))

        return "|".join(patterns) if patterns else None

    @property
    def allows_credentialed_cors(self) -> bool:
        """Whether signed-in requests can be made from another origin.

        Cookies plus a wildcard origin would let any website on the internet
        read and change a signed-in reader's watchlist, so the two are never
        combined: naming the site explicitly is what turns sign-in on.
        """
        return self.cors_origin_list != ["*"]

    @property
    def cors_summary(self) -> str:
        """What the API will accept, for the boot log."""
        named = self.cors_origin_list + ([self.cors_origin_regex] if self.cors_origin_regex else [])
        return ", ".join(n for n in named if n) or "(none)"


settings = Settings()
