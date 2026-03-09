"""
ff_scraper.py — ForexFactory calendar scraper using cloudscraper + BeautifulSoup.

No Selenium. No ChromeDriver. No binaries. Pure HTTP + HTML parsing.

Usage (CLI):
    python -m src.ff_scraper --start 2026-02-06 --end 2026-02-27 --csv data/ff_events.csv

Output CSV columns (same format data_loader.py expects):
    DateTime, Currency, Impact, Event, Actual, Forecast, Previous
"""
# ↑ Docstring for this file.
#   This scraper fetches the ForexFactory economic calendar (forexfactory.com) — a website
#   that lists upcoming economic announcements (like US jobs reports, inflation data, etc.).
#   It uses HTTP requests (no browser needed) and parses the HTML to extract event data.

from __future__ import annotations
# ↑ Modern type hint handling. Safe to ignore as a beginner.

import argparse
# ↑ Python's built-in library for parsing command-line arguments.
#   When you run: python -m src.ff_scraper --start 2026-02-06 --end 2026-02-27
#   argparse reads those "--start" and "--end" flags and makes them available as variables.

import logging
# ↑ Python's built-in logging library. More powerful than plain print() — it adds
#   timestamps and log levels (INFO, WARNING, ERROR) to messages automatically.
#   You'll see output like: "2026-03-07 10:30:00 [INFO] Fetching ..."

import re
# ↑ Python's built-in 're' (regular expressions) module.
#   Regular expressions are patterns used to search and extract text.
#   Example: re.match(r"(\d{2}):(\d{2})", "09:30") extracts "09" and "30" from a time string.

import time
# ↑ Python's built-in 'time' module for time-related utilities.
#   Here we use time.sleep(seconds) to pause between web requests (polite scraping).
#   Note: 'time' the module vs 'time' the class from datetime — they are different things.

from datetime import date, datetime, timedelta
# ↑ From the 'datetime' module, imports three classes:
#   date      → represents a calendar date (year, month, day), no time component.
#   datetime  → represents a full timestamp (date + time).
#   timedelta → represents a duration (e.g., 1 day, 2 hours).

from pathlib import Path
# ↑ Cross-platform file path handling. Path objects let you build paths with / operator.

import cloudscraper
# ↑ Third-party library (installed via pip). cloudscraper creates HTTP sessions that
#   can bypass Cloudflare's bot protection, which ForexFactory uses.
#   It works by mimicking a real browser's HTTP headers and TLS fingerprint.

import pandas as pd
# ↑ Pandas for building and saving the results table to a CSV.

import pytz
# ↑ Timezone library. Used to attach Eastern timezone to the parsed event datetimes.

from bs4 import BeautifulSoup
# ↑ Imports 'BeautifulSoup' from the 'bs4' (Beautiful Soup 4) library.
#   Beautiful Soup is the standard Python HTML parser — it reads raw HTML from a webpage
#   and lets you search it like a structured document (find elements by tag, class, etc.).

logging.basicConfig(
    # ↑ Configures the logging system. This sets global logging settings for the whole script.
    level=logging.INFO,
    # ↑ Sets the minimum log level to INFO. Messages at INFO, WARNING, and ERROR will be shown.
    #   DEBUG messages (more verbose) will be hidden.
    format="%(asctime)s [%(levelname)s] %(message)s",
    # ↑ Defines how each log line looks. The % placeholders are filled automatically:
    #   %(asctime)s   → current timestamp, e.g., "2026-03-07 10:30:00".
    #   %(levelname)s → the level name, e.g., "INFO" or "WARNING".
    #   %(message)s   → the actual message you logged.
    datefmt="%Y-%m-%d %H:%M:%S",
    # ↑ Format for the timestamp: Year-Month-Day Hour:Minute:Second.
)

logger = logging.getLogger(__name__)
# ↑ Creates a logger object for this specific module.
#   __name__ is a special Python variable that equals the module's name (e.g., "src.ff_scraper").
#   Using __name__ lets us trace which file generated each log message in larger applications.

