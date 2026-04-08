import os
import re
import sys
import requests

def fetch_images(url, save_dir, limit=10):
    print(f"Fetching images from {url}...")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        return

    html = resp.text
    
    # Find image URLs
    # Example: https://assets.hospitable.com/property_images/2059574/poKFskTrD4xBMpBOA1Q9coik12LW2lUgTC3XqmMD.jpg
    urls = re.findall(r'https://assets\.hospitable\.com/property_images/[^"]+\.jpg', html)
    
    # Also check for smartbnbuploads or digitaloceanspaces if any
    urls.extend(re.findall(r'https://smartbnbuploads\.nyc3\.digitaloceanspaces\.com/property_images/[^"]+\.jpg', html))
    
    # Remove duplicates while preserving order
    urls = list(dict.fromkeys(urls))
    
    print(f"Found {len(urls)} unique image URLs.")
    
    urls = urls[:limit]
    print(f"Downloading first {len(urls)} images...")
    
    os.makedirs(save_dir, exist_ok=True)
    
    downloaded = 0
    for i, img_url in enumerate(urls):
        try:
            print(f"Downloading {img_url}...")
            img_resp = requests.get(img_url, timeout=10)
            img_resp.raise_for_status()
            
            filename = f"image_{i+1}.jpg"
            filepath = os.path.join(save_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(img_resp.content)
            
            print(f"Saved to {filepath}")
            downloaded += 1
        except Exception as e:
            print(f"Failed to download {img_url}: {e}")
            
    print(f"Successfully downloaded {downloaded} images.")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python fetch_hospitable_images.py <url> <save_dir>")
        sys.exit(1)
        
    url = sys.argv[1]
    save_dir = sys.argv[2]
    
    fetch_images(url, save_dir)
