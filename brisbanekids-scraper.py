"""
Brisbane Kids Events Calendar Scraper

This script scrapes event listings from brisbanekids.com.au for the current
and next month, then generates an ICS calendar file that can be imported
into Google Calendar, Apple Calendar, Outlook, etc.

Author: Bryan Bultitude
License: MIT
"""

from playwright.async_api import async_playwright
from datetime import datetime, timezone
import argparse
import asyncio
import json
import html
import logging
import os
import re
import hashlib
import time


# =============================================================================
# URL Generation
# =============================================================================

def get_month_urls():
    """
    Generate URLs for the current month and next month's event pages.

    Brisbane Kids uses a URL pattern: /events/month/YYYY-MM/
    This function calculates the current month and next month, then returns
    their corresponding URLs.

    Returns:
        list: Two URLs as strings, one for this month and one for next month

    Example:
        ['https://brisbanekids.com.au/events/month/2024-01/',
         'https://brisbanekids.com.au/events/month/2024-02/']
    """
    today = datetime.today()
    this_month = today.replace(day=1)

    # Calculate next month (handle year rollover)
    if this_month.month == 12:
        next_month = this_month.replace(year=this_month.year + 1, month=1)
    else:
        next_month = this_month.replace(month=this_month.month + 1)

    def fmt(dt):
        """Format datetime object into Brisbane Kids URL format"""
        return f"https://brisbanekids.com.au/events/month/{dt.year}-{dt.month:02d}/"

    return [fmt(this_month), fmt(next_month)]


def extract_json_ld_from_html(html_text):
    """Parse Event JSON-LD directly from raw HTML string, no DOM needed."""
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE
    )
    for match in pattern.finditer(html_text):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    return item
        elif isinstance(parsed, dict) and parsed.get("@type") == "Event":
            return parsed
    return None


# =============================================================================
# Event Link Collection
# =============================================================================

POPUP_SELECTORS = [
    # Cookie consent / GDPR banners
    "button[aria-label*='close' i]",
    "button[aria-label*='dismiss' i]",
    "button[aria-label*='accept' i]",
    ".cookie-notice-container button",
    "#cookie-notice button",
    ".cn-button",
    # Newsletter / subscription popups
    ".pum-close",              # Popup Maker plugin
    ".popup-close",
    ".close-popup",
    "[class*='popup'] [class*='close']",
    "[class*='modal'] [class*='close']",
    # Generic dismiss patterns
    "button.close",
    ".dismiss",
]

# Block ad/tracking domains and binary assets that can hang page loads
BLOCKED_PATTERNS = [
    # Ad/tracking domains
    "*googlesyndication*", "*doubleclick*", "*googletagmanager*",
    "*google-analytics*", "*facebook.net*", "*hotjar*",
    "*adnxs*", "*moatads*", "*criteo*",
    # Additional tracking/ad domains confirmed in page source
    "*ads.adthrive.com*",
    "*chimpstatic.com*",
    "*static.cloudflareinsights.com*",
    "*html-load.com*",
    "*scorecardresearch.com*",
    "*openstreetmap.org*",
    # Images, fonts, and media — not needed to extract JSON-LD
    "**/*.{png,jpg,jpeg,gif,webp,svg,ico,avif,woff,woff2,ttf,otf,eot,mp4,mp3}",
    # CSS stylesheets — safe to block; all use async media-swap pattern
    # and do not affect domcontentloaded or JS execution
    "**/*.css*",
]


async def dismiss_popups(page):
    """Click any visible popup/overlay dismiss buttons."""
    for selector in POPUP_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass


