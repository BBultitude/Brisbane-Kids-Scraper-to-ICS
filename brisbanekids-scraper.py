from playwright.sync_api import sync_playwright
from datetime import datetime, timezone
import json, html, re, hashlib
from datetime import timezone

# ---------------------------------------------------------
# Generate URLs for this month + next month
# ---------------------------------------------------------
def get_month_urls():
    today = datetime.today()
    this_month = today.replace(day=1)

    # Compute next month
    if this_month.month == 12:
        next_month = this_month.replace(year=this_month.year + 1, month=1)
    else:
        next_month = this_month.replace(month=this_month.month + 1)

    def fmt(dt):
        return f"https://brisbanekids.com.au/events/month/{dt.year}-{dt.month:02d}/"

    return [fmt(this_month), fmt(next_month)]


# ---------------------------------------------------------
# Extract event URLs from a month page
# ---------------------------------------------------------
def collect_event_links(page, url):
    page.goto(url, timeout=60000)
    page.wait_for_timeout(3000)

    events = page.query_selector_all(
        ".tribe-events-calendar-month-mobile-events__mobile-event-details"
    )

    links = []
    for ev in events:
        link_el = ev.query_selector("h3 a")
        if link_el:
            links.append(link_el.get_attribute("href"))

    return links


# ---------------------------------------------------------
# Extract JSON-LD event metadata
# ---------------------------------------------------------
def extract_event_details(page, url):
    page.goto(url, timeout=60000)
    page.wait_for_timeout(2000)

    scripts = page.query_selector_all('script[type="application/ld+json"]')
    event_data = None

    for script in scripts:
        raw = script.inner_text().strip()
        if not raw:
            continue

        try:
            parsed = json.loads(raw)
        except:
            continue

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

    if not event_data:
        return None

    location = event_data.get("location", {})
    address = location.get("address", {})

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


# ---------------------------------------------------------
# ICS Helpers
# ---------------------------------------------------------
def clean_description(desc):
    if not desc:
        return ""
    text = html.unescape(desc)
    text = re.sub("<.*?>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_ics_datetime(dt_str):
    if not dt_str:
        return None
    dt = datetime.fromisoformat(dt_str)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")


def make_uid(url):
    return hashlib.md5(url.encode()).hexdigest() + "@brisbanekids"


def build_ics_event(event):
    start = to_ics_datetime(event["start"])
    end = to_ics_datetime(event["end"])
    desc = clean_description(event["description"])

    location_parts = [
        event["venue"],
        event["street"],
        event["locality"],
        event["region"],
        event["postcode"],
        event["country"]
    ]
    location = ", ".join([p for p in location_parts if p])

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
    body = "\n".join(events)
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//BryanScraper//EN
{body}
END:VCALENDAR"""


# ---------------------------------------------------------
# Main Workflow
# ---------------------------------------------------------
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        month_urls = get_month_urls()
        print("Scraping:", month_urls)

        all_links = set()

        for url in month_urls:
            print(f"\nLoading {url}")
            links = collect_event_links(page, url)
            print(f"Found {len(links)} events")
            all_links.update(links)

        print(f"\nTotal unique event URLs: {len(all_links)}")

        ics_events = []
        for url in all_links:
            details = extract_event_details(page, url)
            if details:
                ics_events.append(build_ics_event(details))

        browser.close()

    ics_data = build_ics_file(ics_events)
    with open("brisbanekids.ics", "w", encoding="utf-8") as f:
        f.write(ics_data)

    print("✅ brisbanekids.ics created successfully!")


if __name__ == "__main__":
    main()
