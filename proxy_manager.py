"""
Proxy rotation manager.

Reads proxies from proxies.txt, rotates automatically on rate limiting,
persists the current proxy index so it survives restarts.
Format per line: user:pass@host:port
"""

import logging
import random
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

PROXY_STATE_FILE = config.BASE_DIR / "data" / ".proxy_state"


def _parse_proxy(line: str) -> Optional[dict]:
    """Parse 'user:pass@host:port' into Playwright proxy dict."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Format: username:password@host:port
    if "@" not in line:
        return None

    credentials, host_port = line.split("@", 1)
    if ":" not in credentials:
        return None

    username, password = credentials.split(":", 1)
    if ":" not in host_port:
        return None

    host, port = host_port.rsplit(":", 1)
    port = int(port)

    return {
        "server": f"http://{host}:{port}",
        "username": username,
        "password": password,
    }


def load_proxies() -> list[dict]:
    """Load and parse all proxies from proxies.txt."""
    proxy_file = config.BASE_DIR / "proxies.txt"
    if not proxy_file.exists():
        logger.warning(f"proxies.txt not found at {proxy_file}")
        return []

    proxies = []
    with open(proxy_file) as f:
        for line in f:
            p = _parse_proxy(line)
            if p:
                proxies.append(p)

    logger.info(f"Loaded {len(proxies)} proxies from proxies.txt")
    return proxies


def _load_proxy_index() -> int:
    """Read the persisted proxy index (survives restarts)."""
    if PROXY_STATE_FILE.exists():
        try:
            return int(PROXY_STATE_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
    return 0


def _save_proxy_index(idx: int):
    """Persist the proxy index to disk."""
    PROXY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROXY_STATE_FILE.write_text(str(idx))


class ProxyManager:
    """Manages proxy rotation for the scraper."""

    def __init__(self):
        self.proxies = load_proxies()
        self._index = _load_proxy_index()
        self._rotations = 0
        self._failures_on_current = 0  # consecutive failures on this proxy

        if not self.proxies:
            logger.warning("No proxies loaded — will run without proxy")

    @property
    def total(self) -> int:
        return len(self.proxies)

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def rotations(self) -> int:
        return self._rotations

    def current(self) -> Optional[dict]:
        """Return the current proxy dict (Playwright format), or None if no proxies."""
        if not self.proxies:
            return None
        return self.proxies[self._index % len(self.proxies)]

    def current_display(self) -> str:
        """Human-readable string for the current proxy (hides password)."""
        p = self.current()
        if not p:
            return "NO PROXY (direct connection)"
        return f"{p['server']} (user={p['username']})"

    def rotate(self) -> Optional[dict]:
        """Switch to the next proxy and return it.

        Called automatically when rate limiting is detected.
        Persists the new index to disk.
        """
        if not self.proxies:
            return None

        old_idx = self._index
        self._index = (self._index + 1) % len(self.proxies)
        self._rotations += 1
        self._failures_on_current = 0

        _save_proxy_index(self._index)

        new_proxy = self.current()
        logger.info(
            f"PROXY ROTATED #{self._rotations}: "
            f"[{old_idx % len(self.proxies)}] → [{self._index}] "
            f"{new_proxy['server']}"
        )
        return new_proxy

    def mark_success(self):
        """Reset failure counter on successful request."""
        self._failures_on_current = 0

    def mark_failure(self):
        """Track consecutive failures. Auto-rotate after threshold."""
        self._failures_on_current += 1
        if self._failures_on_current >= config.PROXY_ROTATE_AFTER_FAILURES:
            logger.info(
                f"Proxy failed {self._failures_on_current} times in a row — auto-rotating"
            )
            self.rotate()
            return True  # rotated
        return False  # not yet rotated