"""
Proxy manager with health checking, exhaustion tracking, and thread-safe rotation.

Lifecycle:
  1. load() — read proxies.txt
  2. health_check() — test each proxy, remove dead ones
  3. Workers call acquire() to get a proxy, release() to return it
  4. On rate-limit: exhaust() moves proxy to proxies_exhausted.txt, acquires new one
  5. State persisted to disk so it survives restarts
"""

import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

DEAD_FILE = config.BASE_DIR / "proxies_dead.txt"
EXHAUSTED_FILE = config.BASE_DIR / "proxies_exhausted.txt"
STATE_FILE = config.BASE_DIR / "data" / ".proxy_state"


# ─── Parsing ─────────────────────────────────────────────────────────

def _parse_proxy(line: str) -> Optional[dict]:
    """Parse 'user:pass@host:port' into a proxy record dict."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "@" not in line:
        return None

    credentials, host_port = line.split("@", 1)
    if ":" not in credentials or ":" not in host_port:
        return None

    username, password = credentials.split(":", 1)
    host, port = host_port.rsplit(":", 1)

    return {
        "raw": line,
        "server": f"http://{host}:{port}",
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
    }


def _load_proxy_file(filepath: Path) -> list[dict]:
    """Load proxies from a file."""
    if not filepath.exists():
        return []
    proxies = []
    with open(filepath) as f:
        for line in f:
            p = _parse_proxy(line)
            if p:
                proxies.append(p)
    return proxies


def _append_to_file(filepath: Path, raw_line: str):
    """Append a raw proxy line to a file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "a") as f:
        f.write(raw_line + "\n")


# ─── Health check ────────────────────────────────────────────────────

def _test_single_proxy(proxy: dict, timeout: int = 10) -> bool:
    """Test if a proxy can reach optimus.ma through it."""
    test_url = config.BASE_URL
    proxy_url = f"http://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"

    handler = None
    try:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        handler = opener.open(
            urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=timeout,
        )
        return handler.status == 200
    except Exception:
        return False
    finally:
        if handler:
            try:
                handler.close()
            except Exception:
                pass


# ─── ProxyManager ───────────────────────────────────────────────────

class ProxyManager:
    """Thread-safe proxy pool with health checking and exhaustion tracking.

    Usage by workers:
        proxy = pm.acquire()     # get a proxy
        # ... use it ...
        pm.exhaust(proxy)        # rate-limited — move to exhausted, get new one
        pm.release(proxy)        # done with it — return to pool
    """

    def __init__(self):
        self._all_proxies: list[dict] = []
        self._available: list[dict] = []
        self._in_use: dict[int, dict] = {}  # worker_id → proxy
        self._lock = threading.Lock()
        self._exhausted_count = 0
        self._dead_count = 0

    @property
    def total_alive(self) -> int:
        with self._lock:
            return len(self._available) + len(self._in_use)

    @property
    def exhausted_count(self) -> int:
        return self._exhausted_count

    @property
    def dead_count(self) -> int:
        return self._dead_count

    def load(self):
        """Load proxies from proxies.txt."""
        self._all_proxies = _load_proxy_file(config.BASE_DIR / "proxies.txt")
        self._available = list(self._all_proxies)
        logger.info(f"Loaded {len(self._available)} proxies from proxies.txt")

    def health_check(self, max_threads: int = 20) -> int:
        """Test all proxies, remove dead ones, save them to proxies_dead.txt.
        Returns the number of alive proxies."""
        if not self._available:
            logger.warning("No proxies to health-check")
            return 0

        alive = []
        dead = []
        total = len(self._available)

        logger.info(f"Health-checking {total} proxies (up to {max_threads} concurrent)...")
        print(f"\n  Checking {total} proxies...", flush=True)

        # Use threading for concurrent checks
        results = [None] * total
        lock = threading.Lock()

        def check_one(idx, proxy):
            try:
                ok = _test_single_proxy(proxy, timeout=config.PAGE_LOAD_TIMEOUT_MS // 1000)
            except Exception:
                ok = False
            with lock:
                results[idx] = (proxy, ok)

        threads = []
        for i, proxy in enumerate(self._available):
            t = threading.Thread(target=check_one, args=(i, proxy))
            threads.append(t)
            t.start()
            # Limit concurrency
            if len(threads) >= max_threads:
                for t in threads:
                    t.join()
                threads = []
        for t in threads:
            t.join()

        for proxy, ok in results:
            if ok:
                alive.append(proxy)
            else:
                dead.append(proxy)

        self._available = alive
        self._dead_count = len(dead)

        # Save dead proxies
        if dead:
            with open(DEAD_FILE, "w") as f:
                for p in dead:
                    f.write(p["raw"] + "\n")
            logger.info(f"Saved {len(dead)} dead proxies to {DEAD_FILE}")

        # Update proxies.txt with only alive ones
        if alive:
            with open(config.BASE_DIR / "proxies.txt", "w") as f:
                for p in alive:
                    f.write(p["raw"] + "\n")

        print(f"  Result: {len(alive)} alive, {len(dead)} dead\n", flush=True)
        logger.info(f"Health check done: {len(alive)} alive, {len(dead)} dead")
        return len(alive)

    def acquire(self, worker_id: int) -> Optional[dict]:
        """Get a proxy for a worker. Thread-safe."""
        with self._lock:
            if not self._available:
                return None
            proxy = self._available.pop(0)
            self._in_use[worker_id] = proxy
            logger.info(f"Worker {worker_id} acquired proxy: {proxy['server']}")
            return proxy

    def release(self, worker_id: int):
        """Return a worker's proxy to the available pool."""
        with self._lock:
            proxy = self._in_use.pop(worker_id, None)
            if proxy:
                self._available.append(proxy)

    def exhaust(self, worker_id: int) -> Optional[dict]:
        """Mark current proxy as exhausted (rate-limited), save to file,
        and acquire a new one for the worker."""
        with self._lock:
            old_proxy = self._in_use.pop(worker_id, None)
            if old_proxy:
                self._exhausted_count += 1
                _append_to_file(EXHAUSTED_FILE, old_proxy["raw"])
                logger.info(
                    f"Proxy EXHAUSTED #{self._exhausted_count}: "
                    f"{old_proxy['server']} → moved to {EXHAUSTED_FILE.name}"
                )

            # Acquire new proxy
            if self._available:
                new_proxy = self._available.pop(0)
                self._in_use[worker_id] = new_proxy
                logger.info(
                    f"Worker {worker_id} new proxy: {new_proxy['server']} "
                    f"({len(self._available)} remaining)"
                )
                return new_proxy
            return None

    def rotate(self, worker_id: int) -> Optional[dict]:
        """Alias for exhaust — rotate to next proxy."""
        return self.exhaust(worker_id)

    def stats(self) -> str:
        with self._lock:
            return (
                f"Alive: {len(self._available)} | "
                f"In-use: {len(self._in_use)} | "
                f"Exhausted: {self._exhausted_count} | "
                f"Dead: {self._dead_count}"
            )