EASTERN = pytz.timezone("America/New_York")
# ↑ Eastern timezone object for New York. Handles daylight saving automatically.

FF_BASE = "https://www.forexfactory.com"
# ↑ The base URL of the ForexFactory website. We'll append paths to this to build full URLs.


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _make_scraper() -> cloudscraper.CloudScraper:
# ↑ Creates and configures an HTTP session capable of bypassing Cloudflare protection.
#   -> cloudscraper.CloudScraper → returns the configured session object.
    """Return a cloudscraper session that handles Cloudflare JS challenges."""

    scraper = cloudscraper.create_scraper(
        # ↑ Creates a CloudScraper session with browser-like settings.
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        # ↑ Tells cloudscraper to impersonate Chrome on macOS (darwin = macOS).
        #   This makes the HTTP requests look like they come from a real Mac running Chrome,
        #   which helps bypass Cloudflare's bot detection.
        #   "mobile": False → pretend to be a desktop browser, not a phone.
    )

    scraper.headers.update({
        # ↑ .headers is a dictionary of HTTP request headers sent with every request.
        #   .update({}) adds or replaces entries in the dictionary.
        #   Headers tell the server things like: what browser we are, what language we prefer, etc.
        "Accept-Language": "en-US,en;q=0.9",
        # ↑ Tells the server we prefer English (US). q=0.9 means 90% preference.
        #   Websites use this to serve content in the right language.
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        # ↑ Tells the server what types of content we can handle. This mimics what a real browser sends.
        #   "text/html" = we want web pages; "*/*;q=0.8" = we accept anything else too.
    })

    return scraper
    # ↑ Returns the configured session. We'll use this to make all HTTP requests.


# ---------------------------------------------------------------------------
# Per-day fetch + parse
# ---------------------------------------------------------------------------

