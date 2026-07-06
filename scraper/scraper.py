"""
Optimus Meknes company scraper using CloakBrowser.

Workflow per page:
  1. Navigate to listing page (with pagination) — verify it loaded
  2. Extract all company links from the listing
  3. Visit each company detail page — verify it loaded
  4. Parse all fields (legal info, contact, coordinates, products, brands)
  5. Save to database via ORM
  6. Log progress every 50 companies
  7. Wait for rate limiting
  8. Move to next page

Rate-limit handling:
  When rate limiting is detected (CONNECTION_REFUSED, 403, 429, blocked page),
  the scraper PAUSES and asks the user to rotate their VPN IP.
  After confirmation, it clears cache, creates a fresh browser context, and resumes.
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

logger = logging.getLogger(__name__)


def parse_french_date(date_str: str) -> Optional[str]:
    """Return raw date string; actual parsing done in db layer."""
    return date_str.strip() if date_str else None


def extract_coordinates_from_osm(osm_url: str) -> tuple[Optional[float], Optional[float]]:
    """Extract lat/lng from an OpenStreetMap link like:
    https://www.openstreetmap.org/?mlat=33.899357&mlon=-5.547927#map=16/...
    """
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

    # Company links are in main content, pointing to /annuaire/<slug>
    skip_prefixes = ("/annuaire/ville", "/annuaire/villes", "/annuaire/secteur", "/annuaire/categorie")
    seen_slugs = set()
    for a in soup.select("main a[href]"):
        href = a.get("href", "")
        if not href.startswith("/annuaire/"):
            continue
        if any(href.startswith(p) for p in skip_prefixes):
            continue
        if "?" in href:  # skip pagination links like ?page=2
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

    # --- Name ---
    h1 = main.find("h1")
    if h1:
        data["name"] = h1.get_text(strip=True)

    # --- Status (e.g. "En activite") ---
    all_text_nodes = main.find_all(string=True)
    for i, node in enumerate(all_text_nodes):
        txt = node.strip()
        if txt in ("En activité", "En activité ", "Fermée", "En cours de création"):
            data["status"] = txt.strip()
            break

    def _find_heading(main_tag, pattern: str):
        """Find an h2 whose text matches pattern (case-insensitive)."""
        for h2 in main_tag.find_all("h2"):
            if re.search(pattern, h2.get_text(strip=True), re.IGNORECASE):
                return h2
        return None

    # --- Description (under Présentation heading) ---
    pres_heading = _find_heading(main, r"^pr.sentation$")
    if pres_heading:
        desc_p = pres_heading.find_next_sibling("p")
        if desc_p:
            data["description"] = desc_p.get_text(strip=True)

    # --- Sector & Category links ---
    for a in main.select("a[href]"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        # Sector links: /annuaire/secteur/commerce (without ?sub=)
        if "/secteur/" in href and "?sub=" not in href and "voir plus" not in text.lower() and not data.get("sector"):
            data["sector"] = text
        # Category links: /annuaire/secteur/commerce?sub=bazar or /annuaire/categorie/...
        elif ("/categorie/" in href or ("/secteur/" in href and "?sub=" in href)) and not data.get("category"):
            data["category"] = text

    # --- Legal info: extract key-value pairs ---
    text_blocks = main.find_all("p")
    key_value_pairs = {}
    for i, p in enumerate(text_blocks):
        txt = p.get_text(strip=True)
        # Look ahead: if next <p> exists, it might be the value
        if i + 1 < len(text_blocks):
            next_txt = text_blocks[i + 1].get_text(strip=True)
            # Common keys
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

    # --- Coordinates from OpenStreetMap link ---
    osm_a = main.find("a", href=re.compile(r"openstreetmap\.org"))
    if osm_a:
        osm_url = osm_a.get("href", "")
        data["osm_url"] = osm_url
        lat, lng = extract_coordinates_from_osm(osm_url)
        data["latitude"] = lat
        data["longitude"] = lng

    # --- Products & Services ---
    prod_heading = _find_heading(main, r"produits.*services")
    if prod_heading:
        # Products are in a <div class="flex flex-wrap gap-2"> with <span> children
        prod_div = prod_heading.find_next_sibling("div")
        if prod_div:
            current_category = None
            for span in prod_div.find_all("span"):
                txt = span.get_text(strip=True)
                if not txt:
                    continue
                # Category lines end with ":"
                if txt.endswith(":"):
                    current_category = txt.rstrip(":").strip()
                elif current_category:
                    data["products"].append({
                        "category_label": current_category,
                        "label": txt.rstrip(","),
                    })

    # --- Brands ---
    brand_heading = _find_heading(main, r"marques")
    if brand_heading:
        # Brands are in a <div> with <span> children
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
    # Connection refused / reset — site blocked the IP
    if any(kw in err_str for kw in ("CONNECTION_REFUSED", "ERR_CONNECTION", "ERR_CONNECTION_RESET")):
        return True
    # HTTP rate-limit status codes
    if any(kw in err_str for kw in ("429", "TOO MANY REQUESTS")):
        return True
    # HTTP forbidden — possible IP block
    if "403" in err_str and ("FORBIDDEN" in err_str or "BLOCKED" in err_str):
        return True
    return False


class OptimusScraper:
    """Main scraper class wrapping CloakBrowser.

    When rate limiting is detected, the scraper:
      1. Pauses and prints a clear message
      2. Waits for the user to press Enter (after rotating VPN IP)
      3. Kills the browser context, clears all cache
      4. Creates a fresh browser context
      5. Retries the failed request
    """

    def __init__(self):
        self.browser = None
        self.page = None
        self._context = None
        self._total_saved = 0
        self._total_skipped = 0
        self._total_errors = 0
        self._ip_rotations = 0  # how many times user rotated IP

    def launch(self):
        """Launch CloakBrowser in headed mode."""
        from cloakbrowser import launch

        logger.info("Launching CloakBrowser (stealth Chromium, HEADED)...")
        self.browser = launch(
            headless=config.CLOAK_HEADLESS,
            humanize=config.CLOAK_HUMANIZE,
        )

        # Create context with ignore HTTPS errors (optimus.ma has cert issues)
        self._context = self.browser.new_context(
            ignore_https_errors=config.CLOAK_IGNORE_HTTPS_ERRORS,
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(config.PAGE_LOAD_TIMEOUT_MS)
        logger.info("CloakBrowser launched (headless=%s, humanize=%s)",
                     config.CLOAK_HEADLESS, config.CLOAK_HUMANIZE)

    def close(self):
        """Close browser."""
        if self._context:
            self._context.close()
        if self.browser:
            self.browser.close()
            logger.info("Browser closed")

    def _clear_context_and_relaunch(self):
        """Kill the current browser context (clears cookies/cache/cookies)
        and create a fresh one — without restarting the browser process."""
        logger.info("Clearing browser context (cookies, cache, localStorage)...")
        try:
            if self._context:
                self._context.clear_cookies()
                self._context.close()
        except Exception:
            pass

        # Fresh context = clean slate
        self._context = self.browser.new_context(
            ignore_https_errors=config.CLOAK_IGNORE_HTTPS_ERRORS,
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(config.PAGE_LOAD_TIMEOUT_MS)
        logger.info("Fresh browser context created — cache cleared")

    def _prompt_ip_rotation(self, url: str, error: Exception):
        """Print a big warning and wait for the user to rotate their VPN IP.
        Returns True after user confirms, or raises if they want to quit."""
        self._ip_rotations += 1

        banner = f"""
{'!'*60}
  RATE LIMITING / IP BLOCKED (rotation #{self._ip_rotations})
{'!'*60}

  URL:    {url}
  Error:  {str(error)[:120]}

  >>> ROTATE YOUR VPN IP NOW <<<
  Change your VPN server to get a new Moroccan IP.
  The scraper is PAUSED and waiting for you.

  After rotating, press ENTER to resume scraping.
  (or type 'q' + ENTER to quit and save progress)
{'!'*60}
"""
        print(banner, flush=True)
        logger.warning(f"RATE LIMIT detected — waiting for user IP rotation #{self._ip_rotations}")

        # Flush logs before blocking on input
        for handler in logger.handlers:
            handler.flush()

        try:
            user_input = input("\n  >>> Press ENTER to resume (or 'q' to quit): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Quitting...")
            raise SystemExit(0)

        if user_input == "q":
            print("  Saving progress and exiting...")
            raise SystemExit(0)

        # User confirmed — clear cache and create fresh context
        print("  IP rotated — clearing cache and resuming...\n", flush=True)
        self._clear_context_and_relaunch()
        time.sleep(2)  # brief pause for new IP to settle

    def _navigate_and_verify(self, url: str, expected_text: str = None) -> str:
        """Navigate to URL, verify it loaded correctly, return HTML.

        On rate-limit detection: pauses for user IP rotation instead of auto-retry.
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

                logger.debug(f"Page loaded in {elapsed:.1f}s, {len(html)} chars")
                return html

            except SystemExit:
                raise  # let quit propagate

            except Exception as e:
                # --- Rate limit detected → ask user to rotate IP ---
                if _is_rate_limited(e):
                    logger.error(f"Rate limit / connection blocked: {str(e)[:100]}")
                    self._prompt_ip_rotation(url, e)
                    # After rotation, retry this attempt (don't consume the attempt)
                    continue

                # --- Other errors: normal retry with short delay ---
                cooldown = config.REQUEST_DELAY_MS / 1000 * attempt
                logger.warning(f"Error on {url} (attempt {attempt}/{config.MAX_RETRIES}): {str(e)[:100]}")
                logger.info(f"  Waiting {cooldown:.0f}s before retry...")
                time.sleep(cooldown)

                if attempt == config.MAX_RETRIES:
                    logger.error(f"All {config.MAX_RETRIES} attempts failed for {url}")
                    raise

    def _has_next_page(self, page_num: int) -> bool:
        """Check if listing page has a 'Suivant' (Next) button."""
        url = config.BASE_URL if page_num == 1 else f"{config.BASE_URL}?page={page_num}"
        html = self._navigate_and_verify(url, expected_text="Entreprises")
        soup = BeautifulSoup(html, "lxml")
        # Check for "Suivant" link
        for a in soup.select("a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if "Suivant" in text and "page=" in href:
                return True
        return False

    def scrape_listing_page(self, page_num: int) -> list[dict]:
        """Scrape one listing page and return company links."""
        if page_num == 1:
            url = config.BASE_URL
        else:
            url = f"{config.BASE_URL}?page={page_num}"

        html = self._navigate_and_verify(url, expected_text="Entreprises")
        links = parse_listing_page(html, config.BASE_URL)

        if not links:
            logger.warning(f"Page {page_num}: 0 company links found — might be empty or blocked")

        # Rate limit: pause after loading listing page
        _jittered_delay(config.LISTING_DELAY_MS)

        logger.info(f"Page {page_num}: found {len(links)} company links")
        return links

    def _log_company_detail(self, data: dict, counter: int):
        """Log a detailed summary of a scraped company."""
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
        """Scrape one company detail page and save to DB."""
        slug = company_link["slug"]
        url = company_link["url"]

        # Skip if already scraped
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

            # Log every Nth company with full detail
            n = config.LOG_EVERY_N_COMPANIES
            if self._total_saved % n == 0:
                self._log_company_detail(data, self._total_saved)
                logger.info(
                    f"  [PROGRESS] Total saved: {self._total_saved} | "
                    f"Skipped (exists): {self._total_skipped} | "
                    f"Errors: {self._total_errors} | "
                    f"IP rotations: {self._ip_rotations}"
                )
            else:
                logger.info(f"  [{self._total_saved}] Saved: {data['name']} "
                            f"(ICE: {data.get('ice', 'N/A')})")

            # Rate limit: wait between company detail pages
            _jittered_delay(config.REQUEST_DELAY_MS)

            return data

        except SystemExit:
            raise  # let quit propagate

        except Exception as e:
            self._total_errors += 1
            logger.error(f"  ERROR scraping {slug}: {e}")
            session.rollback()
            # Non-rate-limit errors: short delay then continue
            time.sleep(config.REQUEST_DELAY_MS / 1000 * 2)
            return None

    def scrape_all(self, session, start_page: int = 1,
                   start_index: int = 0, max_pages: int = 0):
        """Scrape all pages from start_page onwards.

        When rate limiting is detected at any point, the scraper pauses and
        asks the user to rotate their VPN IP. After confirmation it clears
        cache and resumes from exactly where it stopped.

        Args:
            session: SQLAlchemy session
            start_page: page number to resume from
            start_index: company index within the page to resume from
            max_pages: 0 = scrape all pages, N = scrape N pages
        """
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
                            f"(saved: {self._total_saved}, "
                            f"errors: {self._total_errors}, "
                            f"IP rotations: {self._ip_rotations})")
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
                        # Rate limit will already be handled inside _navigate_and_verify
                        # If we get here, it's a non-rate-limit error
                        logger.error(f"Listing page {page_num} failed "
                                     f"(attempt {listing_attempt}/3): {str(e)[:100]}")
                        if listing_attempt < 3:
                            time.sleep(15)
                        else:
                            log_scrape(session, page_num, "failed", error=str(e)[:200])
                            logger.warning(f"Page {page_num} failed 3 times — skipping")
                            page_num += 1

                if not listing_ok:
                    continue  # go to next page

                if not company_links:
                    logger.info(f"No companies found on page {page_num} — done!")
                    log_scrape(session, page_num, "completed", found=0)
                    break

                # Apply start_index for resume
                if start_index > 0:
                    company_links = company_links[start_index:]
                    start_index = 0
                    logger.info(f"  Resuming from index 0 of {len(company_links)} companies")

                # --- Scrape each company detail page ---
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

                # Log page summary every N pages
                if pages_scraped % config.LOG_EVERY_N_PAGES == 0:
                    logger.info(
                        f"\n  *** PAGE SUMMARY ***\n"
                        f"  Pages scraped: {pages_scraped}\n"
                        f"  Current page:   {page_num}\n"
                        f"  Total saved:    {self._total_saved}\n"
                        f"  Total skipped:  {self._total_skipped}\n"
                        f"  Total errors:   {self._total_errors}\n"
                        f"  IP rotations:   {self._ip_rotations}\n"
                        f"  This page:      {scraped_count} new, {skipped_count} skipped\n"
                    )

                # --- Check for next page ---
                logger.info(f"  Checking for next page...")
                try:
                    has_next = self._has_next_page(page_num)
                    if not has_next:
                        logger.info(f"No 'Suivant' (Next) button on page {page_num} — finished!")
                        break
                except SystemExit:
                    raise
                except Exception as e:
                    is_rate = _is_rate_limited(e)
                    if is_rate:
                        # _navigate_and_verify already prompted for IP rotation
                        # Retry the next-page check once more
                        try:
                            has_next = self._has_next_page(page_num)
                            if not has_next:
                                break
                        except SystemExit:
                            raise
                        except Exception as e3:
                            logger.error(f"Next page check failed twice: {e3}")
                            break
                    else:
                        logger.error(f"Could not verify next page: {e}")
                        break

                page_num += 1

        except SystemExit:
            # User chose to quit — save progress
            logger.info(
                f"\n{'='*60}\n"
                f"  SCRAPING PAUSED (user quit)\n"
                f"  Total saved:    {self._total_saved}\n"
                f"  Total skipped:  {self._total_skipped}\n"
                f"  Total errors:   {self._total_errors}\n"
                f"  IP rotations:   {self._ip_rotations}\n"
                f"  Last page:      {page_num}\n"
                f"  Resume with:    python run_scraper.py --start-page {page_num}\n"
                f"{'='*60}"
            )
            raise

        finally:
            self.close()
            if not isinstance(sys.exc_info()[1], SystemExit):
                logger.info(
                    f"\n{'='*60}\n"
                    f"  SCRAPING SESSION FINISHED\n"
                    f"  Total saved:    {self._total_saved}\n"
                    f"  Total skipped:  {self._total_skipped}\n"
                    f"  Total errors:   {self._total_errors}\n"
                    f"  IP rotations:   {self._ip_rotations}\n"
                    f"  Last page:      {page_num}\n"
                    f"{'='*60}"
                )