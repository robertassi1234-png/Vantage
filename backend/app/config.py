from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fmp_api_key: str = ""
    anthropic_api_key: str = ""
    vantage_db_path: str = "vantage.db"
    fundamentals_cache_hours: int = 24
    cors_origins: str = "http://localhost:5173"

    # Providers tried in order for quotes, history and search. Yahoo has no
    # published quota; FMP's free tier is 250 calls/day, so it sits behind as
    # the fallback. Set to "fmp" alone to disable Yahoo entirely.
    provider_order: str = "yahoo,fmp"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
