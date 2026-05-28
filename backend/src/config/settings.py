from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""  # From .env: SUPABASE_URL
    supabase_service_key: str = ""  # From .env: SUPABASE_SERVICE_KEY
    database_url: str = "sqlite+aiosqlite:///data/vespeiro.db"  # Local dev fallback
    log_level: str = "INFO"
    embedding_model: str = "intfloat/multilingual-e5-large"
    scrape_interval_minutes: int = 15

    # Google Custom Search API (DRE scraper)
    # Free tier: 100 queries/day — sufficient for weekly DRE checks
    google_api_key: str = ""  # From .env: GOOGLE_API_KEY
    google_custom_search_cx: str = ""  # From .env: GOOGLE_CUSTOM_SEARCH_CX

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
