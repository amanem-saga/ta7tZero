"""
Orchestrator — manages parallel workers, page queue, and startup.

Usage is via run_scraper.py which calls launch_workers().
"""

import logging
import queue
import threading
from typing import Optional

import config
from db import init_db, get_session, get_unfinished_pages, count_companies, get_max_scraped_page
from proxy_manager import ProxyManager
from scraper.worker import ScrapeWorker

logger = logging.getLogger(__name__)


def launch_workers(num_workers: int, start_page: int = 1, max_pages: int = 0):
    """Main entry point: health-check proxies, build page queue, launch workers.

    Args:
        num_workers: how many parallel browsers to launch
        start_page: page to start from (1 = beginning)
        max_pages: 0 = all pages, N = limit
    """
    # ─── 1. Initialize database ────────────────────────────────
    SessionLocal = init_db()
    session = get_session(SessionLocal)
    existing = count_companies(session)
    max_logged_page = get_max_scraped_page(session)
    session.close()

    if existing > 0:
        logger.info(f"DB already has {existing} companies (will skip duplicates)")

    # ─── 2. Load and health-check proxies ──────────────────────
    pm = ProxyManager()
    pm.load()

    if pm.total_alive == 0:
        logger.error("No proxies in proxies.txt! Cannot scrape.")
        print("\n  ERROR: No proxies found. Add proxies to proxies.txt and re-run.\n")
        return

    # Health check
    alive = pm.health_check()
    if alive == 0:
        logger.error("All proxies are dead! Cannot scrape.")
        print("\n  ERROR: All proxies failed health check. Check proxies.txt.\n")
        return

    # ─── 3. Auto-set workers = all alive proxies ───────────────
    num_workers = alive
    logger.info(f"Launching 1 browser per alive proxy: {num_workers} workers")

    # ─── 4. Build page queue (DB-driven resume) ────────────────
    page_queue = queue.Queue()

    # Find where to start
    effective_start = max(start_page, 1)
    if existing > 0 and start_page <= 1:
        # Auto-resume: find unfinished pages
        session = get_session(SessionLocal)
        unfinished = get_unfinished_pages(session, start_page=1)
        session.close()

        if unfinished:
            effective_start = min(unfinished)
            logger.info(f"DB-driven resume: {len(unfinished)} unfinished pages detected, starting from page {effective_start}")

    # Fill the queue
    pages_queued = 0
    page_num = effective_start
    while max_pages == 0 or pages_queued < max_pages:
        page_queue.put(page_num)
        pages_queued += 1
        page_num += 1

    logger.info(f"Page queue: {pages_queued} pages queued (starting at {effective_start})")

    # ─── 5. Launch workers ─────────────────────────────────────
    shared_results = {"saved": 0, "skipped": 0, "errors": 0, "rotations": 0}

    logger.info(f"\n{'='*60}")
    logger.info(f"  LAUNCHING {num_workers} PARALLEL WORKERS")
    logger.info(f"  Proxies:   {alive} alive")
    logger.info(f"  Queue:     {pages_queued} pages")
    logger.info(f"  Existing:  {existing} companies in DB")
    logger.info(f"{'='*60}\n")

    print(f"\n  Launching {num_workers} workers with CloakBrowser...\n", flush=True)

    threads = []
    for i in range(num_workers):
        w = ScrapeWorker(
            worker_id=i + 1,
            proxy_mgr=pm,
            page_queue=page_queue,
            session_factory=SessionLocal,
            results=shared_results,
        )
        t = threading.Thread(target=w.run, name=f"worker-{i+1}")
        t.daemon = True
        threads.append(t)
        # Stagger launches to avoid all hitting the site at once
        if i > 0:
            import time
            time.sleep(2)
        t.start()

    # ─── 6. Wait for completion ────────────────────────────────
    for t in threads:
        t.join()

    # ─── 7. Final summary ──────────────────────────────────────
    session = get_session(SessionLocal)
    final_count = count_companies(session)
    session.close()

    new_saved = final_count - existing

    logger.info(f"\n{'='*60}")
    logger.info(f"  ALL WORKERS FINISHED")
    logger.info(f"  New saved this run:    {new_saved}")
    logger.info(f"  Total in DB:           {final_count}")
    logger.info(f"  Proxy rotations:       {shared_results['rotations']}")
    logger.info(f"  Errors:                {shared_results['errors']}")
    logger.info(f"  Proxy pool:            {pm.stats()}")
    logger.info(f"{'='*60}")

    print(f"\n  Done! {final_count} companies in database ({new_saved} new this run)")
    print(f"  Proxy rotations: {shared_results['rotations']} | Errors: {shared_results['errors']}")
    print(f"  Proxy pool: {pm.stats()}\n")