def _parse_time(time_text: str, day: date, last_hhmm: tuple | None) -> tuple[datetime, tuple]:
# ↑ Converts a ForexFactory time string (like "8:30am") to a proper datetime object.
#   ForexFactory sometimes omits the time (events inherit the previous event's time),
#   so we carry forward the last seen time in 'last_hhmm'.
#   Parameters:
#     time_text: str          → the raw time string from the HTML (e.g., "8:30am", "All Day", "").
#     day: date               → the calendar date this event is on.
#     last_hhmm: tuple | None → the last successfully parsed (hour, minute) tuple, or None if first event.
#   -> tuple[datetime, tuple] → returns (parsed datetime, (hour, minute)) pair.
    """
    Convert a ForexFactory time string to an Eastern-tz datetime.
    Returns (datetime, (hh, mm)) so the caller can carry it forward.
    """

    t = time_text.strip().lower()
    # ↑ Strips whitespace and converts to lowercase for consistent matching.
    #   "8:30am" → "8:30am", "  All Day  " → "all day".

    if not t and last_hhmm:
        # ↑ If the time string is empty AND we have a previous time to fall back to:
        #   'not t' → an empty string is "falsy" in Python, so 'not ""' is True.
        hh, mm = last_hhmm
        # ↑ Unpacks the last known (hour, minute) tuple into separate variables.
        #   E.g., if last_hhmm = (8, 30), then hh = 8 and mm = 30.

    elif "day" in t:
        # ↑ "all day" or "all day" events — assigned to end of day.
        hh, mm = 23, 59
        # ↑ Set to 23:59 (11:59 PM) to sort all-day events after time-specific ones.

    elif "data" in t or "tentative" in t:
        # ↑ "data" or "tentative" means no specific release time is known.
        hh, mm = 0, 0
        # ↑ Default to midnight (00:00).

    else:
        m = re.match(r"(\d{1,2}):(\d{2})(am|pm)", t)
        # ↑ Uses a regular expression to parse a time string like "8:30am" or "12:00pm".
        #   re.match(pattern, string) → tries to match the pattern at the START of the string.
        #   r"(\d{1,2}):(\d{2})(am|pm)" → the pattern:
        #     (\d{1,2}) → captures 1 or 2 digits (the hours). \d = any digit 0-9. {1,2} = 1 or 2 of them.
        #     :         → matches a literal colon.
        #     (\d{2})   → captures exactly 2 digits (the minutes).
        #     (am|pm)   → captures either "am" or "pm".
        #   Result: m is a match object if the pattern matched, or None if it didn't.

        if m:
            # ↑ If the regex matched successfully (m is not None).
            hh = int(m.group(1))
            # ↑ m.group(1) → the first captured group (hours as a string, e.g., "8").
            #   int() converts it to an integer: "8" → 8.
            mm = int(m.group(2))
            # ↑ m.group(2) → the second captured group (minutes as a string, e.g., "30").

            if m.group(3) == "pm" and hh < 12:
                # ↑ If it's PM and not already noon (12:xx pm is already correct).
                hh += 12
                # ↑ Add 12 to convert 12-hour PM to 24-hour format: 1pm → 13, 8pm → 20, etc.

            if m.group(3) == "am" and hh == 12:
                # ↑ Special case: 12:00 AM (midnight) in 12-hour format = 0:00 in 24-hour format.
                hh = 0
                # ↑ Correct midnight: 12am → 0.

        elif last_hhmm:
            # ↑ If the regex didn't match (unrecognized format) AND we have a fallback time.
            hh, mm = last_hhmm
            # ↑ Use the last known time.

        else:
            hh, mm = 0, 0
            # ↑ No match and no fallback — default to midnight.

    dt = EASTERN.localize(datetime(day.year, day.month, day.day, hh, mm, 0))
    # ↑ Creates a timezone-aware datetime for this event.
    #   datetime(year, month, day, hour, minute, second) → creates a naive datetime.
    #     day.year, day.month, day.day → extracts year/month/day from the 'day' date object.
    #     hh, mm, 0                    → the parsed hour, minute, and 0 seconds.
    #   EASTERN.localize(...)          → attaches the Eastern timezone to the naive datetime.
    #     This is how pytz recommends creating timezone-aware datetimes (not using tz= directly).

    return dt, (hh, mm)
    # ↑ Returns the datetime AND the (hh, mm) tuple so the next event can use it as last_hhmm.


_IMPACT_CLASS_MAP = {
    # ↑ A dictionary mapping ForexFactory CSS class names to human-readable impact levels.
    #   ForexFactory doesn't write "High Impact" in plain text — it encodes it via CSS classes
    #   on colored icon elements. We decode those class names here.
    "icon--ff-impact-red": "High Impact Expected",
    # ↑ Red icon = High Impact (e.g., NFP, CPI, FOMC decisions).
    "icon--ff-impact-ora": "Medium Impact Expected",
    # ↑ Orange icon = Medium Impact.
    "icon--ff-impact-yel": "Low Impact Expected",
    # ↑ Yellow icon = Low Impact.
    "icon--ff-impact-gry": "Non-Economic",
    # ↑ Grey icon = Non-Economic (e.g., speeches, holidays).
}

