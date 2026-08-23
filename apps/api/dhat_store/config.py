from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./store.db"
    secret_key: str = "change-me"
    telegram_bot_token: str | None = None
    owner_telegram_id: int | None = None
    cors_origins: str = "http://localhost:5173"
    session_days: int = 7
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
