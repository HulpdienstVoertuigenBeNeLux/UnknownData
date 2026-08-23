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


def fetch_all_pages():
    """Fetch data from the sheet endpoint and return combined data.

    The original script supported a paginated API. The fetch-sheet endpoint
    typically returns a single JSON payload (not paginated). This function
    keeps a fallback pagination loop but will work fine if the endpoint
    ignores the `page` parameter or returns a single list/dict.
    """
    print("Fetching JSON data from fetch-sheet endpoint...")
    
    # Adding a realistic User-Agent prevents many modern servers from blocking requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://hulpdienstvoertuigenbenelux.nl/",
    }

    # Add sheet API key header if available
    if SHEET_API_KEY:
        headers["X-API-Key"] = SHEET_API_KEY

    all_vehicles = []
    page = 1

    while True:
        try:
            # Many sheet endpoints are not paginated; include `page` param as a no-op if ignored.
            url = f"{API_BASE_URL}&page={page}" if "?" in API_BASE_URL else f"{API_BASE_URL}?page={page}"
            print(f"Fetching page {page}... URL: {url}")
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch page {page}: {e}")
            break

        # Check if response body has content
        if not response.text.strip():
            print(f"Received an empty response from page {page}.")
            break

        # Safely parse JSON
        try:
            data = response.json()
        except ValueError:
            # requests raises simple ValueError for JSON decode errors in some versions
            print(f"Error: Response from page {page} was not valid JSON.")
            print(f"First 200 characters of response content:\n{response.text[:200]}")
            break

        # If the endpoint returns a dict with a key like `data` or `vehicles`, extract it
        vehicles = data.get("data", []) or data.get("vehicles", []) or data
        
        # If the returned payload is a dict representing metadata + rows, try to extract rows
        if isinstance(vehicles, dict) and "rows" in vehicles:
            vehicles = vehicles.get("rows", [])

        if not vehicles:
            print(f"No more vehicles on page {page}. Stopping pagination.")
            break

        # If the endpoint returned a single dict (non-list), wrap it
        if isinstance(vehicles, dict):
            all_vehicles.append(vehicles)
        else:
            all_vehicles.extend(vehicles)

        print(f"Page {page}: fetched {len(vehicles) if hasattr(vehicles, '__len__') else 1} vehicles (total: {len(all_vehicles)})")

        # If the endpoint is not paginated, stop after first successful fetch
        if page == 1 and ("fetch-sheet" in API_BASE_URL or not isinstance(data, dict) or not data.get("next_page")):
            break

        page += 1

    return all_vehicles


def fetch_and_check():
    print("Starting ONBEKEND detection...\n")
    
    # Fetch all pages / sheet
    all_vehicles = fetch_all_pages()
    
    if not all_vehicles:
        print("No vehicles data found!")
        return

    print(f"\n✓ Total vehicles fetched: {len(all_vehicles)}\n")

    onbekend_entries = []

    # Loop through all vehicles and check for 'ONBEKEND'
    for index, vehicle in enumerate(all_vehicles):
        # Handle both dict and list formats
        if isinstance(vehicle, dict):
            row_str_repr = [str(item) for item in vehicle.values()]
        else:
            row_str_repr = [str(item) for item in vehicle]
        
        if any("ONBEKEND" in item.upper() for item in row_str_repr):
            onbekend_entries.append({"row_number": index + 1, "row_data": vehicle})

    print(f"Found {len(onbekend_entries)} rows containing 'ONBEKEND'.")

    # Output results locally or send to Discord
    if onbekend_entries:
        send_discord_alert(onbekend_entries)
    else:
        print("No 'ONBEKEND' values found!")


def generate_csv_file(entries):
    """Generate a CSV file in memory and return as bytes."""
    output = StringIO()
    writer = csv.writer(output)
    
    # If entries are dicts, use keys as headers
    if entries and isinstance(entries[0]["row_data"], dict):
        first_entry = entries[0]["row_data"]
        headers = list(first_entry.keys())
        writer.writerow(headers)
        
        for entry in entries:
            # preserve order by using the same header keys
            writer.writerow([entry["row_data"].get(h, "") for h in headers])
    else:
        # If entries are lists, just write them
        for entry in entries:
            writer.writerow(entry["row_data"])
    
    return output.getvalue().encode('utf-8')


def generate_json_file(entries):
    """Generate a JSON file in memory and return as bytes."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_entries": len(entries),
        "entries": entries
    }
    return json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')


def send_discord_alert(entries):
    if not DISCORD_WEBHOOK_URL:
        print(
            "Discord Webhook URL not set. Printing locally:"
            f" {len(entries)} entries found."
        )
        return

    # Generate both CSV and JSON files
    csv_data = generate_csv_file(entries)
    json_data = generate_json_file(entries)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"onbekend_entries_{timestamp}.csv"
    json_filename = f"onbekend_entries_{timestamp}.json"

    # Send summary message
    summary_payload = {
        "content": f"⚠️ **'ONBEKEND' values detected in Hulpdienstvoertuigen Dataset!**\n"
                   f"📊 Total entries found: **{len(entries)}**\n"
                   f"📥 Files are attached below for download.",
        "embeds": [
            {
                "title": "Detection Summary",
                "color": 15158332,
                "fields": [
                    {
                        "name": "Total Entries",
                        "value": str(len(entries)),
                        "inline": True
                    },
                    {
                        "name": "Timestamp",
                        "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "inline": True
                    }
                ]
            }
        ]
    }

    requests.post(DISCORD_WEBHOOK_URL, json=summary_payload)

    # Send CSV file
    files_csv = {
        'file': (csv_filename, csv_data, 'text/csv')
    }
    requests.post(DISCORD_WEBHOOK_URL, files=files_csv)

    # Send JSON file
    files_json = {
        'file': (json_filename, json_data, 'application/json')
    }
    requests.post(DISCORD_WEBHOOK_URL, files=files_json)

    print(f"Discord alert sent with attachments: {csv_filename}, {json_filename}")


if __name__ == "__main__":
    fetch_and_check()
