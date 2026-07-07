"""
Configuration for Optimus Meknes Scraper.
"""

import os
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "optimus.db"

# --- Database ---
DATABASE_URL = os.getenv("OPTIMUS_DATABASE_URL", os.getenv("DATABASE_URL", f"sqlite:///{str(DB_PATH)}"))
if not DATABASE_URL.startswith(("postgresql://", "sqlite://", "mysql://")):
    DATABASE_URL = f"sqlite:///{str(DB_PATH)}"

# --- Scraper settings ---
BASE_URL = "https://optimus.ma/annuaire/ville/meknes"
PAGE_LOAD_TIMEOUT_MS = 45000     # max wait for a page to load (increased for slow proxies)
MAX_RETRIES = 3                  # retries on non-rate-limit errors

# --- Delays (wide random ranges to avoid pattern detection) ---
REQUEST_DELAY_MS = 5000          # base delay (kept for backward compat)
REQUEST_DELAY_MIN_MS = 3000      # delay between company navigations (random range)
REQUEST_DELAY_MAX_MS = 9000
LISTING_DELAY_MIN_MS = 3000      # pause after loading a listing page
LISTING_DELAY_MAX_MS = 8000
SCROLL_DELAY_MS = 1500           # delay after human-like scrolling

# --- Rate-limit backoff (exponential) ---
# After a 429/rate-limit, wait: INITIAL_BACKOFF_MS * 2^hits (capped at MAX_BACKOFF_MS)
INITIAL_BACKOFF_MS = 15000
MAX_BACKOFF_MS = 120000

# --- Rate limiting & Proxy ---
# On rate limit: proxy auto-rotates, context is rebuilt, scraping resumes.
PROXY_ROTATE_AFTER_FAILURES = 2   # auto-rotate after this many consecutive failures

# --- Anti-detection / Browser fingerprint ---
CLOAK_HEADLESS = False           # headed mode — you can see the browsers
CLOAK_HUMANIZE = True            # human-like mouse/keyboard
CLOAK_HUMAN_PRESET = "careful"   # slower, more deliberate human preset
CLOAK_IGNORE_HTTPS_ERRORS = True # optimus.ma has SSL cert issues
BROWSER_LOCALE = "fr-MA"         # Moroccan French via binary flag (stealthy)
BROWSER_TIMEZONE = "Africa/Casablanca"
BROWSER_LATITUDE = 33.8935       # Meknes, Morocco
BROWSER_LONGITUDE = -5.5473
BROWSER_EXTRA_HEADERS = {
    "Accept-Language": "fr-FR,fr;q=0.9,ar-MA;q=0.8,en;q=0.7",
}

# --- Tracking domains to block ---
BLOCKED_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "doubleclick.net",
    "scorecardresearch.com",
    "hotjar.com",
    "newrelic.com",
]

# --- Progress reporting ---
LOG_EVERY_N_COMPANIES = 50      # log detailed summary every N companies saved

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "scraper.log"