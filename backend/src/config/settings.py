from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""  # From .env: SUPABASE_URL
    supabase_service_key: str = ""  # From .env: SUPABASE_SERVICE_KEY
    database_url: str = "sqlite+aiosqlite:///data/vespeiro.db"  # Local dev fallback
    log_level: str = "INFO"
    scrape_interval_minutes: int = 15

    # Embedding provider: "auto" | "api" | "local"
    # auto: uses API if OPENAI_API_KEY or JINA_API_KEY is set, else local
    # api:   forces API (requires embedding_api_key)
    # local: forces sentence-transformers (slower, ~26s model load)
    embedding_provider: str = "auto"

    # API embedding settings (used when provider is "auto" or "api")
    # All providers use the same OpenAI-compatible /v1/embeddings format.
    # Set ONE of these API keys to enable API embeddings:
    #   OPENAI_API_KEY   → OpenAI text-embedding-3-small (1536d, $0.02/1M tokens)
    #   JINA_API_KEY     → Jina jina-embeddings-v3 (1024d, 10M free tokens)
    #   NVIDIA_API_KEY   → Nvidia NIM baai/bge-m3 (1024d, free for dev)
    openai_api_key: str = ""   # From .env: OPENAI_API_KEY
    jina_api_key: str = ""     # From .env: JINA_API_KEY
    nvidia_api_key: str = ""   # From .env: NVIDIA_API_KEY
    embedding_api_key: str = ""  # Explicit override (takes priority over individual keys)
    embedding_api_base: str = ""  # Override base URL (auto-detected if empty)
    embedding_api_model: str = ""  # Override model name (auto-detected if empty)

    # Local embedding model (used when provider is "local" or "auto" fallback)
    embedding_local_model: str = "intfloat/multilingual-e5-large"

    # Exa Search API (DRE spider — appointment discovery, primary)
    # Free tier: 1,000 requests/month
    exa_api_key: str = ""  # From .env: EXA_API_KEY

    # Tavily Search API (DRE spider — appointment discovery, fallback)
    # Free tier: 1,000 credits/month
    tavily_api_key: str = ""  # From .env: TAVILY_API_KEY

    # Telegram bot (Jornal do Contra alerts)
    telegram_bot_token: str = ""  # From .env: TELEGRAM_BOT_TOKEN
    telegram_chat_id: str = ""  # From .env: TELEGRAM_CHAT_ID

    model_config = {"env_file": ("../.env", ".env"), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
