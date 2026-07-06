"""Main entry point for the Optimus Meknes scraper."""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_DIR, LOG_LEVEL, LOG_FILE


def setup_logging():
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
        "--workers", "-w", type=int, default=5,
        help="Number of parallel browsers (default: 5). Each gets its own proxy."
    )
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Page number to start from (default: 1 = auto-resume from DB)"
    )
    parser.add_argument(
        "--pages", type=int, default=0,
        help="Max pages to scrape (0 = all). Default: 0"
    )
    parser.add_argument(
        "--skip-health-check", action="store_true",
        help="Skip proxy health check (faster start, but dead proxies won't be filtered)"
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("  Optimus Meknes Scraper — Parallel Workers")
    logger.info("=" * 60)
    logger.info(f"  Workers:         {args.workers}")
    logger.info(f"  Start page:      {args.start_page} (1 = auto-resume)")
    logger.info(f"  Max pages:       {'ALL' if args.pages == 0 else args.pages}")
    logger.info(f"  Health check:    {'SKIP' if args.skip_health_check else 'YES'}")
    logger.info(f"  Mode:            CloakBrowser + proxy rotation")
    logger.info("=" * 60)

    # Import here so logging is set up first
    from scraper.scraper import launch_workers
    from proxy_manager import ProxyManager

    # Quick proxy count
    pm = ProxyManager()
    pm.load()
    logger.info(f"  Proxies loaded:  {pm.total_alive}")

    if not args.skip_health_check and pm.total_alive > 0:
        logger.info("  Running health check...")
    elif args.skip_health_check:
        logger.info("  Health check SKIPPED (--skip-health-check)")

    # Launch
    try:
        launch_workers(
            num_workers=args.workers,
            start_page=args.start_page,
            max_pages=args.pages,
        )
    except KeyboardInterrupt:
        logger.info("\nInterrupted. Just re-run to resume — the DB tracks progress.")


if __name__ == "__main__":
    main()