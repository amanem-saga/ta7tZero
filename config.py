"""
Configuration for Optimus Meknes Scraper.
Switch DATABASE_URL to connect to PostgreSQL when available.
"""

import os
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "optimus.db"

# --- Database ---
# SQLite for local dev (no PostgreSQL server needed)
# PostgreSQL for production: "postgresql://user:password@localhost:5432/optimus"
DATABASE_URL = os.getenv("OPTIMUS_DATABASE_URL", os.getenv("DATABASE_URL", f"sqlite:///{str(DB_PATH)}"))
# If the inherited DATABASE_URL doesn't look like a valid SQLAlchemy URL, use SQLite
if not DATABASE_URL.startswith(("postgresql://", "sqlite://", "mysql://")):
    DATABASE_URL = f"sqlite:///{str(DB_PATH)}"

# --- Scraper settings ---
BASE_URL = "https://optimus.ma/annuaire/ville/meknes"
COMPANIES_PER_PAGE = 40
REQUEST_DELAY_MS = 3000          # delay between company navigations (3s base)
PAGE_LOAD_DELAY_MS = 1000       # extra pause after each page loads
LISTING_DELAY_MS = 3000         # pause after loading a listing page
PAGE_LOAD_TIMEOUT_MS = 30000     # max wait for a page to load
MAX_RETRIES = 3                  # retries on failure
CONNECTION_REFUSED_COOLDOWN = 60  # seconds to wait when site refuses connection
MAX_CONSECUTIVE_REFUSED = 5      # restart browser after this many refused errors
LONG_COOLDOWN_AFTER_RESTART = 300  # 5 min wait if still refused after browser restart
RESUME_FROM_PAGE = int(os.getenv("RESUME_FROM_PAGE", "1"))
RESUME_FROM_INDEX = int(os.getenv("RESUME_FROM_INDEX", "0"))

# --- Progress reporting ---
LOG_EVERY_N_COMPANIES = 50      # log detailed summary every N companies saved
LOG_EVERY_N_PAGES = 5           # log page progress summary every N pages

# --- CloakBrowser settings ---
CLOAK_HEADLESS = True            # set False for debugging
CLOAK_HUMANIZE = True            # human-like mouse/keyboard
CLOAK_IGNORE_HTTPS_ERRORS = True # optimus.ma has SSL cert issues

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "scraper.log"