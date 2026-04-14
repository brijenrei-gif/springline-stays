import os
import json
import requests
from datetime import datetime, timedelta

def load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    env[key] = value.strip()
    return env

def main():
    env = load_env()
    token = env.get('HOSPITABLE_TOKEN')
    if not token:
        print("HOSPITABLE_TOKEN not found in .env")
        return

    base_url = "https://public.api.hospitable.com/v2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    print("Fetching properties from Hospitable...")
    resp = requests.get(f"{base_url}/properties", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch properties: {resp.status_code}")
        return

    properties = resp.json().get('data', [])
    print(f"Found {len(properties)} properties.")

    availability_data = {}

    # Calculate date range for next 12 months
    start_date = datetime.now().strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')

    for prop in properties:
        prop_id = prop['id']
        name = prop['name']
        print(f"Fetching calendar for {name} ({prop_id})...")

        cal_url = f"{base_url}/properties/{prop_id}/calendar?start_date={start_date}&end_date={end_date}"
        cal_resp = requests.get(cal_url, headers=headers)

        if cal_resp.status_code != 200:
            print(f"Failed to fetch calendar for {name}")
            continue

        days = cal_resp.json().get('data', {}).get('days', [])
        blocked_dates = []
        prices = {}

        for day in days:
            date_str = day['date']
            available = day.get('status', {}).get('available', True)
            if not available:
                blocked_dates.append(date_str)
            
            # Get nightly price
            price_amount = day.get('price', {}).get('amount')
            if price_amount:
                prices[date_str] = price_amount / 100.0 # amount is in cents

        availability_data[prop_id] = {
            "name": name,
            "public_name": prop.get('public_name', ''),
            "blocked_dates": blocked_dates,
            "prices": prices
        }

    output_path = os.path.join(os.path.dirname(__file__), 'static', 'availability.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(availability_data, f, indent=2)

    print(f"Saved availability data to {output_path}")

if __name__ == "__main__":
    main()
