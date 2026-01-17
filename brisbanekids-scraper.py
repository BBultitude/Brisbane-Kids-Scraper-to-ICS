"""
Brisbane Kids Events Calendar Scraper

This script scrapes event listings from brisbanekids.com.au for the current 
and next month, then generates an ICS calendar file that can be imported 
into Google Calendar, Apple Calendar, Outlook, etc.

Author: Bryan Bultitude
License: MIT
"""

from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import json
import html
import re
import hashlib


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


# =============================================================================
# Event Link Collection
# =============================================================================

def collect_event_links(page, url):
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
    # Load the page and wait for dynamic content to render
    page.goto(url, timeout=60000)
    page.wait_for_timeout(3000)  # Give JavaScript time to populate events

    # Find all event cards on the page
    events = page.query_selector_all(
        ".tribe-events-calendar-month-mobile-events__mobile-event-details"
    )

    # Extract the href attribute from each event's title link
    links = []
    for ev in events:
        link_el = ev.query_selector("h3 a")
        if link_el:
            href = link_el.get_attribute("href")
            if href:
                links.append(href)

    return links


# =============================================================================
# Event Detail Extraction
# =============================================================================

def extract_event_details(page, url):
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
    page.goto(url, timeout=60000)
    page.wait_for_timeout(2000)

    # Find all JSON-LD script tags on the page
    scripts = page.query_selector_all('script[type="application/ld+json"]')
    event_data = None

    # Parse each script tag looking for Event type
    for script in scripts:
        raw = script.inner_text().strip()
        if not raw:
            continue

        # Safely parse JSON
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # Handle both array and object JSON-LD formats
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    event_data = item
                    break
        elif isinstance(parsed, dict):
            if parsed.get("@type") == "Event":
                event_data = parsed

        if event_data:
            break

    # If no Event data found, skip this URL
    if not event_data:
        return None

    # Extract location information (can be nested)
    location = event_data.get("location", {})
    address = location.get("address", {})

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

def main():
    """
    Main workflow:
    1. Launch a browser using Playwright
    2. Scrape this month and next month's event listings
    3. Visit each event page to extract detailed information
    4. Generate an ICS calendar file with all events
    5. Save to brisbanekids.ics
    """
    with sync_playwright() as p:
        # Launch Chromium browser (headless=False shows browser window)
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # Generate URLs for this month and next month
        month_urls = get_month_urls()
        print("Scraping:", month_urls)

        # Collect all unique event URLs across both months
        all_links = set()  # Use set to automatically deduplicate
        
        for url in month_urls:
            print(f"\nLoading {url}")
            links = collect_event_links(page, url)
            print(f"Found {len(links)} events")
            all_links.update(links)

        print(f"\nTotal unique event URLs: {len(all_links)}")

        # Extract details from each event and build ICS entries
        ics_events = []
        for i, url in enumerate(all_links, 1):
            print(f"Processing event {i}/{len(all_links)}...")
            details = extract_event_details(page, url)
            if details:
                ics_events.append(build_ics_event(details))

        browser.close()

    # Write final ICS file
    ics_data = build_ics_file(ics_events)
    with open("brisbanekids.ics", "w", encoding="utf-8") as f:
        f.write(ics_data)

    print(f"\n✅ brisbanekids.ics created successfully with {len(ics_events)} events!")


if __name__ == "__main__":
    main()