def _parse_impact(impact_td) -> str:
# ↑ Extracts the impact level from the HTML <td> element that contains the impact icon.
#   Parameter:
#     impact_td → a BeautifulSoup Tag object representing the <td> cell in the HTML table.
#                 It can also be None if the cell wasn't found.
#   -> str      → returns the impact string like "High Impact Expected" or "" if not found.
    """
    Extract impact level from the impact <td>.
    ForexFactory encodes impact via CSS class on the inner <span>:
      icon--ff-impact-red → High
      icon--ff-impact-ora → Medium
      icon--ff-impact-yel → Low
      icon--ff-impact-gry → Non-Economic
    """

    if impact_td is None:
        # ↑ If no impact cell was found in the HTML row.
        return ""
        # ↑ Return empty string — no impact info available.

    span = impact_td.find("span")
    # ↑ Inside the <td>, there's a <span> element that holds the colored icon.
    #   .find("span") → searches for the first <span> child element.
    #   Returns the span element if found, or None if not.

    if span:
        # ↑ If we found a <span> element.
        for cls in span.get("class", []):
            # ↑ Gets the list of CSS classes on the span element.
            #   span.get("class", []) → like a dictionary lookup: get the "class" attribute,
            #                           return an empty list [] if it doesn't exist.
            #   HTML: <span class="icon icon--ff-impact-red"> → class list is ["icon", "icon--ff-impact-red"].
            #   for cls in ... → loops over each class name in the list.

            if cls in _IMPACT_CLASS_MAP:
                # ↑ Checks if this CSS class name is one of our known impact class names.
                #   'in' tests dictionary key membership.
                return _IMPACT_CLASS_MAP[cls]
                # ↑ Returns the human-readable impact level for this class name.
                #   e.g., "icon--ff-impact-red" → "High Impact Expected".

    return ""
    # ↑ No matching class found — return empty string.


