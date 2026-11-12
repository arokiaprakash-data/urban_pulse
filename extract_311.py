"""
Urban Pulse - Part 1: NYC 311 data extraction (Day 1-2)

Pulls the most recent N service requests from the NYC Open Data API
(dataset erm2-nwe9) page by page, with timeouts and retries, and saves:
  data/raw/nyc311_raw.csv        - the raw extract (never edit this file)
  data/raw/extraction_log.json   - date, parameters, row count, date window

Usage:
  python extract_311.py                 # 100,000 rows (default)
  python extract_311.py --rows 1000     # quick Day 1 test
  python extract_311.py --end-date 2026-10-01

Optional: set NYC_APP_TOKEN as an environment variable (free token from
data.cityofnewyork.us) for fewer throttling errors. Works without it.
"""

import argparse
import csv
import json
import os
import time
from datetime import datetime, date
from pathlib import Path

import requests

DATA_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
META_URL = "https://data.cityofnewyork.us/api/views/erm2-nwe9.json"

# ~25 fields chosen for the project. They are checked against the live
# schema before downloading; any that no longer exist are skipped.
FIELDS = [
    "unique_key", "created_date", "closed_date", "due_date",
    "resolution_action_updated_date", "agency", "agency_name",
    "complaint_type", "descriptor", "location_type", "incident_zip",
    "incident_address", "street_name", "city", "borough",
    "community_board", "council_district", "police_precinct",
    "address_type", "status", "resolution_description",
    "open_data_channel_type", "latitude", "longitude", "park_borough",
]

MAX_RETRIES = 5
TIMEOUT_SECONDS = 60


def get_with_retry(session, url, params=None):
    """GET a URL, retrying on timeouts, throttling (429) and server errors (5xx)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                print(f"  HTTP {resp.status_code}, retry {attempt}/{MAX_RETRIES}")
            else:
                # 4xx other than 429 = bad query; retrying will not help
                resp.raise_for_status()
        except (requests.Timeout, requests.ConnectionError) as err:
            print(f"  {type(err).__name__}, retry {attempt}/{MAX_RETRIES}")
        time.sleep(2 ** attempt)  # 2, 4, 8, 16, 32 seconds
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url}")


def check_fields(session):
    """Keep only the fields that exist in the live dataset schema."""
    meta = get_with_retry(session, META_URL)
    live = {col["fieldName"] for col in meta["columns"]}
    missing = [f for f in FIELDS if f not in live]
    if missing:
        print(f"WARNING: not in live schema, skipped: {missing}")
    return [f for f in FIELDS if f in live]


def extract(rows, page_size, end_date, out_dir):
    session = requests.Session()
    token = os.getenv("NYC_APP_TOKEN")
    if token:
        session.headers["X-App-Token"] = token

    fields = check_fields(session)
    print(f"Using {len(fields)} fields")

    # Fixed cut-off so new requests arriving during the download do not
    # shift the pages (which would cause duplicates).
    where = f"created_date < '{end_date}T00:00:00'"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "nyc311_raw.csv"

    seen = set()
    duplicates = 0
    offset = 0
    started = datetime.now()

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()

        while len(seen) < rows:
            limit = min(page_size, rows - len(seen))
            params = {
                "$select": ",".join(fields),
                "$where": where,
                "$order": "created_date DESC, unique_key",
                "$limit": limit,
                "$offset": offset,
            }
            page = get_with_retry(session, DATA_URL, params)
            if not page:
                print("No more data available from the API.")
                break

            for rec in page:
                key = rec.get("unique_key")
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                writer.writerow(rec)

            offset += len(page)
            print(f"  fetched {offset:,} | unique saved {len(seen):,}")
            time.sleep(0.5)  # be polite to the API

    # Realized date window, read back from the saved file
    with open(csv_path, encoding="utf-8") as f:
        dates = [r["created_date"] for r in csv.DictReader(f) if r["created_date"]]

    log = {
        "extracted_at": started.isoformat(timespec="seconds"),
        "source": DATA_URL,
        "row_target": rows,
        "rows_saved": len(seen),
        "duplicates_skipped": duplicates,
        "page_size": page_size,
        "filter": where,
        "order": "created_date DESC",
        "fields": fields,
        "created_date_min": min(dates) if dates else None,
        "created_date_max": max(dates) if dates else None,
        "duration_seconds": round((datetime.now() - started).total_seconds(), 1),
    }
    with open(out_dir / "extraction_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)

    print(f"\nSaved {len(seen):,} rows -> {csv_path}")
    print(f"Date window: {log['created_date_min']} to {log['created_date_max']}")
    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract NYC 311 records")
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--page-size", type=int, default=5_000)
    parser.add_argument("--end-date", default=date.today().isoformat(),
                        help="only records created before this date (YYYY-MM-DD)")
    parser.add_argument("--out-dir", default="data/raw")
    args = parser.parse_args()

    extract(args.rows, args.page_size, args.end_date, Path(args.out_dir))
