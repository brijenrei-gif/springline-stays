#!/usr/bin/env python3
"""
Springline Stays — SEO Blog Post Generator

Generates SEO-optimized blog posts using Gemini, fetches relevant images
from Unsplash, and includes property photos with booking CTAs.

Usage:
    python seo_agent.py                    # Generate 1 post (random market)
    python seo_agent.py --market colorado-springs  # Generate for specific market
    python seo_agent.py --count 3          # Generate 3 posts (rotating markets)
"""

import os
import sys
import json
import random
import argparse
import requests
import yaml
import time
from datetime import date, datetime
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("  ⚠  dotenv module not found, relying on system environment variables")

# ─── Paths ───
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / 'config' / 'properties.yaml'
CONTENT_PLAN_PATH = BASE_DIR / 'config' / 'content_plan.yaml'
CONTENT_DIR = BASE_DIR / 'content'
STATIC_DIR = BASE_DIR / 'static'

# ─── API Keys ───
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
UNSPLASH_ACCESS_KEY = os.getenv('UNSPLASH_ACCESS_KEY')


def load_config():
    """Load properties configuration."""
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def load_content_plan():
    """Load content plan."""
    if not CONTENT_PLAN_PATH.exists():
        return {'markets': {}}
    with open(CONTENT_PLAN_PATH, 'r') as f:
        return yaml.safe_load(f) or {'markets': {}}


def save_content_plan(plan):
    """Save content plan."""
    with open(CONTENT_PLAN_PATH, 'w') as f:
        yaml.safe_dump(plan, f, default_flow_style=False)


def get_market_properties(config, market_id):
    """Get active properties for a specific market."""
    return [
        p for p in config['properties']
        if p['market'] == market_id and p.get('active', True)
    ]


def get_market_config(config, market_id):
    """Get market configuration."""
    for m in config['markets']:
        if m['id'] == market_id:
            return m
    return None


def fetch_unsplash_image(query, save_dir):
    """Fetch a relevant image from Unsplash and save it locally.
    
    Returns the relative path to the saved image, or empty string on failure.
    """
    if not UNSPLASH_ACCESS_KEY:
        print("  ⚠  No Unsplash API key, skipping image fetch")
        return ""

    try:
        resp = requests.get(
            'https://api.unsplash.com/search/photos',
            params={
                'query': query,
                'per_page': 5,
                'orientation': 'landscape',
            },
            headers={'Authorization': f'Client-ID {UNSPLASH_ACCESS_KEY}'},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get('results', [])

        if not results:
            print(f"  ⚠  No Unsplash results for '{query}'")
            return ""

        # Pick a random image from top 5
        photo = random.choice(results)
        image_url = photo['urls']['regular']  # 1080px wide
        photographer = photo['user']['name']

        # Download image
        img_resp = requests.get(image_url, timeout=30)
        img_resp.raise_for_status()

        # Save to static/images/blog/
        os.makedirs(save_dir, exist_ok=True)
        slug = query.lower().replace(' ', '-').replace(',', '').replace(':', '').replace('?', '')
        slug = slug.replace('(', '').replace(')', '').replace("'", '').replace('"', '')[:50]
        slug = slug.strip('-')
        filename = f"{slug}-{random.randint(1000, 9999)}.jpg"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'wb') as f:
            f.write(img_resp.content)

        print(f"  📸 Downloaded: {filename} (Photo by {photographer})")

        # Return path relative to public/
        rel_path = os.path.relpath(filepath, BASE_DIR)
        return f"/{rel_path}"

    except Exception as e:
        print(f"  ⚠  Unsplash error: {e}")
        return ""


def pick_property_images(properties, count=2):
    """Pick random property images to include in the blog post.
    
    Returns a list of dicts with image_path, property_name, and booking_url.
    Falls back to Unsplash if no local images exist for a property.
    """
    property_images = []
    # Unsplash queries to use when no local photos exist
    fallback_queries = [
        "modern vacation rental living room",
        "cozy bedroom vacation home",
        "vacation rental patio outdoor",
        "luxury vacation home kitchen",
        "vacation rental pool backyard",
    ]

    for prop in random.sample(properties, min(count, len(properties))):
        image_dir = BASE_DIR / prop.get('image_dir', '')
        img_path = None

        # Try local images first
        if image_dir.exists():
            images = list(image_dir.glob('*.jpg')) + list(image_dir.glob('*.png'))
            if images:
                img = random.choice(images)
                img_path = f"/{os.path.relpath(img, BASE_DIR)}"

        # Fallback: use Unsplash URL directly (no download needed for property cards)
        if not img_path:
            query = random.choice(fallback_queries)
            print(f"  📷 No local images for '{prop['headline']}', using Unsplash: '{query}'")
            blog_images_dir = STATIC_DIR / 'images' / 'blog' / prop.get('market', 'general')
            img_path = fetch_unsplash_image(query, str(blog_images_dir))

        if img_path:
            property_images.append({
                'image_path': img_path,
                'property_name': prop['headline'],
                'booking_url': prop['booking_url'],
            })
        else:
            # Last resort: use a static Unsplash URL directly
            property_images.append({
                'image_path': 'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=800&q=80',
                'property_name': prop['headline'],
                'booking_url': prop['booking_url'],
            })

    return property_images


