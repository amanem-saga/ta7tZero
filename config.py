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
MAX_RETRIES = 3                  # retries on non-rate-limit errors
RESUME_FROM_PAGE = int(os.getenv("RESUME_FROM_PAGE", "1"))
RESUME_FROM_INDEX = int(os.getenv("RESUME_FROM_INDEX", "0"))

# --- Rate limiting ---
# On rate limit detection (CONNECTION_REFUSED, 429, 403, blocked page):
#   1. Scraper PAUSES and asks you to rotate your VPN IP
#   2. After you press ENTER, it clears cache/cookies and resumes
# No auto-retry — you stay in control.

# --- Progress reporting ---
LOG_EVERY_N_COMPANIES = 50      # log detailed summary every N companies saved
LOG_EVERY_N_PAGES = 5           # log page progress summary every N pages

# --- CloakBrowser settings ---
CLOAK_HEADLESS = False           # headed mode — you can see the browser
CLOAK_HUMANIZE = True            # human-like mouse/keyboard
CLOAK_IGNORE_HTTPS_ERRORS = True # optimus.ma has SSL cert issues

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = BASE_DIR / "logs" / "scraper.log"