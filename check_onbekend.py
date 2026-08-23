import os
import requests
import json
import csv
from io import StringIO
from datetime import datetime

# URL of the JSON endpoint (paginated API)
API_BASE_URL = "https://hulpdienstvoertuigenbenelux.nl/api/vehicles"
API_KEY = os.getenv("API_KEY")  # Loaded from GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Loaded from GitHub Secrets


def fetch_all_pages():
    """Fetch all pages from the paginated API and return combined data."""
    print("Fetching paginated JSON data...")
    
    # Adding a realistic User-Agent prevents many modern servers from blocking requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Add API key to headers
    if API_KEY:
        headers["x-api-key"] = API_KEY

    all_vehicles = []
    page = 1
    
    while True:
        try:
            # Fetch page with pagination parameter
            url = f"{API_BASE_URL}?page={page}"
            print(f"Fetching page {page}...")
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
        except requests.exceptions.JSONDecodeError:
            print(f"Error: Response from page {page} was not valid JSON.")
            print(f"First 200 characters of response content:\n{response.text[:200]}")
            break

        # Extract vehicles from response
        # Adjust based on actual API response structure (e.g., data.get("data"), data.get("vehicles"), etc.)
        vehicles = data.get("data", []) or data.get("vehicles", []) or data
        
        if not vehicles:
            print(f"No more vehicles on page {page}. Stopping pagination.")
            break

        all_vehicles.extend(vehicles)
        print(f"Page {page}: fetched {len(vehicles)} vehicles (total: {len(all_vehicles)})")
        page += 1

    return all_vehicles


def fetch_and_check():
    print("Starting ONBEKEND detection...\n")
    
    # Fetch all pages
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
            writer.writerow(entry["row_data"].values())
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
