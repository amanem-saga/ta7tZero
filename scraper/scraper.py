"""
Orchestrator — manages parallel workers, page queue, and startup.

Usage is via run_scraper.py which calls launch_workers().
"""

import logging
import threading
from typing import Optional

import config
from db import init_db, get_session, get_unfinished_pages, count_companies, get_max_scraped_page
from proxy_manager import ProxyManager
from scraper.worker import ScrapeWorker

logger = logging.getLogger(__name__)


class PageCounter:
    """Thread-safe page number generator. Workers call next_page() to get
    the next page to scrape. Returns None when done (end detected or max reached)."""

    def __init__(self, start: int, max_pages: int = 0):
        self._current = start
        self._max_pages = max_pages  # 0 = unlimited
        self._count = 0
        self._lock = threading.Lock()
        self._ended = False  # set by a worker when it finds an empty page

    def next_page(self) -> Optional[int]:
        with self._lock:
            if self._ended:
                return None
            if self._max_pages > 0 and self._count >= self._max_pages:
                return None
            page = self._current
            self._current += 1
            self._count += 1
            return page

    def mark_end(self):
        """A worker found an empty page — signal all workers to stop."""
        with self._lock:
            self._ended = True

    @property
    def pages_served(self) -> int:
        with self._lock:
            return self._count


def launch_workers(num_workers: int, start_page: int = 1, max_pages: int = 0):
    """Main entry point: health-check proxies, launch workers.

    Args:
        num_workers: how many parallel browsers to launch
        start_page: page to start from (1 = beginning)
        max_pages: 0 = all pages, N = limit
    """
    # ─── 1. Initialize database ────────────────────────────────
    SessionLocal = init_db()
    session = get_session(SessionLocal)
    existing = count_companies(session)
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

    # ─── 3. Cap workers to available proxies ──────────────────
    if num_workers > alive:
        logger.warning(f"Requested {num_workers} workers but only {alive} proxies alive — using {alive}")
        num_workers = alive

    # ─── 4. Determine start page (DB-driven resume) ───────────
    effective_start = max(start_page, 1)
    if existing > 0 and start_page <= 1:
        session = get_session(SessionLocal)
        unfinished = get_unfinished_pages(session, start_page=1)
        session.close()

        if unfinished:
            effective_start = min(unfinished)
            logger.info(f"DB-driven resume: {len(unfinished)} unfinished pages, starting from page {effective_start}")

    # ─── 5. Launch workers ─────────────────────────────────────
    shared_results = {"saved": 0, "skipped": 0, "errors": 0, "rotations": 0}
    page_counter = PageCounter(start=effective_start, max_pages=max_pages)

    logger.info(f"\n{'='*60}")
    logger.info(f"  LAUNCHING {num_workers} PARALLEL WORKERS")
    logger.info(f"  Proxies:   {alive} alive")
    logger.info(f"  Start:     page {effective_start} ({'ALL' if max_pages == 0 else max_pages} pages)")
    logger.info(f"  Existing:  {existing} companies in DB")
    logger.info(f"{'='*60}\n")

    print(f"\n  Launching {num_workers} workers with CloakBrowser...\n", flush=True)

    threads = []
    for i in range(num_workers):
        w = ScrapeWorker(
            worker_id=i + 1,
            proxy_mgr=pm,
            page_counter=page_counter,
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
    logger.info(f"  Pages served:         {page_counter.pages_served}")
    logger.info(f"  New saved this run:    {new_saved}")
    logger.info(f"  Total in DB:           {final_count}")
    logger.info(f"  Proxy rotations:       {shared_results['rotations']}")
    logger.info(f"  Errors:                {shared_results['errors']}")
    logger.info(f"  Proxy pool:            {pm.stats()}")
    logger.info(f"{'='*60}")

    print(f"\n  Done! {final_count} companies in database ({new_saved} new this run)")
    print(f"  Proxy rotations: {shared_results['rotations']} | Errors: {shared_results['errors']}")
    print(f"  Proxy pool: {pm.stats()}\n")