def fetch_day(scraper: cloudscraper.CloudScraper, day: date) -> list[dict]:
# ↑ Downloads and parses the ForexFactory calendar page for a single day.
#   Parameters:
#     scraper: cloudscraper.CloudScraper → the HTTP session created by _make_scraper().
#     day: date                          → the specific calendar date to fetch.
#   -> list[dict]                        → returns a list of event dictionaries (one per event row).
    """
    Fetch and parse ForexFactory calendar for a single day.
    Returns a list of event dicts.
    """

    date_str = day.strftime("%b%d.%Y").lower()
    # ↑ Formats the date into the URL format ForexFactory expects.
    #   .strftime(format) → converts a date to a string using the given format.
    #   "%b%d.%Y" → abbreviated month + day + year: date(2026,2,6) → "Feb06.2026".
    #   .lower()   → lowercases it: "Feb06.2026" → "feb06.2026".

    url = f"{FF_BASE}/calendar?day={date_str}"
    # ↑ Builds the full URL for this day's calendar page.
    #   e.g., "https://www.forexfactory.com/calendar?day=feb06.2026".

    logger.info(f"  Fetching {url}")
    # ↑ Logs an INFO message so you can see the scraper's progress in the terminal.

    resp = scraper.get(url, timeout=30)
    # ↑ Makes an HTTP GET request to the URL.
    #   GET is the standard HTTP method for fetching a webpage (like clicking a link).
    #   timeout=30 → if the server doesn't respond within 30 seconds, raise an error (don't hang forever).
    #   resp → the HTTP response object containing the status code and page content.

    if resp.status_code != 200:
        # ↑ HTTP status code 200 means "OK" (success). Other codes indicate problems:
        #   403 = Forbidden, 404 = Not Found, 429 = Too Many Requests, 500 = Server Error.
        logger.warning(f"  HTTP {resp.status_code} for {day} — skipping")
        # ↑ Logs a WARNING (not ERROR — we just skip this day and continue).
        return []
        # ↑ Returns an empty list for this day — no events to report.

    soup = BeautifulSoup(resp.text, "html.parser")
    # ↑ Parses the HTML content of the response into a searchable BeautifulSoup object.
    #   resp.text      → the raw HTML string of the webpage (thousands of characters).
    #   "html.parser"  → tells BeautifulSoup to use Python's built-in HTML parser.
    #   Result: 'soup' is a tree-like object we can navigate and search.

    table = soup.find("table", class_=re.compile(r"calendar__table"))
    # ↑ Searches the HTML for the main calendar table element.
    #   soup.find(tag, class_=...) → finds the FIRST element matching the tag + class.
    #   "table"                     → we're looking for a <table> HTML element.
    #   class_=re.compile(...)      → matches any class containing "calendar__table" as a pattern.
    #     re.compile(r"calendar__table") → compiles a regex pattern for partial class matching.
    #   Result: 'table' is the BeautifulSoup element for the calendar table, or None if not found.

    if not table:
        # ↑ If no calendar table was found in the HTML (page structure may have changed or blocked).
        logger.warning(f"  No calendar table found for {day}")
        # ↑ Log a warning.
        return []
        # ↑ Return empty list — nothing to parse.

    rows = table.find_all("tr", class_=re.compile(r"calendar__row"))
    # ↑ Finds ALL rows (<tr> elements) inside the table that have "calendar__row" in their class.
    #   .find_all() → returns a LIST of all matching elements (unlike .find() which returns only the first).
    #   Each row represents one economic event (or a day separator).

    records: list[dict] = []
    # ↑ Empty list to collect the parsed event dictionaries.
    #   ': list[dict]' is a type annotation — tells us this will be a list of dictionaries.

    last_hhmm: tuple | None = None
    # ↑ Tracks the last successfully parsed time (hour, minute).
    #   Starts as None — no previous time yet.
    #   Type annotation: 'tuple | None' means it can be a tuple or None.

    for row in rows:
        # ↑ Loops over each table row found above.

        cls = " ".join(row.get("class", []))
        # ↑ Gets all CSS class names on this row and joins them into one string.
        #   row.get("class", []) → list of class names, e.g., ["calendar__row", "calendar__row--grey"].
        #   " ".join([...])      → joins with spaces: "calendar__row calendar__row--grey".
        #   This makes it easy to check if a class name appears anywhere with 'in'.

        if "day-breaker" in cls or "no-event" in cls:
            # ↑ Skips rows that are not actual events:
            #   "day-breaker" → a row that shows the date header (not an event row).
            #   "no-event"    → a placeholder row for days with no events.
            continue
            # ↑ Skip to the next row.

        time_td     = row.find("td", class_=re.compile(r"calendar__time"))
        # ↑ Finds the <td> cell containing the event time.
        #   row.find("td", class_=...) → searches within this row for a <td> with matching class.
        currency_td = row.find("td", class_=re.compile(r"calendar__currency"))
        # ↑ Finds the <td> containing the currency code (e.g., "USD", "EUR").
        impact_td   = row.find("td", class_=re.compile(r"calendar__impact"))
        # ↑ Finds the <td> containing the impact icon.
        event_td    = row.find("td", class_=re.compile(r"calendar__event"))
        # ↑ Finds the <td> containing the event name (e.g., "Non-Farm Employment Change").
        actual_td   = row.find("td", class_=re.compile(r"calendar__actual"))
        # ↑ Finds the <td> with the actual reported value (e.g., "227K").
        forecast_td = row.find("td", class_=re.compile(r"calendar__forecast"))
        # ↑ Finds the <td> with the analyst forecast value (e.g., "170K").
        previous_td = row.find("td", class_=re.compile(r"calendar__previous"))
        # ↑ Finds the <td> with the previous month's value.

        if not currency_td or not event_td:
            # ↑ If either the currency or event cell is missing, this row has no useful data.
            #   'not currency_td' → True if currency_td is None (the .find() returned nothing).
            continue
            # ↑ Skip this incomplete row.

        currency = currency_td.get_text(strip=True)
        # ↑ Extracts the plain text from the currency cell.
        #   .get_text()   → removes all HTML tags and returns the inner text.
        #   strip=True    → strips leading/trailing whitespace from the result.
        #   e.g., <td class="calendar__currency">USD</td> → "USD".

        event = event_td.get_text(strip=True)
        # ↑ Extracts the event name text. e.g., "Non-Farm Employment Change".

        if not event:
            # ↑ If the event text is empty (some rows are structural, not actual events).
            continue
            # ↑ Skip empty event rows.

        time_text = time_td.get_text(strip=True) if time_td else ""
        # ↑ Gets the time text if the time cell exists, otherwise defaults to empty string.
        #   'X if condition else Y' → ternary: use X if condition is True, Y otherwise.
        #   time_td may be None if the cell wasn't found.

        dt, last_hhmm = _parse_time(time_text, day, last_hhmm)
        # ↑ Parses the time string into a proper datetime using our helper function.
        #   Also updates last_hhmm (tuple unpacking) so the next event can inherit the time if blank.

        records.append({
            # ↑ Builds one event dictionary and adds it to our results list.
            "DateTime": dt.isoformat(),
            # ↑ The event datetime as an ISO 8601 string: "2026-02-06T08:30:00-05:00".
            #   .isoformat() → converts a datetime to the standard ISO format string.
            #   This format preserves timezone info and is universally readable.
            "Currency": currency,
            # ↑ The currency code affected by this event (e.g., "USD").
            "Impact":   _parse_impact(impact_td),
            # ↑ The impact level string, decoded from the CSS class (e.g., "High Impact Expected").
            "Event":    event,
            # ↑ The event name text.
            "Actual":   actual_td.get_text(strip=True)   if actual_td   else "",
            # ↑ The actual reported value (e.g., "227K") or empty string if not released yet.
            "Forecast": forecast_td.get_text(strip=True) if forecast_td else "",
            # ↑ The consensus forecast value (e.g., "170K") or empty string.
            "Previous": previous_td.get_text(strip=True) if previous_td else "",
            # ↑ The previous period's value or empty string.
        })

    return records
    # ↑ Returns the list of event dictionaries for this day.


