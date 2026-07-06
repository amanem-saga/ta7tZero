"""
Optimus Meknes company scraper using CloakBrowser + automatic proxy rotation.

Workflow per page:
  1. Navigate to listing page (with pagination) — verify it loaded
  2. Extract all company links from the listing
  3. Visit each company detail page — verify it loaded
  4. Parse all fields (legal info, contact, coordinates, products, brands)
  5. Save to database via ORM
  6. Log progress every 50 companies
  7. Wait for rate limiting
  8. Move to next page

Proxy rotation:
  Proxies are loaded from proxies.txt. When rate limiting is detected:
    1. Auto-rotate to the next proxy (new browser context)
    2. Resume immediately — no manual intervention needed
    3. If all proxies are exhausted, pause and ask user what to do
"""

import logging
import random
import re
import sys
import time
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from db import save_company, company_exists, log_scrape
from proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


def parse_french_date(date_str: str) -> Optional[str]:
    """Return raw date string; actual parsing done in db layer."""
    return date_str.strip() if date_str else None


def extract_coordinates_from_osm(osm_url: str) -> tuple[Optional[float], Optional[float]]:
    """Extract lat/lng from an OpenStreetMap link."""
    if not osm_url:
        return None, None
    m = re.search(r"mlat=([0-9.\-]+)&mlon=([0-9.\-]+)", osm_url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def parse_listing_page(html: str, base_url: str) -> list[dict]:
    """Parse the listing page and return a list of {slug, url, name_hint}."""
    soup = BeautifulSoup(html, "lxml")
    links = []

    skip_prefixes = ("/annuaire/ville", "/annuaire/villes", "/annuaire/secteur", "/annuaire/categorie")
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
    """Parse a company detail page and return structured data."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main")
    if not main:
        logger.warning(f"No <main> found on {url}")
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

    all_text_nodes = main.find_all(string=True)
    for node in all_text_nodes:
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
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "/secteur/" in href and "?sub=" not in href and "voir plus" not in text.lower() and not data.get("sector"):
            data["sector"] = text
        elif ("/categorie/" in href or ("/secteur/" in href and "?sub=" in href)) and not data.get("category"):
            data["category"] = text

    text_blocks = main.find_all("p")
    key_value_pairs = {}
    for i, p in enumerate(text_blocks):
        txt = p.get_text(strip=True)
        if i + 1 < len(text_blocks):
            next_txt = text_blocks[i + 1].get_text(strip=True)
            if txt in ("ICE (Identifiant Commun)", "Registre du Commerce",
                       "Identifiant Fiscal", "Date de création",
                       "Effectif", "Chiffre d'affaires",
                       "Adresse", "Ville",
                       "Téléphone 1", "Téléphone 2", "Téléphone 3",
                       "Fax"):
                key_value_pairs[txt] = next_txt

    data["ice"] = key_value_pairs.get("ICE (Identifiant Commun)")
    data["rc"] = key_value_pairs.get("Registre du Commerce")
    data["fiscal_id"] = key_value_pairs.get("Identifiant Fiscal")
    data["date_creation"] = parse_french_date(key_value_pairs.get("Date de création"))
    data["employees"] = key_value_pairs.get("Effectif")
    data["revenue"] = key_value_pairs.get("Chiffre d'affaires")
    data["address"] = key_value_pairs.get("Adresse")
    data["city"] = key_value_pairs.get("Ville")
    data["phone1"] = key_value_pairs.get("Téléphone 1")
    data["phone2"] = key_value_pairs.get("Téléphone 2")
    data["phone3"] = key_value_pairs.get("Téléphone 3")
    data["fax"] = key_value_pairs.get("Fax")

    osm_a = main.find("a", href=re.compile(r"openstreetmap\.org"))
    if osm_a:
        osm_url = osm_a.get("href", "")
        data["osm_url"] = osm_url
        lat, lng = extract_coordinates_from_osm(osm_url)
        data["latitude"] = lat
        data["longitude"] = lng

    prod_heading = _find_heading(main, r"produits.*services")
    if prod_heading:
        prod_div = prod_heading.find_next_sibling("div")
        if prod_div:
            current_category = None
            for span in prod_div.find_all("span"):
                txt = span.get_text(strip=True)
                if not txt:
                    continue
                if txt.endswith(":"):
                    current_category = txt.rstrip(":").strip()
                elif current_category:
                    data["products"].append({
                        "category_label": current_category,
                        "label": txt.rstrip(","),
                    })

    brand_heading = _find_heading(main, r"marques")
    if brand_heading:
        brand_div = brand_heading.find_next_sibling("div")
        if brand_div:
            for span in brand_div.find_all("span"):
                name = span.get_text(strip=True)
                if name:
                    data["brands"].append(name)

    return data


def _jittered_delay(base_ms: int):
    """Sleep for base_ms ± 30% to appear more human-like."""
    delay = base_ms / 1000 * random.uniform(0.7, 1.3)
    time.sleep(delay)


def _is_rate_limited(error: Exception) -> bool:
    """Detect if an error is caused by rate limiting or IP blocking."""
    err_str = str(error).upper()
    if any(kw in err_str for kw in ("CONNECTION_REFUSED", "ERR_CONNECTION", "ERR_CONNECTION_RESET")):
        return True
    if any(kw in err_str for kw in ("429", "TOO MANY REQUESTS")):
        return True
    if "403" in err_str and ("FORBIDDEN" in err_str or "BLOCKED" in err_str):
        return True
    return False


class OptimusScraper:
    """Main scraper with automatic proxy rotation.

    On rate limit:
      - Auto-rotates to next proxy
      - Clears cookies/cache (new browser context)
      - Resumes immediately
    If all proxies exhausted:
      - Pauses and asks user what to do
    """

    def __init__(self):
        self.browser = None
        self.page = None
        self._context = None
        self._playwright = None
        self._total_saved = 0
        self._total_skipped = 0
        self._total_errors = 0
        self.proxy_mgr = ProxyManager()

    # ─── Browser lifecycle ──────────────────────────────────────────

    def launch(self):
        """Launch browser — CloakBrowser if available, plain Playwright as fallback."""
        try:
            self._launch_cloakbrowser()
        except Exception as e:
            logger.warning(f"CloakBrowser failed ({e}), falling back to plain Playwright...")
            self._launch_playwright()

        # Create initial context with proxy
        self._create_context()

        # Log proxy info
        if self.proxy_mgr.total > 0:
            logger.info(f"Using proxy: {self.proxy_mgr.current_display()}")
        else:
            logger.warning("No proxies loaded — running without proxy (will likely fail)")

    def _launch_cloakbrowser(self):
        from cloakbrowser import launch
        logger.info("Launching CloakBrowser (stealth Chromium, HEADED)...")
        self.browser = launch(
            headless=config.CLOAK_HEADLESS,
            humanize=config.CLOAK_HUMANIZE,
        )
        logger.info("CloakBrowser launched (headless=%s, humanize=%s)",
                     config.CLOAK_HEADLESS, config.CLOAK_HUMANIZE)

    def _launch_playwright(self):
        from playwright.sync_api import sync_playwright
        logger.info("Launching plain Playwright Chromium (no stealth)...")
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=config.CLOAK_HEADLESS,
        )
        logger.info("Playwright Chromium launched (headless=%s)", config.CLOAK_HEADLESS)

    def _create_context(self):
        """Create a fresh browser context with proxy + HTTPS errors ignored."""
        ctx_kwargs = {
            "ignore_https_errors": config.CLOAK_IGNORE_HTTPS_ERRORS,
        }
        proxy = self.proxy_mgr.current()
        if proxy:
            ctx_kwargs["proxy"] = proxy

        self._context = self.browser.new_context(**ctx_kwargs)
        self.page = self._context.new_page()
        self.page.set_default_timeout(config.PAGE_LOAD_TIMEOUT_MS)

    def _rotate_proxy_and_rebuild_context(self):
        """Rotate to next proxy, kill old context, build fresh one."""
        new_proxy = self.proxy_mgr.rotate()
        if new_proxy is None:
            # No proxies at all — can't rotate
            logger.error("No proxies available to rotate to!")
            return

        logger.info("Rebuilding browser context with new proxy...")
        try:
            if self._context:
                self._context.clear_cookies()
                self._context.close()
        except Exception:
            pass

        self._create_context()
        logger.info(f"Context rebuilt — now using: {self.proxy_mgr.current_display()}")

    def close(self):
        if self._context:
            self._context.close()
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Browser closed")

    # ─── Navigation ─────────────────────────────────────────────────

    def _navigate_and_verify(self, url: str, expected_text: str = None) -> str:
        """Navigate to URL, verify it loaded, return HTML.

        On rate-limit: auto-rotates proxy and retries immediately.
        """
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                logger.debug(f"Navigating to {url} (attempt {attempt})")
                start = time.time()
                self.page.goto(url, wait_until="domcontentloaded")
                self.page.wait_for_load_state("networkidle", timeout=15000)
                elapsed = time.time() - start

                html = self.page.content()
                if len(html) < 500:
                    raise RuntimeError(f"Page too small ({len(html)} chars), likely blocked")

                if expected_text and expected_text not in html:
                    title = self.page.title() or ""
                    if not title:
                        raise RuntimeError(
                            f"Expected text '{expected_text[:40]}' not found, "
                            f"title='{title}', html_len={len(html)}"
                        )

                self.proxy_mgr.mark_success()
                logger.debug(f"Page loaded in {elapsed:.1f}s, {len(html)} chars")
                return html

            except SystemExit:
                raise

            except Exception as e:
                if _is_rate_limited(e):
                    # Auto-rotate proxy
                    rotated = self.proxy_mgr.mark_failure()
                    if rotated or _is_rate_limited(e):
                        # Always rotate on rate-limit errors (not just after N failures)
                        self._rotate_proxy_and_rebuild_context()
                    logger.info(f"Retrying {url} with new proxy...")
                    continue  # retry without consuming the attempt

                # Non-rate-limit error: normal retry
                cooldown = config.REQUEST_DELAY_MS / 1000 * attempt
                logger.warning(f"Error on {url} (attempt {attempt}/{config.MAX_RETRIES}): {str(e)[:100]}")
                logger.info(f"  Waiting {cooldown:.0f}s before retry...")
                time.sleep(cooldown)

                if attempt == config.MAX_RETRIES:
                    logger.error(f"All {config.MAX_RETRIES} attempts failed for {url}")
                    raise

    # ─── Page scraping ──────────────────────────────────────────────

    def _has_next_page(self, page_num: int) -> bool:
        url = config.BASE_URL if page_num == 1 else f"{config.BASE_URL}?page={page_num}"
        html = self._navigate_and_verify(url, expected_text="Entreprises")
        soup = BeautifulSoup(html, "lxml")
        for a in soup.select("a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if "Suivant" in text and "page=" in href:
                return True
        return False

    def scrape_listing_page(self, page_num: int) -> list[dict]:
        if page_num == 1:
            url = config.BASE_URL
        else:
            url = f"{config.BASE_URL}?page={page_num}"

        html = self._navigate_and_verify(url, expected_text="Entreprises")
        links = parse_listing_page(html, config.BASE_URL)

        if not links:
            logger.warning(f"Page {page_num}: 0 company links found — might be empty or blocked")

        _jittered_delay(config.LISTING_DELAY_MS)
        logger.info(f"Page {page_num}: found {len(links)} company links")
        return links

    def _log_company_detail(self, data: dict, counter: int):
        logger.info(
            f"\n{'─'*60}\n"
            f"  COMPANY #{counter} SAVED\n"
            f"{'─'*60}\n"
            f"  Name:       {data.get('name', 'N/A')}\n"
            f"  ICE:        {data.get('ice', 'N/A')}\n"
            f"  RC:         {data.get('rc', 'N/A')}\n"
            f"  Fiscal ID:  {data.get('fiscal_id', 'N/A')}\n"
            f"  Date:       {data.get('date_creation', 'N/A')}\n"
            f"  Employees:  {data.get('employees', 'N/A')}\n"
            f"  Revenue:    {data.get('revenue', 'N/A')}\n"
            f"  Sector:     {data.get('sector', 'N/A')}\n"
            f"  Category:   {data.get('category', 'N/A')}\n"
            f"  Address:    {data.get('address', 'N/A')}\n"
            f"  City:       {data.get('city', 'N/A')}\n"
            f"  Phone:      {data.get('phone1', 'N/A')} / {data.get('phone2', 'N/A')}\n"
            f"  Coords:     {data.get('latitude')}, {data.get('longitude')}\n"
            f"  Products:   {len(data.get('products', []))} items\n"
            f"  Brands:     {data.get('brands', [])}\n"
            f"  Source:     {data.get('source_url', 'N/A')}\n"
            f"{'─'*60}"
        )

    def scrape_company_detail(self, company_link: dict, page_num: int,
                               session) -> Optional[dict]:
        slug = company_link["slug"]
        url = company_link["url"]

        if company_exists(session, slug):
            self._total_skipped += 1
            logger.debug(f"  SKIP (already in DB): {slug}")
            return None

        try:
            html = self._navigate_and_verify(url)
            data = parse_detail_page(html, url, page_num)
            if not data.get("name"):
                logger.warning(f"No name found for {slug}, skipping")
                self._total_errors += 1
                return None

            save_company(session, data)
            session.commit()
            self._total_saved += 1

            n = config.LOG_EVERY_N_COMPANIES
            if self._total_saved % n == 0:
                self._log_company_detail(data, self._total_saved)
                logger.info(
                    f"  [PROGRESS] Saved: {self._total_saved} | "
                    f"Skipped: {self._total_skipped} | "
                    f"Errors: {self._total_errors} | "
                    f"Proxy rotations: {self.proxy_mgr.rotations}"
                )
            else:
                logger.info(f"  [{self._total_saved}] Saved: {data['name']} "
                            f"(ICE: {data.get('ice', 'N/A')})")

            _jittered_delay(config.REQUEST_DELAY_MS)
            return data

        except SystemExit:
            raise
        except Exception as e:
            self._total_errors += 1
            logger.error(f"  ERROR scraping {slug}: {e}")
            session.rollback()
            time.sleep(config.REQUEST_DELAY_MS / 1000 * 2)
            return None

    # ─── Main loop ──────────────────────────────────────────────────

    def scrape_all(self, session, start_page: int = 1,
                   start_index: int = 0, max_pages: int = 0):
        """Scrape all pages with automatic proxy rotation."""
        self.launch()

        try:
            page_num = start_page
            pages_scraped = 0

            while True:
                if max_pages > 0 and pages_scraped >= max_pages:
                    logger.info(f"Reached max_pages limit ({max_pages})")
                    break

                log_scrape(session, page_num, "started")
                logger.info(f"\n{'='*60}")
                logger.info(f"  SCRAPING PAGE {page_num} "
                            f"(saved: {self._total_saved}, errors: {self._total_errors}, "
                            f"proxy: {self.proxy_mgr.current_display()})")
                logger.info(f"{'='*60}")

                # --- Load listing page ---
                listing_ok = False
                company_links = []
                for listing_attempt in range(1, 4):
                    try:
                        company_links = self.scrape_listing_page(page_num)
                        listing_ok = True
                        break
                    except SystemExit:
                        raise
                    except Exception as e:
                        logger.error(f"Listing page {page_num} failed "
                                     f"(attempt {listing_attempt}/3): {str(e)[:100]}")
                        if listing_attempt < 3:
                            time.sleep(5)

                if not listing_ok:
                    log_scrape(session, page_num, "failed", error="listing failed 3x")
                    page_num += 1
                    continue

                if not company_links:
                    logger.info(f"No companies found on page {page_num} — done!")
                    log_scrape(session, page_num, "completed", found=0)
                    break

                if start_index > 0:
                    company_links = company_links[start_index:]
                    start_index = 0
                    logger.info(f"  Resuming from index 0 of {len(company_links)} companies")

                # --- Scrape each company ---
                scraped_count = 0
                skipped_count = 0
                for i, link in enumerate(company_links):
                    logger.debug(f"  [{i+1}/{len(company_links)}] {link['slug']}")
                    result = self.scrape_company_detail(link, page_num, session)
                    if result:
                        scraped_count += 1
                    elif company_exists(session, link["slug"]):
                        skipped_count += 1

                log_scrape(session, page_num, "completed",
                           found=len(company_links), scraped=scraped_count)
                pages_scraped += 1

                if pages_scraped % config.LOG_EVERY_N_PAGES == 0:
                    logger.info(
                        f"\n  *** PAGE SUMMARY ***\n"
                        f"  Pages scraped:  {pages_scraped}\n"
                        f"  Current page:    {page_num}\n"
                        f"  Total saved:     {self._total_saved}\n"
                        f"  Total skipped:   {self._total_skipped}\n"
                        f"  Total errors:    {self._total_errors}\n"
                        f"  Proxy rotations: {self.proxy_mgr.rotations}\n"
                        f"  Current proxy:   {self.proxy_mgr.current_display()}\n"
                        f"  This page:       {scraped_count} new, {skipped_count} skipped\n"
                    )

                # --- Check for next page ---
                logger.info(f"  Checking for next page...")
                try:
                    has_next = self._has_next_page(page_num)
                    if not has_next:
                        logger.info(f"No 'Suivant' button on page {page_num} — finished!")
                        break
                except SystemExit:
                    raise
                except Exception as e:
                    logger.error(f"Could not verify next page: {e}")
                    break

                page_num += 1

        except SystemExit:
            logger.info(
                f"\n{'='*60}\n"
                f"  SCRAPING PAUSED\n"
                f"  Saved:    {self._total_saved}\n"
                f"  Skipped:  {self._total_skipped}\n"
                f"  Errors:   {self._total_errors}\n"
                f"  Proxy rotations: {self.proxy_mgr.rotations}\n"
                f"  Resume: python run_scraper.py --start-page {page_num}\n"
                f"{'='*60}"
            )
            raise

        finally:
            self.close()
            if not isinstance(sys.exc_info()[1], SystemExit):
                logger.info(
                    f"\n{'='*60}\n"
                    f"  SCRAPING FINISHED\n"
                    f"  Saved:    {self._total_saved}\n"
                    f"  Skipped:  {self._total_skipped}\n"
                    f"  Errors:   {self._total_errors}\n"
                    f"  Proxy rotations: {self.proxy_mgr.rotations}\n"
                    f"  Last page: {page_num}\n"
                    f"{'='*60}"
                )