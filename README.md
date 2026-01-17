# Brisbane Kids Events Calendar Scraper

A Python script that automatically scrapes family-friendly events from [Brisbane Kids](https://brisbanekids.com.au) and generates an ICS calendar file you can import into Google Calendar, Apple Calendar, Outlook, or any other calendar application.

## What It Does

This script:
1. Scrapes the Brisbane Kids events calendar for the **current month** and **next month**
2. Extracts detailed event information (title, date/time, location, description)
3. Generates a standard `.ics` calendar file with all events
4. Outputs `brisbanekids.ics` that you can import into your preferred calendar app

## Why This Exists

Brisbane Kids is a fantastic resource for finding family activities in Brisbane, but manually adding events to your calendar one-by-one is tedious. This script automates the process, letting you import dozens of events at once and keep your family calendar up-to-date effortlessly.

## Requirements

- **Python 3.7+**
- **Playwright** (for web scraping)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/brisbane-kids-scraper.git
cd brisbane-kids-scraper
```

### 2. Set Up Virtual Environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install playwright
```

### 4. Install Playwright Browsers

Playwright needs to download browser binaries (Chromium) to function:

```bash
playwright install chromium
```

## Usage

### Basic Usage

Simply run the script:

```bash
python3 brisbanekids-scraper.py
```

The script will:
- Open a browser window (you can watch the scraping happen)
- Visit Brisbane Kids' event calendar pages
- Extract all events for this month and next month
- Create `brisbanekids.ics` in the same directory

### Running in Headless Mode

If you don't want to see the browser window, edit the script and change:

```python
browser = p.chromium.launch(headless=False)
```

to:

```python
browser = p.chromium.launch(headless=True)
```

### Automated Scheduling with Cron

To keep your calendar automatically updated, you can schedule the scraper to run regularly using cron.

#### Setup Script

Create a shell script `run_scraper.sh`:

```bash
#!/bin/bash
export DISPLAY=:0
cd /home/bryan/scraper-project
source venv/bin/activate
python3 brisbanekids-scraper.py
```

Make it executable:

```bash
chmod +x run_scraper.sh
```

**Note**: Change `/home/bryan/scraper-project` to your actual project path.

#### Add to Crontab

Edit your user crontab:

```bash
crontab -e
```

Add one of these lines depending on how often you want to run it:

```bash
# Run every Monday at 8 AM
0 8 * * 1 /home/bryan/scraper-project/run_scraper.sh

# Run on the 1st of every month at 9 AM
0 9 1 * * /home/bryan/scraper-project/run_scraper.sh

# Run every Sunday at 7 AM
0 7 * * 0 /home/bryan/scraper-project/run_scraper.sh
```

**Important**: When running via cron with headless mode disabled, make sure:
- `DISPLAY=:0` is set (already in the script above)
- You're logged into a graphical session
- Or switch to headless mode for cron jobs

#### Recommended Cron Setup

For automated calendar updates, I recommend:
1. **Set headless mode to `True`** in the Python script
2. **Run monthly** (since the script already grabs current + next month)
3. **Redirect output to a log file** for debugging

Updated crontab entry with logging:

```bash
# Run on the 1st of every month at 9 AM, log output
0 9 1 * * /home/bryan/scraper-project/run_scraper.sh >> /home/bryan/scraper-project/scraper.log 2>&1
```

### Output

After running, you'll get:
- **brisbanekids.ics** - An ICS calendar file containing all scraped events

This file is **overwritten** each time the script runs, so it always contains the most current events.

### Importing to Your Calendar

#### Google Calendar
1. Open [Google Calendar](https://calendar.google.com)
2. Click the **+** button next to "Other calendars"
3. Select **Import**
4. Choose your `brisbanekids.ics` file
5. Select which calendar to add events to
6. Click **Import**

#### Apple Calendar
1. Double-click the `brisbanekids.ics` file
2. Choose which calendar to import into
3. Click **OK**

#### Outlook
1. Open Outlook
2. Go to **File** → **Open & Export** → **Import/Export**
3. Select **Import an iCalendar (.ics) or vCalendar file**
4. Browse to `brisbanekids.ics`
5. Click **OK**

## How It Works

### Technical Overview

The script uses these key technologies:

1. **Playwright**: A browser automation framework that loads JavaScript-heavy web pages
2. **JSON-LD Parsing**: Brisbane Kids embeds structured event data in JSON-LD format (schema.org), which is much cleaner than parsing raw HTML
3. **ICS Generation**: Creates RFC 5545-compliant iCalendar files

### Workflow

```
1. Generate URLs for current/next month
   └─> https://brisbanekids.com.au/events/month/2024-01/

2. Load each month page
   └─> Find all event card links

3. Visit each individual event page
   └─> Extract JSON-LD structured data

4. Convert to ICS format
   └─> Generate VEVENT entries

5. Write brisbanekids.ics file
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `get_month_urls()` | Generates URLs for this month + next month |
| `collect_event_links()` | Extracts event URLs from monthly calendar pages |
| `extract_event_details()` | Parses JSON-LD event metadata from individual event pages |
| `build_ics_event()` | Converts event data to ICS VEVENT format |
| `build_ics_file()` | Wraps all events in a complete VCALENDAR container |

### Why JSON-LD?

Brisbane Kids (like many modern websites) includes structured metadata in JSON-LD format for search engines. This makes scraping much more reliable than parsing HTML because:
- The data structure is standardized (schema.org)
- It's less likely to break when the website design changes
- All event fields are clearly labeled

Example JSON-LD from the page:
```json
{
  "@type": "Event",
  "name": "Story Time at the Library",
  "startDate": "2024-01-25T10:00:00+10:00",
  "endDate": "2024-01-25T11:00:00+10:00",
  "location": {
    "name": "Brisbane City Library",
    "address": {
      "streetAddress": "266 Queen St",
      "addressLocality": "Brisbane City",
      "postalCode": "4000"
    }
  }
}
```

## Customization

### Scraping Different Date Ranges

Edit the `get_month_urls()` function to change which months are scraped. Current logic is:
- This month (starting from day 1)
- Next month

### Changing Output Filename

Modify the final write statement:
```python
with open("brisbanekids.ics", "w", encoding="utf-8") as f:
```

### Script Location and Paths

If you move the script or run it from cron, make sure to update:
- The path in `run_scraper.sh`
- The crontab entry path
- Consider using absolute paths in the Python script for the output file

### Adding More Event Details

If Brisbane Kids includes additional fields in their JSON-LD, you can capture them by:
1. Adding fields to the return dictionary in `extract_event_details()`
2. Including them in the ICS output in `build_ics_event()`

## Troubleshooting

### "playwright: command not found"
Run `pip install playwright` and then `playwright install chromium`

### Browser launches but finds 0 events
The website structure may have changed. Check the CSS selector:
```python
".tribe-events-calendar-month-mobile-events__mobile-event-details"
```

You can inspect the Brisbane Kids website and update the selector if needed.

### Events missing start/end times
Some events may not have complete JSON-LD data. The script will skip events that don't have proper Event metadata.

### Timeout errors
If the website is slow, increase timeout values:
```python
page.goto(url, timeout=60000)  # Increase from 60000 (60 seconds)
```

### Cron job runs but doesn't create file
- Check the log file: `tail -f ~/scraper-project/scraper.log`
- Verify paths are absolute in both the shell script and crontab
- Ensure the virtual environment is activated in the shell script
- Make sure you're using headless mode for unattended runs

## Limitations

- Only scrapes current month + next month (by design, to keep calendar imports manageable)
- Relies on Brisbane Kids maintaining their JSON-LD structure
- Does not handle recurring events differently (each occurrence is treated as separate)
- Some events may lack complete location data depending on how they're entered on the website

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. Some ideas:
- Add command-line arguments for date range selection
- Add filtering by event type/category
- Add support for other Australian kids event websites
- Create a scheduling option (e.g., run monthly via cron)

## License

MIT License - feel free to use and modify as needed.

## Disclaimer

This script is for personal use. Please respect Brisbane Kids' website terms of service and don't overload their servers with excessive requests. The script includes reasonable delays between requests to be respectful of their infrastructure.

## Questions?

Open an issue on GitHub if you encounter problems or have suggestions!

---

**Made with ❤️ for Brisbane families**