# ---------------------------------------------------------------------------
# Date-range scrape
# ---------------------------------------------------------------------------

def scrape_range(
    start: date,
    end: date,
    output_csv: str | Path,
    currencies: list[str] | None = None,
    delay: float = 2.0,
) -> pd.DataFrame:
# ↑ The main scraping function — fetches ForexFactory for every day from start to end.
#   Parameters:
#     start: date                 → first date to scrape (inclusive).
#     end: date                   → last date to scrape (inclusive).
#     output_csv: str | Path      → where to save the resulting CSV (accepts string or Path).
#     currencies: list[str] | None → if provided, only keep events for these currencies.
#                                    e.g., ["USD"] keeps only US events. None = keep all.
#     delay: float = 2.0          → seconds to wait between day requests (be polite to the server).
#   -> pd.DataFrame               → returns the combined events table.
    """
    Scrape ForexFactory from start to end (inclusive) and save to CSV.

    Parameters
    ----------
    start, end    : date range (inclusive)
    output_csv    : path to write CSV
    currencies    : if given, keep only these currency codes (e.g. ["USD"])
    delay         : seconds to wait between day requests
    """

    output_csv = Path(output_csv)
    # ↑ Converts the output_csv argument to a Path object (in case it was passed as a plain string).
    #   Path("data/ff_events.csv") → a proper Path object we can use with .exists(), .parent, etc.

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    # ↑ Creates the directory containing the output file, if it doesn't exist.
    #   .parent       → the directory part of the path (e.g., "data/" from "data/ff_events.csv").
    #   .mkdir(parents=True, exist_ok=True):
    #     parents=True  → also creates any missing parent directories (like mkdir -p in shell).
    #     exist_ok=True → don't error if the directory already exists.

    # Load existing data so we can append/deduplicate
    # ↑ If we've scraped before, load the existing CSV so we can merge new data with old.
    if output_csv.exists():
        # ↑ If the output CSV already exists (a previous scrape was done).
        existing = pd.read_csv(output_csv)
        # ↑ Read the existing CSV into a DataFrame.
        logger.info(f"Loaded {len(existing)} existing rows from {output_csv}")
        # ↑ Log how many rows we already have.
    else:
        existing = pd.DataFrame()
        # ↑ If no existing file, start with an empty DataFrame.
        #   pd.DataFrame() with no arguments creates a completely empty table.

    scraper = _make_scraper()
    # ↑ Creates the cloudscraper HTTP session.

    all_records: list[dict] = []
    # ↑ Empty list to collect all event dictionaries from all days.

    day = start
    # ↑ Initialize our "current day" pointer to the start date.

    while day <= end:
        # ↑ Loop from start to end, one day at a time.
        #   Continues as long as the current day is on or before the end date.

        try:
            # ↑ 'try' block — wraps code that might throw an error.
            #   If an error occurs inside, Python jumps to the 'except' block instead of crashing.
            records = fetch_day(scraper, day)
            # ↑ Fetches and parses this day's events.
            logger.info(f"  → {len(records)} events on {day}")
            # ↑ Logs how many events were found for this day.
            all_records.extend(records)
            # ↑ .extend() adds all items from 'records' to 'all_records'.
            #   Unlike .append() which adds the list itself, .extend() adds each item individually.
            #   e.g., if records=[event1, event2], all_records becomes [..., event1, event2].

        except Exception as e:
            # ↑ 'except Exception as e' catches ANY exception that occurred in the try block.
            #   Exception is the base class for all Python errors.
            #   'as e' gives us the error object so we can read its message.
            logger.error(f"  Error on {day}: {e}")
            # ↑ Logs the error message but continues the loop (doesn't crash the whole program).
            #   This way, one bad day doesn't stop the entire scrape.

        day += timedelta(days=1)
        # ↑ Advances 'day' by one calendar day.
        #   timedelta(days=1) is a 1-day duration.
        #   += is shorthand for: day = day + timedelta(days=1).

        if day <= end:
            # ↑ Only sleep if there are more days to fetch (no need to wait after the last day).
            time.sleep(delay)
            # ↑ Pauses execution for 'delay' seconds (default 2 seconds).
            #   This is "polite scraping" — we don't hammer the server with rapid requests.
            #   time.sleep() is from the 'time' module imported at the top (not the datetime 'time').

    if not all_records:
        # ↑ If we got no events at all after scraping the entire range.
        logger.warning("No events scraped.")
        # ↑ Log a warning.
        return existing
        # ↑ Return whatever we already had (the pre-existing CSV data).

    new_df = pd.DataFrame(all_records)
    # ↑ Converts the list of event dictionaries into a DataFrame.
    #   Each dict becomes one row; dict keys become column headers.

    # Currency filter
    if currencies:
        # ↑ If a currency filter was provided (currencies is not None and not empty).
        new_df = new_df[new_df["Currency"].isin(currencies)]
        # ↑ Keeps only rows where the Currency column value is in our filter list.
        #   .isin(currencies) → returns True for rows where Currency is in the list (e.g., ["USD"]).
        #   new_df[...]       → applies the True/False mask to filter the rows.
        logger.info(f"Filtered to {currencies}: {len(new_df)} rows")
        # ↑ Logs how many rows remain after filtering.

    # Merge with existing, deduplicate on (DateTime, Currency, Event)
    # ↑ Combine old and new data, then remove any duplicate events.
    combined = pd.concat([existing, new_df], ignore_index=True)
    # ↑ Stacks the existing DataFrame on top of (or below) the new DataFrame.
    #   pd.concat([df1, df2]) → concatenates them vertically (row-wise).
    #   ignore_index=True     → resets the row numbers (index) to 0, 1, 2, ... after combining.
    #                           Otherwise the index from each table would be preserved, causing duplicates.

    combined.drop_duplicates(subset=["DateTime", "Currency", "Event"], keep="last", inplace=True)
    # ↑ Removes duplicate rows where the combination of DateTime + Currency + Event is identical.
    #   subset=[...]   → only look at these columns when deciding if two rows are duplicates.
    #   keep="last"    → when there's a duplicate, keep the LAST occurrence (the newer data wins).
    #   inplace=True   → modifies 'combined' directly instead of returning a new copy.

    combined.sort_values("DateTime", inplace=True)
    # ↑ Sorts all rows chronologically by the DateTime column.
    #   inplace=True → modifies in place.

    combined.reset_index(drop=True, inplace=True)
    # ↑ Resets the row index to 0, 1, 2, 3, ... after sorting and deduplication.
    #   drop=True   → don't keep the old index as a column (just discard it).
    #   inplace=True → modifies in place.

    combined.to_csv(output_csv, index=False)
    # ↑ Saves the final combined DataFrame to the CSV file.
    #   index=False → don't write the row numbers (0, 1, 2, ...) as a column in the CSV.

    logger.info(f"Saved {len(combined)} rows → {output_csv}")
    # ↑ Logs the total number of rows saved.

    return combined
    # ↑ Returns the combined DataFrame to the caller.


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# ↑ Command-Line Interface section. This code handles running the scraper
#   directly from the terminal with arguments like:
#   python -m src.ff_scraper --start 2026-02-06 --end 2026-02-27

