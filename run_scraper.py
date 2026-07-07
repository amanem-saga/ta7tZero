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


def cmd_scrape(args):
    """Run the scraper."""
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

    try:
        launch_workers(
            num_workers=args.workers,
            start_page=args.start_page,
            max_pages=args.pages,
        )
    except KeyboardInterrupt:
        logger.info("\nInterrupted. Just re-run to resume — the DB tracks progress.")


def cmd_dedup(_args):
    """Remove duplicate companies from the database."""
    from db import run_dedup
    run_dedup()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Optimus.ma companies in Meknes into a database."
    )
    parser.add_argument("--workers", "-w", type=int, default=5,
                        help="Parallel browsers (default: 5)")
    parser.add_argument("--start-page", type=int, default=1,
                        help="Page to start from (1 = auto-resume)")
    parser.add_argument("--pages", type=int, default=0,
                        help="Max pages (0 = all)")
    parser.add_argument("--skip-health-check", action="store_true",
                        help="Skip proxy health check")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scrape", help="Run the scraper (default)")
    sub.add_parser("dedup", help="Remove duplicate companies from DB")

    args = parser.parse_args()

    if args.command is None or args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "dedup":
        cmd_dedup(args)


if __name__ == "__main__":
    main()