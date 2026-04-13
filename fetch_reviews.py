import os
import yaml
import requests

def load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    env[key] = value
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

    # Fetch properties from Hospitable to get IDs
    print("Fetching properties from Hospitable...")
    resp = requests.get(f"{base_url}/properties", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch properties: {resp.status_code}")
        print(resp.text)
        return
    
    hospitable_props = resp.json().get('data', [])
    print(f"Found {len(hospitable_props)} properties in Hospitable.")

    all_reviews = []

    for hp in hospitable_props:
        hp_id = hp['id']
        hp_name = hp['name']
        hp_public_name = hp.get('public_name', '')
        
        print(f"Fetching reviews for {hp_name} ({hp_id})...")
        reviews_url = f"{base_url}/properties/{hp_id}/reviews"
        rev_resp = requests.get(reviews_url, headers=headers)
        
        if rev_resp.status_code != 200:
            print(f"Failed to fetch reviews for {hp_name}: {rev_resp.status_code}")
            continue
            
        reviews_data = rev_resp.json().get('data', [])
        print(f"Found {len(reviews_data)} reviews.")
        
        for rev in reviews_data:
            rating = rev.get('public', {}).get('rating')
            if rating == 5:
                text = rev.get('public', {}).get('review')
                if not text or not text.strip():
                    continue
                    
                author = "Verified Guest"
                
                all_reviews.append({
                    'property_name': hp_name,
                    'property_public_name': hp_public_name,
                    'author': author,
                    'rating': rating,
                    'text': text,
                    'date': rev.get('reviewed_at')
                })

    # Save to config/reviews.yaml
    output_dir = os.path.join(os.path.dirname(__file__), 'config')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'reviews.yaml')
    with open(output_path, 'w') as f:
        yaml.dump(all_reviews, f, sort_keys=False)
    
    print(f"Saved {len(all_reviews)} 5-star reviews to {output_path}")

if __name__ == '__main__':
    main()
