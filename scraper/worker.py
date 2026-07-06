"""
Scraper worker — one thread = one CloakBrowser + one proxy.

Workers pull pages from a shared queue, scrape all new companies on each page,
and save them to the database. On rate-limit, they rotate their proxy.
"""

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from db import company_exists, save_company, log_scrape

logger = logging.getLogger(__name__)


# ─── HTML Parsing (shared, no state) ───────────────────────────────

def parse_french_date(date_str: str) -> Optional[str]:
    return date_str.strip() if date_str else None


def extract_coordinates_from_osm(osm_url: str) -> tuple[Optional[float], Optional[float]]:
    if not osm_url:
        return None, None
    m = re.search(r"mlat=([0-9.\-]+)&mlon=([0-9.\-]+)", osm_url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def parse_listing_page(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    skip_prefixes = ("/annuaire/ville", "/annuaire/villes",
                     "/annuaire/secteur", "/annuaire/categorie")
    seen_slugs = set()
    for a in soup.select("main a[href]"):
        href = a.get("href", "")
        if not href.startswith("/annuaire/"):
            continue
        if any(href.startswith(p) for p in skip_prefixes):
            continue
        if "?" in href:
            continue
        slug = href.removeprefix("/annuaire/")
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        full_url = urljoin(base_url, href)
        text = a.get_text(strip=True)[:200]
        links.append({"slug": slug, "url": full_url, "name_hint": text})
    return links


def parse_detail_page(html: str, url: str, page_number: int) -> dict:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main")
    if not main:
        return {}

    data = {
        "source_url": url,
        "slug": url.rstrip("/").split("/")[-1],
        "page_number": page_number,
        "products": [],
        "brands": [],
    }

    h1 = main.find("h1")
    if h1:
        data["name"] = h1.get_text(strip=True)

    for node in main.find_all(string=True):
        txt = node.strip()
        if txt in ("En activité", "En activité ", "Fermée", "En cours de création"):
            data["status"] = txt.strip()
            break

    def _find_heading(main_tag, pattern: str):
        for h2 in main_tag.find_all("h2"):
            if re.search(pattern, h2.get_text(strip=True), re.IGNORECASE):
                return h2
        return None

    pres_heading = _find_heading(main, r"^pr.sentation$")
    if pres_heading:
        desc_p = pres_heading.find_next_sibling("p")
        if desc_p:
            data["description"] = desc_p.get_text(strip=True)

    for a in main.select("a[href]"):
        href, text = a.get("href", ""), a.get_text(strip=True)
        if "/secteur/" in href and "?sub=" not in href and "voir plus" not in text.lower() and not data.get("sector"):
            data["sector"] = text
        elif ("/categorie/" in href or ("/secteur/" in href and "?sub=" in href)) and not data.get("category"):
            data["category"] = text

    text_blocks = main.find_all("p")
    kv = {}
    for i, p in enumerate(text_blocks):
        txt = p.get_text(strip=True)
        if i + 1 < len(text_blocks):
            nxt = text_blocks[i + 1].get_text(strip=True)
            if txt in ("ICE (Identifiant Commun)", "Registre du Commerce",
                       "Identifiant Fiscal", "Date de création",
                       "Effectif", "Chiffre d'affaires",
                       "Adresse", "Ville",
                       "Téléphone 1", "Téléphone 2", "Téléphone 3", "Fax"):
                kv[txt] = nxt

    data["ice"] = kv.get("ICE (Identifiant Commun)")
    data["rc"] = kv.get("Registre du Commerce")
    data["fiscal_id"] = kv.get("Identifiant Fiscal")
    data["date_creation"] = parse_french_date(kv.get("Date de création"))
    data["employees"] = kv.get("Effectif")
    data["revenue"] = kv.get("Chiffre d'affaires")
    data["address"] = kv.get("Adresse")
    data["city"] = kv.get("Ville")
    data["phone1"] = kv.get("Téléphone 1")
    data["phone2"] = kv.get("Téléphone 2")
    data["phone3"] = kv.get("Téléphone 3")
    data["fax"] = kv.get("Fax")

    osm_a = main.find("a", href=re.compile(r"openstreetmap\.org"))
    if osm_a:
        osm_url = osm_a.get("href", "")
        data["osm_url"] = osm_url
        data["latitude"], data["longitude"] = extract_coordinates_from_osm(osm_url)

    prod_heading = _find_heading(main, r"produits.*services")
    if prod_heading:
        prod_div = prod_heading.find_next_sibling("div")
        if prod_div:
            cat = None
            for span in prod_div.find_all("span"):
                t = span.get_text(strip=True)
                if not t:
                    continue
                if t.endswith(":"):
                    cat = t.rstrip(":").strip()
                elif cat:
                    data["products"].append({"category_label": cat, "label": t.rstrip(",")})

    brand_heading = _find_heading(main, r"marques")
    if brand_heading:
        brand_div = brand_heading.find_next_sibling("div")
        if brand_div:
            for span in brand_div.find_all("span"):
                name = span.get_text(strip=True)
                if name:
                    data["brands"].append(name)

    return data


def _is_rate_limited(error: Exception) -> bool:
    s = str(error).upper()
    if any(k in s for k in ("CONNECTION_REFUSED", "ERR_CONNECTION", "ERR_CONNECTION_RESET")):
        return True
    if any(k in s for k in ("429", "TOO MANY REQUESTS")):
        return True
    if "403" in s and ("FORBIDDEN" in s or "BLOCKED" in s):
        return True
    return False


def _jittered_delay(base_ms: int):
    time.sleep(base_ms / 1000 * random.uniform(0.7, 1.3))


# ─── Worker ─────────────────────────────────────────────────────────

class ScrapeWorker:
    """One worker = one CloakBrowser + one proxy + one DB session.

    Pulls pages from a shared queue, scrapes companies, saves to DB.
    On rate-limit: rotates proxy via ProxyManager, rebuilds context.
    """

    def __init__(self, worker_id: int, proxy_mgr, page_queue, session_factory,
                 results: dict):
        """
        Args:
            worker_id: unique int for this worker
            proxy_mgr: ProxyManager instance (shared)
            page_queue: thread-safe queue of (page_num,) tuples
            session_factory: SQLAlchemy sessionmaker
            results: shared dict to report stats {saved, skipped, errors, rotations}
        """
        self.worker_id = worker_id
        self.proxy_mgr = proxy_mgr
        self.page_queue = page_queue
        self.SessionLocal = session_factory
        self.results = results  # shared, thread-safe via GIL for simple ints

        self.browser = None
        self._context = None
        self.page = None
        self._proxy = None

        self._saved = 0
        self._skipped = 0
        self._errors = 0
        self._rotations = 0

    # ─── Browser lifecycle ──────────────────────────────────────

    def _launch_browser(self):
        """Launch CloakBrowser."""
        from cloakbrowser import launch

        logger.info(f"[W{self.worker_id}] Launching CloakBrowser...")
        self.browser = launch(
            headless=config.CLOAK_HEADLESS,
            humanize=config.CLOAK_HUMANIZE,
        )
        self._create_context()
        logger.info(f"[W{self.worker_id}] CloakBrowser ready")

    def _create_context(self):
        """Create fresh browser context with current proxy."""
        ctx_kwargs = {"ignore_https_errors": config.CLOAK_IGNORE_HTTPS_ERRORS}
        if self._proxy:
            ctx_kwargs["proxy"] = {
                "server": self._proxy["server"],
                "username": self._proxy["username"],
                "password": self._proxy["password"],
            }
        self._context = self.browser.new_context(**ctx_kwargs)
        self.page = self._context.new_page()
        self.page.set_default_timeout(config.PAGE_LOAD_TIMEOUT_MS)

    def _rotate_proxy(self):
        """Rotate proxy and rebuild context."""
        self._rotations += 1
        new_proxy = self.proxy_mgr.rotate(self.worker_id)
        if new_proxy is None:
            logger.error(f"[W{self.worker_id}] No more proxies available!")
            return False

        self._proxy = new_proxy
        try:
            if self._context:
                self._context.clear_cookies()
                self._context.close()
        except Exception:
            pass

        self._create_context()
        logger.info(
            f"[W{self.worker_id}] Proxy rotated #{self._rotations} → "
            f"{self._proxy['server']} ({self.proxy_mgr.total_alive} remaining)"
        )
        return True

    def _close_browser(self):
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass

    # ─── Navigation ─────────────────────────────────────────────

    def _navigate(self, url: str, expected_text: str = None) -> str:
        """Navigate, handle rate-limit with auto-rotation."""
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                self.page.goto(url, wait_until="domcontentloaded")
                self.page.wait_for_load_state("networkidle", timeout=15000)
                html = self.page.content()
                if len(html) < 500:
                    raise RuntimeError(f"Page too small ({len(html)} chars)")
                if expected_text and expected_text not in html:
                    if not self.page.title():
                        raise RuntimeError(f"Expected text not found, html_len={len(html)}")
                return html

            except Exception as e:
                if _is_rate_limited(e):
                    if not self._rotate_proxy():
                        raise
                    logger.info(f"[W{self.worker_id}] Retrying with new proxy...")
                    continue  # don't consume attempt

                cooldown = config.REQUEST_DELAY_MS / 1000 * attempt
                logger.warning(f"[W{self.worker_id}] Error (attempt {attempt}): {str(e)[:80]}")
                time.sleep(cooldown)
                if attempt == config.MAX_RETRIES:
                    raise

    # ─── Scraping ───────────────────────────────────────────────

    def _scrape_company(self, link: dict, page_num: int, session) -> bool:
        """Scrape one company. Returns True if saved, False if skipped/error."""
        slug = link["slug"]
        if company_exists(session, slug):
            self._skipped += 1
            return False

        try:
            html = self._navigate(link["url"])
            data = parse_detail_page(html, link["url"], page_num)
            if not data.get("name"):
                self._errors += 1
                return False

            save_company(session, data)
            session.commit()
            self._saved += 1

            if self._saved % config.LOG_EVERY_N_COMPANIES == 0:
                logger.info(
                    f"[W{self.worker_id}] SAVED #{self._saved} total | "
                    f"Name: {data['name']} | ICE: {data.get('ice', 'N/A')}"
                )

            _jittered_delay(config.REQUEST_DELAY_MS)
            return True

        except Exception as e:
            self._errors += 1
            logger.error(f"[W{self.worker_id}] ERROR {slug}: {str(e)[:80]}")
            session.rollback()
            if _is_rate_limited(e):
                self._rotate_proxy()
            else:
                time.sleep(config.REQUEST_DELAY_MS / 1000 * 2)
            return False

    def _scrape_page(self, page_num: int, session) -> bool:
        """Scrape one listing page + all its companies.
        Returns True if page had companies, False if empty (signals end)."""
        url = config.BASE_URL if page_num == 1 else f"{config.BASE_URL}?page={page_num}"

        log_scrape(session, page_num, "started")
        logger.info(f"[W{self.worker_id}] === PAGE {page_num} ===")

        try:
            html = self._navigate(url, expected_text="Entreprises")
        except Exception as e:
            logger.error(f"[W{self.worker_id}] Page {page_num} listing failed: {e}")
            log_scrape(session, page_num, "failed", error=str(e)[:200])
            return True  # don't signal end — might just be a bad proxy

        links = parse_listing_page(html, config.BASE_URL)
        if not links:
            logger.info(f"[W{self.worker_id}] Page {page_num}: 0 links — end of pages?")
            log_scrape(session, page_num, "completed", found=0)
            return False  # signal: no more pages

        _jittered_delay(config.LISTING_DELAY_MS)
        logger.info(f"[W{self.worker_id}] Page {page_num}: {len(links)} links")

        scraped_count = 0
        for i, link in enumerate(links):
            if self._scrape_company(link, page_num, session):
                scraped_count += 1

        log_scrape(session, page_num, "completed",
                   found=len(links), scraped=scraped_count)
        logger.info(
            f"[W{self.worker_id}] Page {page_num} done: "
            f"{scraped_count} new, {len(links) - scraped_count} skipped"
        )
        return True  # continue

    # ─── Main worker loop ───────────────────────────────────────

    def run(self):
        """Main loop: pull pages from queue, scrape until queue is empty."""
        session = self.SessionLocal()
        try:
            # Acquire proxy and launch browser
            self._proxy = self.proxy_mgr.acquire(self.worker_id)
            if not self._proxy:
                logger.error(f"[W{self.worker_id}] No proxy available, exiting")
                return

            self._launch_browser()

            # Pull pages from the shared queue
            while True:
                try:
                    page_num = self.page_queue.get_nowait()
                except Exception:
                    # Queue empty — we're done
                    break

                has_more = self._scrape_page(page_num, session)
                self.page_queue.task_done()

                if not has_more:
                    # This page was empty — signal end to other workers
                    # by draining the queue
                    self._drain_queue()
                    break

        finally:
            self._close_browser()
            self.proxy_mgr.release(self.worker_id)
            session.close()

            # Report stats
            self.results["saved"] += self._saved
            self.results["skipped"] += self._skipped
            self.results["errors"] += self._errors
            self.results["rotations"] += self._rotations

            logger.info(
                f"[W{self.worker_id}] DONE — "
                f"saved: {self._saved}, skipped: {self._skipped}, "
                f"errors: {self._errors}, rotations: {self._rotations}"
            )

    def _drain_queue(self):
        """Drain remaining pages from queue (another worker found the end)."""
        drained = 0
        while True:
            try:
                self.page_queue.get_nowait()
                self.page_queue.task_done()
                drained += 1
            except Exception:
                break
        if drained > 0:
            logger.info(f"[W{self.worker_id}] Drained {drained} pages from queue (end detected)")