async def collect_event_links(page, url):
    """
    Navigate to a monthly calendar page and extract all individual event URLs.

    The Brisbane Kids website displays events in a mobile-friendly card layout.
    Each event card contains a link to the full event details page. This
    function finds all those links using the specific CSS selector for the
    mobile event layout.

    Args:
        page: Playwright page object (browser tab)
        url: The monthly calendar URL to scrape

    Returns:
        list: URLs (strings) to individual event detail pages
    """
    log = logging.getLogger(__name__)
    # Use domcontentloaded so popups/ads don't block the load event
    t0 = time.perf_counter()
    await page.goto(url, timeout=60000, wait_until="domcontentloaded")
    log.debug("MONTH  goto        %.1fs  %s", time.perf_counter() - t0, url)

    # Wait for JS to finish rendering events (blocked resources make this fast)
    t1 = time.perf_counter()
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
        log.debug("MONTH  networkidle %.1fs  %s", time.perf_counter() - t1, url)
    except Exception:
        log.debug("MONTH  networkidle TIMEOUT %.1fs  %s", time.perf_counter() - t1, url)

    t2 = time.perf_counter()
    try:
        await page.wait_for_selector(
            ".tribe-events-calendar-month-mobile-events__mobile-event-details",
            timeout=15000
        )
        log.debug("MONTH  selector    %.1fs  %s", time.perf_counter() - t2, url)
    except Exception:
        log.warning("MONTH no-events  %s (selector timed out)", url)
        return []
    await page.evaluate("window.stop()")
    await dismiss_popups(page)

    # Find all event cards on the page
    events = await page.query_selector_all(
        ".tribe-events-calendar-month-mobile-events__mobile-event-details"
    )

    # Extract the href attribute from each event's title link
    links = []
    for ev in events:
        link_el = await ev.query_selector("h3 a")
        if link_el:
            href = await link_el.get_attribute("href")
            if href:
                links.append(href)

    return links


# =============================================================================
# Event Detail Extraction
# =============================================================================

async def extract_event_details(page, url):
    """
    Extract structured event data from an individual event page.

    Brisbane Kids embeds event metadata in JSON-LD format (a type of structured
    data that search engines use). This script parses that JSON-LD to extract
    clean, structured event information rather than scraping HTML.

    JSON-LD is embedded in <script type="application/ld+json"> tags and follows
    the schema.org Event format.

    Args:
        page: Playwright page object
        url: URL of the individual event page

    Returns:
        dict: Event details with keys: title, description, start, end, venue,
              street, locality, region, postcode, country, url
        None: If no valid Event JSON-LD is found
    """
    log = logging.getLogger(__name__)
    t0 = time.perf_counter()
    await page.goto(url, timeout=90000, wait_until="domcontentloaded")
    log.debug("EVENT  goto %.1fs  %s", time.perf_counter() - t0, url)

    html_text = await page.content()

    event_data = extract_json_ld_from_html(html_text)
    if not event_data:
        logging.getLogger(__name__).info("SKIP no-json-ld  %s", url)
        return None

    # Extract location information (can be nested)
    location = event_data.get("location", {})
    if not isinstance(location, dict):
        location = {}
    address = location.get("address", {})
    if not isinstance(address, dict):
        address = {}

    # Return flattened, clean structure
    return {
        "title": event_data.get("name"),
        "description": event_data.get("description"),
        "start": event_data.get("startDate"),
        "end": event_data.get("endDate"),
        "venue": location.get("name"),
        "street": address.get("streetAddress"),
        "locality": address.get("addressLocality"),
        "region": address.get("addressRegion"),
        "postcode": address.get("postalCode"),
        "country": address.get("addressCountry"),
        "url": event_data.get("url")
    }


# =============================================================================
# ICS Calendar File Generation
# =============================================================================

