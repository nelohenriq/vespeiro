from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""  # From .env: SUPABASE_URL
    supabase_service_key: str = ""  # From .env: SUPABASE_SERVICE_KEY
    database_url: str = "sqlite+aiosqlite:///data/vespeiro.db"  # Local dev fallback
    log_level: str = "INFO"
    embedding_model: str = "intfloat/multilingual-e5-large"
    scrape_interval_minutes: int = 15

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
