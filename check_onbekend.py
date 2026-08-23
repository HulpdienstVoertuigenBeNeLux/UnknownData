import os
import requests
import json
import csv
from io import StringIO
from datetime import datetime

# URL of the JSON endpoint (not paginated / sheet endpoint)
API_BASE_URL = "https://hulpdienstvoertuigenbenelux.nl/fetch-sheet?region=NL"
SHEET_API_KEY = os.getenv("SHEET_API_KEY")  # Loaded from environment / GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Loaded from GitHub Secrets


def fetch_sheet():
    """Fetch data from the non-paginated sheet endpoint and return list of rows.

    This endpoint is expected to return a single JSON payload (list or dict).
    """
    print("Fetching JSON data from fetch-sheet endpoint (single request)...")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://hulpdienstvoertuigenbenelux.nl/",
    }

    if SHEET_API_KEY:
        headers["X-API-Key"] = SHEET_API_KEY

    try:
        response = requests.get(API_BASE_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch sheet: {e}")
        return []

    if not response.text.strip():
        print("Received an empty response from fetch-sheet.")
        return []

    try:
        data = response.json()
    except ValueError:
        print("Error: Response was not valid JSON.")
        print(response.text[:200])
        return []

    # Try common shapes (list, dict with `data`/`vehicles`, dict with `rows`)
    rows = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("data") or data.get("vehicles") or data.get("rows") or data
        # If `rows` is still a dict with `rows` key, extract
        if isinstance(rows, dict) and "rows" in rows:
            rows = rows.get("rows", [])

        # If it's a dict representing a single vehicle, wrap it
        if isinstance(rows, dict):
            rows = [rows]
    else:
        # unknown shape, return empty
        print("Unexpected JSON shape returned from sheet endpoint.")
        return []

    print(f"Fetched {len(rows)} rows from sheet.")
    return rows


def is_onbekend_in_value(value):
    """Return True if the given value (any type) contains the string 'ONBEKEND' (case-insensitive)."""
    if value is None:
        return False
    if isinstance(value, (int, float, bool)):
        value = str(value)
    if isinstance(value, str):
        return "ONBEKEND" in value.upper()
    # For other types (lists/dicts), check their string representation but prefer not to scan large nested structures
    try:
        return "ONBEKEND" in json.dumps(value, ensure_ascii=False).upper()
    except Exception:
        return False


def flatten_vehicle_row(vehicle):
    """Return a flat dict of top-level primitive fields of the vehicle.

    Skip nested lists/dicts (like `posts`) to avoid exploding the CSV. Nested structures are omitted.
    """
    flat = {}
    if isinstance(vehicle, dict):
        for k, v in vehicle.items():
            # Keep simple scalar values only
            if v is None:
                flat[k] = ""
            elif isinstance(v, (str, int, float, bool)):
                flat[k] = v
            else:
                # skip lists/dicts/complex objects (e.g., posts)
                continue
    else:
        # If the row is a list/tuple, map to col0, col1, ...
        for i, v in enumerate(vehicle):
            flat[f"col{i}"] = v if v is not None else ""
    return flat


def fetch_and_check():
    print("Starting ONBEKEND detection...\n")

    all_rows = fetch_sheet()
    if not all_rows:
        print("No vehicles data found!")
        return

    print(f"\n✓ Total rows fetched: {len(all_rows)}\n")

    matches = []

    # Look for 'ONBEKEND' anywhere in the row. If a row contains it, include the flattened vehicle as one CSV row.
    for idx, row in enumerate(all_rows):
        found = False
        if isinstance(row, dict):
            for v in row.values():
                if is_onbekend_in_value(v):
                    found = True
                    break
        else:
            # list/tuple or other
            for v in row:
                if is_onbekend_in_value(v):
                    found = True
                    break

        if found:
            flat = flatten_vehicle_row(row)
            # attach original index for traceability if desired
            flat["_source_row_index"] = idx + 1
            matches.append(flat)

    print(f"Found {len(matches)} rows containing 'ONBEKEND'.")

    if matches:
        send_discord_alert(matches)
    else:
        print("No 'ONBEKEND' values found!")


def generate_csv_file_dicts(dict_rows):
    """Generate CSV bytes from a list of flat dict rows. Use union of keys for headers, preserving insertion order."""
    if not dict_rows:
        return b""

    # Collect headers in insertion order across rows
    headers = []
    seen = set()
    for row in dict_rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    for row in dict_rows:
        writer.writerow([row.get(h, "") for h in headers])

    return output.getvalue().encode("utf-8")


def send_discord_alert(dict_rows):
    # Only one CSV file is sent, containing all matching rows (flattened). No JSON file.
    csv_data = generate_csv_file_dicts(dict_rows)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"onbekend_entries_{timestamp}.csv"

    if not DISCORD_WEBHOOK_URL:
        # Save locally and print path
        with open(csv_filename, "wb") as f:
            f.write(csv_data)
        print(f"Discord Webhook URL not set. Wrote CSV locally: {csv_filename}")
        return

    # Send summary message first
    summary_payload = {
        "content": f"⚠️ **'ONBEKEND' values detected in Hulpdienstvoertuigen Dataset!**\n📊 Total entries found: **{len(dict_rows)}**",
    }

    try:
        requests.post(DISCORD_WEBHOOK_URL, json=summary_payload, timeout=10)
    except Exception as e:
        print(f"Failed to post summary to Discord: {e}")

    # Send CSV file
    files_csv = {
        'file': (csv_filename, csv_data, 'text/csv')
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, files=files_csv, timeout=20)
        print(f"Discord alert sent with attachment: {csv_filename}")
    except Exception as e:
        print(f"Failed to send CSV to Discord: {e}")


if __name__ == "__main__":
    fetch_and_check()