def clean_description(desc):
    """
    Convert HTML description to plain text for ICS files.

    Event descriptions often contain HTML tags and entities. This function:
    1. Decodes HTML entities (&amp; → &, &nbsp; → space, etc.)
    2. Strips all HTML tags
    3. Normalizes whitespace

    Args:
        desc: Raw HTML description string

    Returns:
        str: Plain text description safe for ICS format
    """
    if not desc:
        return ""

    # Decode HTML entities (e.g., &amp; → &)
    text = html.unescape(desc)

    # Remove all HTML tags
    text = re.sub("<.*?>", "", text)

    # Collapse multiple spaces/newlines into single spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def to_ics_datetime(dt_str):
    """
    Convert ISO 8601 datetime string to ICS format (UTC).

    ICS files use the format: YYYYMMDDTHHMMSSz
    Example: 20240125T140000Z (Jan 25, 2024, 2:00 PM UTC)

    Args:
        dt_str: ISO 8601 datetime string (e.g., '2024-01-25T14:00:00+10:00')

    Returns:
        str: ICS-formatted datetime string in UTC
        None: If dt_str is None or invalid
    """
    if not dt_str:
        return None

    # Parse ISO format and convert to UTC
    dt = datetime.fromisoformat(dt_str)
    dt_utc = dt.astimezone(timezone.utc)

    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def make_uid(url):
    """
    Generate a unique identifier for the event.

    ICS files require unique UIDs for each event. This creates a stable UID
    based on the event's URL using MD5 hashing. The same URL will always
    produce the same UID, which helps calendar apps recognize duplicate events.

    Args:
        url: The event's URL

    Returns:
        str: UID in format 'hash@brisbanekids'
    """
    hash_value = hashlib.md5(url.encode()).hexdigest()
    return f"{hash_value}@brisbanekids"


def build_ics_event(event):
    """
    Build an ICS VEVENT entry from event data.

    Creates a properly formatted iCalendar event block following RFC 5545.
    Each event contains:
    - UID: Unique identifier
    - DTSTAMP: When this entry was created
    - DTSTART/DTEND: Start and end times (UTC)
    - SUMMARY: Event title
    - DESCRIPTION: Event details (plain text)
    - LOCATION: Full address
    - URL: Link back to original event page

    Args:
        event: Dictionary with event details from extract_event_details()

    Returns:
        str: ICS VEVENT block
    """
    start = to_ics_datetime(event["start"])
    end = to_ics_datetime(event["end"])
    desc = clean_description(event["description"])

    # Build comma-separated location string from available parts
    location_parts = [
        event["venue"],
        event["street"],
        event["locality"],
        event["region"],
        event["postcode"],
        event["country"]
    ]
    location = ", ".join([p for p in location_parts if p])

    # Return formatted VEVENT block
    return f"""BEGIN:VEVENT
UID:{make_uid(event["url"])}
DTSTAMP:{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}
DTSTART:{start}
DTEND:{end}
SUMMARY:{event["title"]}
DESCRIPTION:{desc}
LOCATION:{location}
URL:{event["url"]}
END:VEVENT"""


