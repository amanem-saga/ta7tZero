# ta7tZero — Optimus.ma Meknes Company Scraper

Stealth web scraper that extracts **all companies** from the [optimus.ma Meknes directory](https://optimus.ma/annuaire/ville/meknes) (~1,821 pages, ~54,000 companies) into a local database with full details including geographic coordinates.

Uses [CloakBrowser](https://github.com/CloakHQ/CloakBrowser/) (stealth Chromium) to avoid detection, and SQLAlchemy ORM for database storage (SQLite by default, PostgreSQL-ready).

## What Gets Scraped

For each company detail page:

| Field | Example |
|-------|---------|
| Name | `SADIPRO` |
| Status | `En activité` |
| ICE (Identifiant Commun) | `002854026000019` |
| Registre du Commerce | `Meknes-2020-12345` |
| Identifiant Fiscal | `123456789` |
| Date de création | `13 janvier 2011` |
| Effectif | `10-49` |
| Chiffre d'affaires | `1-5 MDH` |
| Sector | `Commerce & Negoce` |
| Category | `Bazar` |
| Description | Full company description |
| Address, City | Full address |
| Phone 1/2/3, Fax | Multiple phone numbers |
| **Latitude, Longitude** | Extracted from OpenStreetMap links |
| Products & Services | Categorized product list |
| Brands | Brand names |

## Prerequisites

- **Python 3.10+**
- **A VPN or Moroccan IP** — optimus.ma blocks non-Moroccan connections (`ERR_CONNECTION_REFUSED`). You **must** run this from a Moroccan IP or through a VPN.
- **Playwright Chromium** (installed automatically with CloakBrowser)

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/amanem-saga/ta7tZero.git
cd ta7tZero

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate      # Linux/Mac
# venv\Scripts\activate       # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser (Chromium)
playwright install chromium

# 5. (Optional) Create a .env file for custom settings
cp .env.example .env
```

## Quick Start

### Run interactively (see live output)

```bash
# Scrape ALL pages (~54,000 companies)
python run_scraper.py

# Scrape only first 5 pages (for testing)
python run_scraper.py --pages 5

# Resume from page 100
python run_scraper.py --start-page 100

# Resume from page 50, starting at company index 15 within that page
python run_scraper.py --start-page 50 --start-index 15
```

### Run as a background daemon

```bash
# Start in background (logs go to logs/console.out)
python daemon.py

# Monitor progress
tail -f logs/console.out
tail -f logs/scraper.log

# Check how many companies are in the DB
python -c "
import sqlite3
conn = sqlite3.connect('data/optimus.db')
print(conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0])
conn.close()
"
```

### Resume after interruption

The scraper **skips companies already in the database** (matched by slug). If it stops for any reason, just re-run:

```bash
python run_scraper.py
```

It will detect existing companies and resume from where it left off.

## Configuration

All settings are in `config.py`. You can override via environment variables:

| Env Variable | Default | Description |
|---|---|---|
| `OPTIMUS_DATABASE_URL` | `sqlite:///data/optimus.db` | SQLAlchemy database URL |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`) |
| `RESUME_FROM_PAGE` | `1` | Auto-resume from this page |

### Switch to PostgreSQL

```bash
export OPTIMUS_DATABASE_URL="postgresql://user:password@localhost:5432/optimus"
python run_scraper.py
```

Or create the PostgreSQL schema manually:

```bash
psql -U user -d optimus -f db/init_postgres.sql
```

## Project Structure

```
ta7tZero/
├── config.py              # All configuration (delays, URLs, settings)
├── run_scraper.py         # CLI entry point with --pages, --start-page, --start-index
├── daemon.py              # Self-daemonizing wrapper (background execution)
├── start_scraper.sh       # Bash helper script
├── requirements.txt       # Python dependencies
├── db/
│   ├── __init__.py        # Engine setup, save_company(), French date parsing
│   ├── models.py          # SQLAlchemy ORM: Company, Product, Brand, ScrapeLog
│   └── init_postgres.sql  # PostgreSQL DDL with pg_trgm + PostGIS extensions
├── scraper/
│   ├── __init__.py
│   └── scraper.py         # CloakBrowser scraper, HTML parsers, retry logic
├── data/                  # SQLite database (created at runtime)
├── logs/                  # Log files (created at runtime)
└── .gitignore
```

## Rate Limiting & Anti-Detection

- **Jittered delays**: 3s ± 30% between requests (human-like timing)
- **Stealth browser**: CloakBrowser patches Chromium's fingerprint
- **Auto-retry**: 3 retries with exponential backoff on failures
- **Browser restart**: Automatically restarts after 5 consecutive connection errors
- **Progress logging**: Detailed summary every 50th company, page summary every 5 pages

## Database Schema

The scraper uses 4 tables:

- **`companies`** — 20+ columns with indexes on name, city, sector, category, coordinates
- **`products`** — Company products/services (category + label, many-to-one)
- **`brands`** — Company brand names (many-to-one)
- **`scrape_logs`** — Page-level progress tracking for resumability

## Querying the Data (SQLite)

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/optimus.db')

# Total companies
print('Total:', conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0])

# Companies by sector
for row in conn.execute('SELECT sector, COUNT(*) FROM companies GROUP BY sector ORDER BY count DESC LIMIT 10'):
    print(f'  {row[0]}: {row[1]}')

# Companies with coordinates (for mapping)
coords = conn.execute('SELECT name, latitude, longitude FROM companies WHERE latitude IS NOT NULL LIMIT 5').fetchall()
for c in coords:
    print(f'  {c[0]}: {c[1]}, {c[2]}')
conn.close()
"
```

## Future: Vite Frontend

The PostgreSQL schema (`db/init_postgres.sql`) includes:
- **pg_trgm** extension for fuzzy company name search
- **PostGIS** support for geographic queries (nearby companies)
- Example queries for full-text French search

This is designed to be consumed by a Vite + React frontend (to be built separately).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ERR_CONNECTION_REFUSED` | Connect via a **Moroccan VPN** or proxy |
| `ERR_CERT_COMMON_NAME_INVALID` | Already handled by `ignore_https_errors=True` |
| `CloakBrowser` not found | Run `pip install -r requirements.txt` again |
| Chromium not found | Run `playwright install chromium` |
| Scraper runs but finds 0 companies | Page structure may have changed — check `logs/scraper.log` |
| Old test data in DB | Delete `data/optimus.db` and restart |

## License

Private project — not for redistribution without permission.