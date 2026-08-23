import os
import requests

# URL of the JSON endpoint
JSON_URL = "https://hulpdienstvoertuigenbenelux.nl/fetch-sheet?region=NL"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Loaded from GitHub Secrets


def fetch_and_check():
    print("Fetching JSON data...")
    
    # Adding a realistic User-Agent prevents many modern servers from blocking requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://hulpdienstvoertuigenbenelux.nl/",
    }

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


def send_discord_alert(entries, headers):
    if not DISCORD_WEBHOOK_URL:
        print(
            "Discord Webhook URL not set. Printing locally:"
            f" {len(entries)} entries found."
        )
        return

    # Discord has a 2000 character limit per message, so we batch or summarize
    chunk_size = 5
    for i in range(0, len(entries), chunk_size):
        chunk = entries[i : i + chunk_size]
        description = ""

        for entry in chunk:
            row_num = entry["row_number"]
            row_data = entry["row_data"]
            description += f"**Row {row_num}**\n```json\n{row_data}\n```\n\n"

        payload = {
            "content": (
                "⚠️ **'ONBEKEND' values detected in Hulpdienstvoertuigen Dataset!**"
                f" (Batch {i // chunk_size + 1})"
            ),
            "embeds": [{"description": description[:4096], "color": 15158332}],
        }

        requests.post(DISCORD_WEBHOOK_URL, json=payload)


if __name__ == "__main__":
    fetch_and_check()
