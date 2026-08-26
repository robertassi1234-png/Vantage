from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    fmp_api_key: str = ""
    anthropic_api_key: str = ""
    vantage_db_path: str = "vantage.db"
    fundamentals_cache_hours: int = 24


settings = Settings()
