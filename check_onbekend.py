import os
import requests
import json
import csv
from io import StringIO
from datetime import datetime

# URL of the JSON endpoint
JSON_URL = "https://hulpdienstvoertuigenbenelux.nl/fetch-sheet?region=NL"
API_KEY = os.getenv("API_KEY")  # Loaded from GitHub Secrets
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Loaded from GitHub Secrets


def fetch_and_check():
    print("Fetching JSON data...")
    
    # Adding a realistic User-Agent prevents many modern servers from blocking requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Add API key to headers
    if API_KEY:
        headers["x-api-key"] = API_KEY

    try:
        response = requests.get(JSON_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch URL: {e}")
        return

    # Check if response body has content
    if not response.text.strip():
        print("Error: Received an empty response from server.")
        return

    # Safely parse JSON
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        print("Error: Response was not valid JSON.")
        print(f"First 200 characters of response content:\n{response.text[:200]}")
        return

    values = data.get("values", [])

    # Headers are usually around row index 2 based on your sample
    headers_row = values[2] if len(values) > 2 else []
    onbekend_entries = []

    # Loop through rows (skip the first few metadata rows if needed, or scan all)
    for index, row in enumerate(values):
        # Check if 'ONBEKEND' exists anywhere in the row items
        row_str_repr = [str(item) for item in row]
        if any("ONBEKEND" in item.upper() for item in row_str_repr):
            onbekend_entries.append({"row_number": index + 1, "row_data": row})

    print(f"Found {len(onbekend_entries)} rows containing 'ONBEKEND'.")

    # Output results locally or send to Discord
    if onbekend_entries:
        send_discord_alert(onbekend_entries, headers_row)
    else:
        print("No 'ONBEKEND' values found!")


def generate_csv_file(entries, headers):
    """Generate a CSV file in memory and return as bytes."""
    output = StringIO()
    
    # Write headers if available
    if headers:
        writer = csv.writer(output)
        writer.writerow(headers)
    
    # Write entries
    writer = csv.writer(output)
    for entry in entries:
        writer.writerow(entry["row_data"])
    
    return output.getvalue().encode('utf-8')


def generate_json_file(entries, headers):
    """Generate a JSON file in memory and return as bytes."""
    data = {
        "timestamp": datetime.now().isoformat(),
        "total_entries": len(entries),
        "headers": headers,
        "entries": entries
    }
    return json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')


def send_discord_alert(entries, headers):
    if not DISCORD_WEBHOOK_URL:
        print(
            "Discord Webhook URL not set. Printing locally:"
            f" {len(entries)} entries found."
        )
        return

    # Generate both CSV and JSON files
    csv_data = generate_csv_file(entries, headers)
    json_data = generate_json_file(entries, headers)
    
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