def generate_blog_post(config, market_id, planned_post=None):
    """Generate a blog post for a given market using Gemini."""
    from google import genai

    market = get_market_config(config, market_id)
    properties = get_market_properties(config, market_id)

    if not market:
        print(f"❌ Market '{market_id}' not found in config")
        return None

    print(f"\n🖊  Generating post for {market['name']}, {market['state']}...")

    # Pick a topic focus
    attractions = market.get('nearby_attractions', [])
    
    # Build property context for the prompt
    property_context_list = []
    for p in properties:
        prop_str = f"  - {p['headline']} ({p['guests']} guests, {p['bedrooms']} beds) — {p['booking_url']}"
        image_dir = BASE_DIR / p.get('image_dir', '')
        if image_dir.exists():
            images = list(image_dir.glob('*.jpg')) + list(image_dir.glob('*.png'))
            if images:
                prop_str += f"\n    Images available:"
                for img in sorted(images)[:3]:  # Sort for determinism, limit to 3
                    img_path = f"/{os.path.relpath(img, BASE_DIR)}"
                    prop_str += f"\n      - {img_path}"
        property_context_list.append(prop_str)
    property_context = "\n".join(property_context_list)

    today = date.today().isoformat()

    if planned_post:
        topic_instruction = f"Write about the specific topic: '{planned_post['title']}'."
        keywords_list = planned_post.get('keywords', [])
    else:
        topic_instruction = f"Choose a compelling topic about visiting {market['name']} — things to do, seasonal guides, local dining, hidden gems, best neighborhoods, etc."
        keywords_list = [
            f"things to do in {market['name']}",
            f"{market['name']} vacation rental",
            f"where to stay in {market['name']}",
            f"{market['name']} travel guide",
            f"book direct {market['name']}"
        ]
        # Add property-specific keywords to capture direct booking intent
        for p in properties:
            keywords_list.append(f"{p['name']} Springline Stays")
            keywords_list.append(f"{p['headline']} Springline Stays")

    keywords_str = "\n".join([f"- {k}" for k in keywords_list])

    prompt = f"""You are an expert SEO content writer specializing in short-term vacation rentals.

Write a long-form, SEO-optimized blog post (2,000-3,000 words) for the website SpringlineStays.com.

**Market**: {market['name']}, {market['state']}
**Nearby attractions**: {', '.join(attractions)}
**Our properties in this market**:
{property_context}

**Requirements**:
1. {topic_instruction}
2. Write in an authoritative, friendly tone — like a well-traveled local sharing insider tips.
3. Naturally weave in 1-2 mentions of our properties with their booking links. Don't be salesy — make it feel like a helpful suggestion. Example: "For groups of up to 11, the [Epic Family Home](booking_url) puts you minutes from Garden of the Gods with a private hot tub for après-hike relaxation."
4. **Images**: When mentioning our properties in the body, embed one of the available images listed for that property using markdown image syntax: `![Alt text](image_path)`. Prefer these local property images over Unsplash for property photos. **DO NOT** use these property images as the `hero_image` in the frontmatter. The `hero_image` should be left empty or set to a relevant search term so `build.py` can fetch a topic-relevant image from Unsplash.
5. Include a Table of Contents with anchor links.
6. Include a FAQ section (3-5 questions) at the bottom targeting Google featured snippets.
7. End with a soft CTA encouraging readers to book directly with Springline Stays.
8. Use H2 and H3 headings liberally for SEO.
9. Include specific details — addresses, drive times, tips, seasonal info.

**Output format**: Start with YAML frontmatter enclosed by `---`:

```
---
title: "Your SEO-Optimized Title (Include Location)"
date: {today}
description: "A 150-160 character meta description with primary keyword."
hero_image: ""
tags:
  - tag-one
  - tag-two
  - tag-three
market: {market_id}
---
```

Then write the full blog post in Markdown format. Do NOT include the title again as an H1 — the template handles that.

**SEO keywords to target** (use naturally):
{keywords_str}
"""

    # Call Gemini
    client = genai.Client(api_key=GEMINI_API_KEY)

    max_retries = 3
    base_delay = 5
    content = None
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
            )
            content = response.text
            break
        except Exception as e:
            print(f"❌ Gemini error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                return None

    # Clean up: remove markdown code fences if present
    content = content.strip()
    if content.startswith('```'):
        # Remove opening fence
        first_newline = content.index('\n')
        content = content[first_newline + 1:]
    if content.endswith('```'):
        content = content[:-3].strip()

    # Fetch hero image from Unsplash
    blog_images_dir = STATIC_DIR / 'images' / 'blog' / market_id
    hero_query = f"{market['name']} {market['state']} scenic"
    hero_image = fetch_unsplash_image(hero_query, str(blog_images_dir))

    # Inject hero image into frontmatter if we got one
    if hero_image and 'hero_image: ""' in content:
        content = content.replace('hero_image: ""', f'hero_image: "{hero_image}"')

    # Fetch 1-2 attraction images to insert into the post
    if attractions:
        for attraction in random.sample(attractions, min(2, len(attractions))):
            query = f"{attraction} {market['name']} {market['state']}"
            img_path = fetch_unsplash_image(query, str(blog_images_dir))
            if img_path:
                # Append image reference at the end of post content for the builder to use
                content += f"\n\n![{attraction}]({img_path})\n*{attraction} — a must-visit near our {market['name']} properties.*\n"

    # Add property images with CTAs
    prop_images = pick_property_images(properties, count=2)
    for pi in prop_images:
        content += f"\n\n![{pi['property_name']}]({pi['image_path']})\n"
        content += f"*[{pi['property_name']} — Book your stay →]({pi['booking_url']})*\n"

    # Generate slug from title
    # Extract title from frontmatter
    if content.startswith('---'):
        _, fm_str, _ = content.split('---', 2)
        fm = yaml.safe_load(fm_str)
        title = fm.get('title', f'blog-{today}')
    else:
        title = f'blog-{today}'

    slug = title.lower()
    slug = slug.replace(' ', '-').replace(',', '').replace(':', '').replace('?', '')
    slug = slug.replace('(', '').replace(')', '').replace("'", '').replace('"', '')
    slug = '-'.join(slug.split('-')[:8])  # Limit slug length
    slug = slug.strip('-')

    # Save post
    market_content_dir = CONTENT_DIR / market_id
    os.makedirs(market_content_dir, exist_ok=True)
    
    output_path = market_content_dir / f"{slug}.md"
    
    # Avoid overwriting existing posts
    counter = 1
    while output_path.exists():
        output_path = market_content_dir / f"{slug}-{counter}.md"
        counter += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"✅ Saved: {output_path}")

    if planned_post:
        plan = load_content_plan()
        market_posts = plan.get('markets', {}).get(market_id, [])
        for p in market_posts:
            if p['title'] == planned_post['title'] and p['status'] == 'planned':
                p['status'] = 'published'
                p['file'] = str(output_path)
                break
        save_content_plan(plan)
        print(f"📝 Updated content plan for: {planned_post['title']}")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='Generate SEO blog posts for Springline Stays')
    parser.add_argument('--market', type=str, help='Target market ID (e.g., colorado-springs)')
    parser.add_argument('--count', type=int, default=1, help='Number of posts to generate')
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    config = load_config()
    market_ids = [m['id'] for m in config['markets']]
    plan = load_content_plan()

    for i in range(args.count):
        planned_post = None
        target_market = None
        
        if args.market:
            target_market = args.market
            # Find a planned post for this specific market
            market_posts = plan.get('markets', {}).get(target_market, [])
            for p in market_posts:
                if p['status'] == 'planned':
                    planned_post = p
                    break
        else:
            # Find all available planned posts
            all_planned = []
            for market_id in market_ids:
                market_posts = plan.get('markets', {}).get(market_id, [])
                for p in market_posts:
                    if p['status'] == 'planned':
                        all_planned.append((market_id, p))
            
            if all_planned:
                target_market, planned_post = random.choice(all_planned)
            else:
                print("ℹ️ No planned posts found in content plan. Falling back to market with fewest posts.")
                market_counts = {}
                for m_id in market_ids:
                    market_dir = CONTENT_DIR / m_id
                    if market_dir.exists():
                        market_counts[m_id] = len(list(market_dir.glob('*.md')))
                    else:
                        market_counts[m_id] = 0
                
                min_count = min(market_counts.values())
                candidates = [m for m, c in market_counts.items() if c == min_count]
                target_market = random.choice(candidates)

        if planned_post:
            print(f"🎯 Selected planned post: '{planned_post['title']}' for market '{target_market}'")
        
        generate_blog_post(config, target_market, planned_post)

    # Trigger build
    print("\n🔨 Triggering site build...")
    import subprocess
    try:
        subprocess.run([sys.executable, 'build.py'], check=True)
        print("✅ Site build completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Site build failed: {e}")


if __name__ == '__main__':
    main()
