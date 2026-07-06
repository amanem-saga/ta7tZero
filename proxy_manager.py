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
    """Test if a proxy is reachable (TCP connect + HTTP auth through it)."""
    import socket
    import urllib.request
    import ssl

    proxy_url = f"http://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"

    # Step 1: quick TCP check
    try:
        sock = socket.create_connection((proxy['host'], proxy['port']), timeout=5)
        sock.close()
    except Exception:
        return False

    # Step 2: full HTTP request through proxy (ignore SSL)
    handler = None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        https_handler = urllib.request.HTTPSHandler(context=ctx)
        opener = urllib.request.build_opener(proxy_handler, https_handler)
        handler = opener.open(
            urllib.request.Request(config.BASE_URL, headers={"User-Agent": "Mozilla/5.0"}),
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

        total = len(self._available)
        checked = [0]  # mutable counter for closure
        lock = threading.Lock()

        logger.info(f"Health-checking {total} proxies (up to {max_threads} concurrent)...")
        print(f"\n  Checking {total} proxies...\n", flush=True)

        alive = []
        dead = []

        def check_one(proxy):
            try:
                ok = _test_single_proxy(proxy, timeout=10)
            except Exception:
                ok = False

            with lock:
                checked[0] += 1
                n = checked[0]
                short = proxy["host"]
                status = "\033[92mOK\033[0m  " if ok else "\033[91mDEAD\033[0m"
                print(f"  [{n:>3}/{total}]  {status}  {short}:{proxy['port']}", flush=True)

                if ok:
                    alive.append(proxy)
                else:
                    dead.append(proxy)

        # Process in batches to limit concurrency
        batch = []
        for i, proxy in enumerate(self._available):
            t = threading.Thread(target=check_one, args=(proxy,))
            batch.append(t)
            t.start()
            if len(batch) >= max_threads:
                for t in batch:
                    t.join()
                batch = []
        for t in batch:
            t.join()

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

        print(f"\n  Result: {len(alive)} alive, {len(dead)} dead\n", flush=True)
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