def main():
# ↑ The entry point function for the CLI. When you run the script from the terminal,
#   Python calls main() (via the 'if __name__ == "__main__"' block at the bottom).
    parser = argparse.ArgumentParser(description="ForexFactory calendar scraper")
    # ↑ Creates an argument parser with a description (shown in --help output).
    #   ArgumentParser handles reading and validating command-line arguments.

    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    # ↑ Defines the --start argument.
    #   required=True → the user MUST provide --start or the program will show an error.
    #   help="..."    → the help text shown when the user runs: python -m src.ff_scraper --help

    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    # ↑ The --end argument (also required).

    parser.add_argument("--csv", default="data/ff_events.csv", help="Output CSV path")
    # ↑ The --csv argument.
    #   default="data/ff_events.csv" → if the user doesn't provide --csv, this value is used.

    parser.add_argument("--currencies", nargs="+", default=["USD"],
                        help="Currency codes to keep (default: USD)")
    # ↑ The --currencies argument.
    #   nargs="+" → accepts one or more values: --currencies USD EUR GBP → ["USD", "EUR", "GBP"].
    #   default=["USD"] → if not provided, defaults to just USD.

    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds between day requests (default: 2)")
    # ↑ The --delay argument.
    #   type=float → converts the string argument to a float number automatically.
    #   default=2.0 → default 2-second delay between requests.

    args = parser.parse_args()
    # ↑ Parses the actual arguments from the command line the user typed.
    #   Result: 'args' is an object where args.start, args.end, args.csv, etc. hold the values.

    start = date.fromisoformat(args.start)
    # ↑ Converts the start date string (e.g., "2026-02-06") to a Python date object.
    #   date.fromisoformat("2026-02-06") → date(2026, 2, 6).
    #   ISO format = YYYY-MM-DD.

    end = date.fromisoformat(args.end)
    # ↑ Same conversion for the end date.

    logger.info(f"Scraping ForexFactory {start} → {end}, currencies={args.currencies}")
    # ↑ Logs the scraping parameters before starting.

    df = scrape_range(start, end, args.csv, currencies=args.currencies, delay=args.delay)
    # ↑ Calls the main scraping function with all the parsed arguments.

    logger.info(f"Done. {len(df)} total rows in {args.csv}")
    # ↑ Logs the final result.


if __name__ == "__main__":
    # ↑ This is a Python idiom — "run this only if this file is executed directly".
    #   When you run: python -m src.ff_scraper
    #     __name__ equals "__main__" → main() is called.
    #   When another file imports this module (e.g., from src import ff_scraper):
    #     __name__ equals "src.ff_scraper" → main() is NOT called automatically.
    #   This lets the file work both as a standalone script AND as an importable module.
    main()
    # ↑ Calls the main() function to start the CLI program.
