from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""  # From .env: SUPABASE_URL
    supabase_service_key: str = ""  # From .env: SUPABASE_SERVICE_KEY
    database_url: str = "sqlite+aiosqlite:///data/vespeiro.db"  # Local dev fallback
    log_level: str = "INFO"
    embedding_model: str = "intfloat/multilingual-e5-large"
    scrape_interval_minutes: int = 15

    # Exa Search API (DRE spider — appointment discovery, primary)
    # Free tier: 1,000 requests/month
    exa_api_key: str = ""  # From .env: EXA_API_KEY

    # Tavily Search API (DRE spider — appointment discovery, fallback)
    # Free tier: 1,000 credits/month
    tavily_api_key: str = ""  # From .env: TAVILY_API_KEY

    # Telegram bot (Jornal do Contra alerts)
    telegram_bot_token: str = ""  # From .env: TELEGRAM_BOT_TOKEN
    telegram_chat_id: str = ""  # From .env: TELEGRAM_CHAT_ID

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
