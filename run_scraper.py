"""Main entry point for the Optimus Meknes scraper."""

import argparse
import logging
import sys
import os

# Ensure project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_DIR, LOG_LEVEL, LOG_FILE
from db import init_db, get_session
from scraper.scraper import OptimusScraper


def setup_logging():
    """Configure logging to both console and file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Optimus.ma companies in Meknes into a database."
    )
    parser.add_argument(
        "--pages", type=int, default=0,
        help="Max pages to scrape (0 = all pages). Default: 0"
    )
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Page number to start from. Default: 1"
    )
    parser.add_argument(
        "--start-index", type=int, default=0,
        help="Company index within the start page to resume from. Default: 0"
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("  Optimus Meknes Scraper — CloakBrowser")
    logger.info("=" * 60)
    logger.info(f"  Database:    SQLite (local)")
    logger.info(f"  Start page:  {args.start_page}")
    logger.info(f"  Start index: {args.start_index}")
    logger.info(f"  Max pages:   {'ALL' if args.pages == 0 else args.pages}")
    logger.info(f"  Rate limit:  ~2s between requests (jittered)")
    logger.info(f"  Log detail:  every 50th company")
    logger.info("=" * 60)

    # Initialize database
    SessionLocal = init_db()
    session = get_session(SessionLocal)

    # Count existing companies for resume info
    from db.models import Company
    existing = session.query(Company).count()
    if existing > 0:
        logger.info(f"  DB already has {existing} companies (will skip duplicates)")

    # Full scrape
    scraper = OptimusScraper()
    try:
        scraper.scrape_all(
            session=session,
            start_page=args.start_page,
            start_index=args.start_index,
            max_pages=args.pages,
        )
    except KeyboardInterrupt:
        logger.info(f"\nInterrupted. Resume with:")
        logger.info(f"  python run_scraper.py --start-page {args.start_page}")
    finally:
        session.close()


if __name__ == "__main__":
    main()