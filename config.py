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
REQUEST_DELAY_MS = 3000          # delay between company navigations (3s base, ±30% jitter)
LISTING_DELAY_MS = 3000         # pause after loading a listing page
PAGE_LOAD_TIMEOUT_MS = 30000     # max wait for a page to load
MAX_RETRIES = 3                  # retries on non-rate-limit errors

# --- Rate limiting & Proxy ---
# On rate limit: proxy auto-rotates, context is rebuilt, scraping resumes.
PROXY_ROTATE_AFTER_FAILURES = 2   # auto-rotate after this many consecutive failures

# --- Progress reporting ---
LOG_EVERY_N_COMPANIES = 50      # log detailed summary every N companies saved

# --- CloakBrowser settings ---
CLOAK_HEADLESS = False           # headed mode — you can see the browsers
CLOAK_HUMANIZE = True            # human-like mouse/keyboard
CLOAK_IGNORE_HTTPS_ERRORS = True # optimus.ma has SSL cert issues

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "scraper.log"