def build_ics_file(events):
    """
    Wrap all events in a complete ICS calendar file.

    Creates the VCALENDAR container with required metadata and includes
    all VEVENT entries.

    Args:
        events: List of VEVENT strings from build_ics_event()

    Returns:
        str: Complete ICS file content
    """
    body = "\n".join(events)

    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//BryanScraper//EN
{body}
END:VCALENDAR"""


# =============================================================================
# Main Execution
# =============================================================================

MAX_CONCURRENT = 5   # per-browser concurrency (matches Chromium's 6-per-host limit)
N_BROWSERS = 1       # separate OS processes; each gets its own connection pool
MAX_RETRIES = 2
RETRY_DELAY_SECS = 5


async def process_browser_slice(p, url_slice, log):
    """
    One Chromium process scrapes its assigned slice of event URLs.
    Each call creates an independent browser with its own TCP connection pool.
    """
    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()
    for pattern in BLOCKED_PATTERNS:
        await context.route(pattern, lambda route: route.abort())

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def scrape_one(url):
        async with semaphore:
            last_error = None
            for attempt in range(1, MAX_RETRIES + 2):
                page = await context.new_page()
                t0 = time.perf_counter()
                try:
                    result = await extract_event_details(page, url)
                    elapsed = time.perf_counter() - t0
                    if result is None:
                        log.debug("SKIP    %5.1fs  %s", elapsed, url)
                    else:
                        log.info( "SUCCESS %5.1fs  %s", elapsed, url)
                    return result
                except Exception as e:
                    elapsed = time.perf_counter() - t0
                    last_error = e
                    if attempt <= MAX_RETRIES and "Timeout" in str(e):
                        log.warning("TIMEOUT %5.1fs  %s (attempt %d/%d), retrying in %ds...",
                                    elapsed, url, attempt, MAX_RETRIES + 1, RETRY_DELAY_SECS)
                        await asyncio.sleep(RETRY_DELAY_SECS)
                    else:
                        log.error("ERROR   %5.1fs  %s: %s", elapsed, url, e, exc_info=True)
                        return None
                finally:
                    await page.close()
            log.error("GIVE UP %s after %d attempts: %s", url, MAX_RETRIES + 1, last_error)
            return None

    results = await asyncio.gather(*[scrape_one(url) for url in url_slice])
    await context.close()
    await browser.close()
    return results


async def main():
    """
    Main workflow:
    1. Launch a browser using Playwright
    2. Scrape this month and next month's event listings
    3. Visit each event page concurrently to extract detailed information
    4. Generate an ICS calendar file with all events
    5. Save to brisbanekids.ics
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                        help="Enable DEBUG logging (shows SKIP lines with timing)")
    args = parser.parse_args()
    log_level = logging.DEBUG if args.debug else getattr(
        logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
    )

    async with async_playwright() as p:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=[
                logging.FileHandler("scraper.log"),
                logging.StreamHandler(),
            ],
        )
        log = logging.getLogger(__name__)
        run_start = time.perf_counter()

        # Launch Chromium browser (headless=False required for Cloudflare bot detection)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # Apply block rules once at context level (inherited by all pages)
        for pattern in BLOCKED_PATTERNS:
            await context.route(pattern, lambda route: route.abort())

        # Phase 1: collect links — parallel across 2 month pages
        month_urls = get_month_urls()
        log.info("MONTHS   scraping %s", month_urls)

        all_links = set()

        async def collect_month(url):
            log.info("MONTH    loading %s", url)
            t0 = time.perf_counter()
            page = await context.new_page()
            try:
                links = await collect_event_links(page, url)
            except Exception as e:
                log.error("MONTH    ERROR %s: %s", url, e, exc_info=True)
                links = []
            finally:
                await page.close()
            log.info("MONTH    found %d events in %.1fs at %s", len(links),
                     time.perf_counter() - t0, url)
            return links

        for url in month_urls:
            links = await collect_month(url)
            all_links.update(links)

        log.info("MONTH    total unique event URLs: %d", len(all_links))

        # Phase 2: partition URLs across N browsers
        all_links_list = list(all_links)
        chunk_size = (len(all_links_list) + N_BROWSERS - 1) // N_BROWSERS
        slices = [
            all_links_list[i * chunk_size:(i + 1) * chunk_size]
            for i in range(N_BROWSERS)
            if i * chunk_size < len(all_links_list)
        ]

        await context.close()
        await browser.close()

        log.info("EVENTS   scraping %d events (%d browsers × %d concurrent, up to %d retries)",
                 len(all_links), len(slices), MAX_CONCURRENT, MAX_RETRIES)

        results_nested = await asyncio.gather(
            *[process_browser_slice(p, s, log) for s in slices]
        )
        results = [r for sublist in results_nested for r in sublist]

    succeeded = [r for r in results if r is not None]
    log.info("SUMMARY  %d/%d events extracted successfully in %.0fs total",
             len(succeeded), len(results), time.perf_counter() - run_start)

    log.info("ICS      building calendar file")
    ics_events = []
    for r in succeeded:
        try:
            ics_events.append(build_ics_event(r))
        except Exception as e:
            log.error("ICS      ERROR building event %s: %s", r.get("url", "?"), e, exc_info=True)

    log.info("ICS      built %d VEVENT entries", len(ics_events))
    try:
        ics_data = build_ics_file(ics_events)
        with open("brisbanekids.ics", "w", encoding="utf-8") as f:
            f.write(ics_data)
        log.info("ICS      written to brisbanekids.ics (%d events)", len(ics_events))
    except Exception as e:
        log.error("ICS      ERROR writing file: %s", e, exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
