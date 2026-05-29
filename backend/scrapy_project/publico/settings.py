# ── Público Scrapy Project Settings ──────────────────────────────────────────
# See: https://docs.scrapy.org/en/latest/topics/settings.html

BOT_NAME = "vespeiro"

SPIDER_MODULES = ["publico.spiders"]
NEWSPIDER_MODULE = "publico.spiders"

# ── Crawl responsibly ────────────────────────────────────────────────────────
USER_AGENT = (
    "Vespeiro/0.1 (media narrative monitor; +https://github.com/vespeiro)"
)
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 3.0           # Be polite — 3 seconds between requests
RANDOMIZE_DOWNLOAD_DELAY = True

# ── Limits ───────────────────────────────────────────────────────────────────
DOWNLOAD_TIMEOUT = 15             # 15 s timeout per request

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# ── Caching ──────────────────────────────────────────────────────────────────
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 1800     # 30 min cache
HTTPCACHE_DIR = ".scrapy-cache"

# ── Item pipelines (disabled for now — we collect via JSON output) ──────────
ITEM_PIPELINES = {}

# ── Extensions ───────────────────────────────────────────────────────────────
EXTENSIONS = {
    "scrapy.extensions.telnet.TelnetConsole": None,  # Disable telnet
}

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_ENABLED = False             # Suppress Scrapy's own log in subprocess mode
