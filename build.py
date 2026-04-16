#!/usr/bin/env python3
"""
Springline Stays — Static Site Generator

Reads property config + markdown blog posts, renders Jinja2 templates,
and outputs a complete static site to public/.
"""

import os
import glob
import sys
import re
import math
import shutil
import yaml
import markdown
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
import difflib
from seo_agent import fetch_unsplash_image

# ─── Paths ───
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'properties.yaml')
CONTENT_DIR = os.path.join(BASE_DIR, 'content')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
OUTPUT_DIR = os.path.join(BASE_DIR, 'public')


def load_config():
    """Load the properties.yaml configuration."""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def parse_markdown_file(filepath):
    """Parse a markdown file with YAML frontmatter into metadata + HTML content."""
    with open(filepath, 'r', encoding='utf-8') as f:
        raw = f.read()

    if raw.startswith('---'):
        _, frontmatter_str, md_content = raw.split('---', 2)
        meta = yaml.safe_load(frontmatter_str) or {}
    else:
        meta = {}
        md_content = raw

    # Convert markdown to HTML with extensions
    html_content = markdown.markdown(
        md_content,
        extensions=['extra', 'codehilite', 'toc', 'tables', 'smarty'],
    )

    # Post-process HTML to add lazy loading to images
    html_content = re.sub(r'<img\b', r'<img loading="lazy"', html_content)

    # Estimate reading time (~200 words per minute)
    word_count = len(md_content.split())
    meta['reading_time'] = max(1, math.ceil(word_count / 200))

    return meta, html_content


def auto_link_content(html_content, markets):
    """Automatically link market names to their hubs if not already linked."""
    parts = re.split(r'(<[^>]+>)', html_content)
    in_link = False
    for i in range(len(parts)):
        if i % 2 == 1:  # It's a tag
            tag = parts[i].lower()
            if tag.startswith('<a'):
                in_link = True
            elif tag == '</a>':
                in_link = False
        else:  # It's text
            if not in_link:
                for market in markets:
                    name = market['name']
                    market_id = market['id']
                    url = f"/{market_id}/"
                    
                    pattern = rf'\b({re.escape(name)})\b'
                    replacement = rf'<a href="{url}" class="text-brand-gold hover:underline">{name}</a>'
                    
                    new_text, count = re.subn(pattern, replacement, parts[i], count=1)
                    if count > 0:
                        parts[i] = new_text
                        break  # Only link one market per text part
    return "".join(parts)


def check_for_similar_posts(all_posts, threshold=0.8):
    """Check for posts with highly similar titles and print warnings."""
    print("\n🔍 Checking for similar posts...")
    for i, post1 in enumerate(all_posts):
        for post2 in all_posts[i+1:]:
            title1 = post1['title']
            title2 = post2['title']
            
            ratio = difflib.SequenceMatcher(None, title1, title2).ratio()
            
            if ratio >= threshold:
                print(f"  ⚠ Warning: Highly similar titles detected ({int(ratio*100)}%):")
                print(f"    - {title1} ({post1['market']})")
                print(f"    - {title2} ({post2['market']})")


def select_balanced_posts(all_posts, count=6):
    """Select posts randomly but balanced across markets."""
    import random
    
    # Group posts by market
    market_groups = {}
    for post in all_posts:
        market = post['market']
        if market not in market_groups:
            market_groups[market] = []
        market_groups[market].append(post)
        
    # Shuffle posts within each market
    for market in market_groups:
        random.shuffle(market_groups[market])
        
    selected_posts = []
    markets = list(market_groups.keys())
    
    # Round-robin selection
    while len(selected_posts) < count and market_groups:
        for market in list(markets):
            if market_groups[market]:
                selected_posts.append(market_groups[market].pop(0))
                if len(selected_posts) >= count:
                    break
            else:
                # Remove empty market group
                del market_groups[market]
                markets.remove(market)
                
    # Shuffle the final selection so they don't appear grouped by market
    random.shuffle(selected_posts)
    return selected_posts


def collect_posts(properties):
    """Collect all blog posts from content/ directories."""
    posts = []
    config = load_config()
    markets = config.get('markets', [])

    for market_dir in glob.glob(os.path.join(CONTENT_DIR, '*')):
        if not os.path.isdir(market_dir):
            continue
        market_id = os.path.basename(market_dir)

        for md_file in glob.glob(os.path.join(market_dir, '*.md')):
            meta, html_content = parse_markdown_file(md_file)
            html_content = auto_link_content(html_content, markets)
            slug = os.path.splitext(os.path.basename(md_file))[0]

            # Skip future dated posts
            post_date_str = str(meta.get('date', ''))
            today_str = datetime.now().strftime('%Y-%m-%d')
            if post_date_str > today_str:
                print(f"  Skipping future post: {slug} (Date: {post_date_str})")
                continue

            # Scan for missing images in the body
            img_matches = re.finditer(r'<img([^>]+)>', html_content)
            for match in img_matches:
                img_attrs = match.group(1)
                src_match = re.search(r'src="([^"]+)"', img_attrs)
                if src_match:
                    src = src_match.group(1)
                    if src.startswith('/static/images/blog/'):
                        relative_src = src.lstrip('/')
                        if relative_src.startswith('static/'):
                            relative_src = relative_src[len('static/'):]
                        local_path = os.path.join(STATIC_DIR, relative_src)
                        if not os.path.exists(local_path):
                            print(f"  Missing body image: {src}")
                            alt_match = re.search(r'alt="([^"]+)"', img_attrs)
                            query = alt_match.group(1) if alt_match else slug
                            
                            print(f"  Fetching missing body image for query: '{query}'...")
                            blog_images_dir = os.path.dirname(local_path)
                            os.makedirs(blog_images_dir, exist_ok=True)
                            
                            fetched_path = fetch_unsplash_image(query, blog_images_dir)
                            if fetched_path:
                                print(f"  Successfully fetched body image: {fetched_path}")
                                # Rename to match requested path
                                fetched_local_path = os.path.join(BASE_DIR, fetched_path.lstrip('/'))
                                try:
                                    os.rename(fetched_local_path, local_path)
                                    print(f"  Renamed fetched file to match request: {local_path}")
                                except Exception as e:
                                    print(f"  Failed to rename fetched file: {e}")

            hero_image = meta.get('hero_image', '')
            if not hero_image:
                title = meta.get('title', 'Untitled')
                print(f"  Topic image missing for '{title}'. Fetching from Unsplash...")
                blog_images_dir = os.path.join(STATIC_DIR, 'images', 'blog', market_id)
                os.makedirs(blog_images_dir, exist_ok=True)
                hero_image = fetch_unsplash_image(title, blog_images_dir)
                
                if not hero_image:
                    print(f"  Failed to fetch image for title. Trying market fallback for '{market_id}'...")
                    hero_image = fetch_unsplash_image(market_id, blog_images_dir)
                
                if hero_image:
                    print(f"  Successfully fetched image: {hero_image}")
                    
                    # Write back to markdown file to lock it in
                    try:
                        with open(md_file, 'r', encoding='utf-8') as f:
                            raw = f.read()
                        if raw.startswith('---'):
                            parts = raw.split('---', 2)
                            frontmatter = yaml.safe_load(parts[1]) or {}
                            frontmatter['hero_image'] = hero_image
                            new_frontmatter_str = yaml.dump(frontmatter, sort_keys=False)
                            new_raw = f"---\n{new_frontmatter_str}---{parts[2]}"
                            with open(md_file, 'w', encoding='utf-8') as f:
                                f.write(new_raw)
                            print(f"  Updated frontmatter in {md_file}")
                    except Exception as e:
                        print(f"  ⚠  Failed to update markdown file: {e}")

            # Extract referenced properties
            referenced_props = []
            booking_domain = config.get('brand', {}).get('hospitable_base', 'https://book.springlinestays.com')
            prop_urls = re.findall(fr'{re.escape(booking_domain)}/property/([a-zA-Z0-9-]+)', html_content)
            
            for prop_slug in prop_urls:
                for p in properties:
                    if prop_slug in p.get('booking_url', ''):
                        if p not in referenced_props:
                            referenced_props.append(p)
                        break

            post = {
                'title': meta.get('title', 'Untitled'),
                'date': str(meta.get('date', '')),
                'description': meta.get('description', ''),
                'hero_image': hero_image,
                'referenced_properties': referenced_props,
                'thumbnail_url': hero_image,
                'tags': meta.get('tags', []),
                'market': market_id,
                'is_topic': market_id == 'property-management',
                'content': html_content,
                'reading_time': meta.get('reading_time', 5),
                'slug': slug,
                'url': f'/{market_id}/blog/{slug}.html',
            }
            posts.append(post)

    # Sort by date descending
    posts.sort(key=lambda p: p['date'], reverse=True)
    return posts


def find_related_posts(current_post, all_posts, max_count=3):
    """Find related posts by same market, excluding current."""
    related = [
        p for p in all_posts
        if p['market'] == current_post['market'] and p['slug'] != current_post['slug']
    ]
    return related[:max_count]


def pick_sidebar_property(market_id, properties):
    """Pick a property to show in the sidebar for a given market."""
    market_props = [p for p in properties if p['market'] == market_id and p.get('active')]
    if not market_props:
        # Fallback to any active property
        market_props = [p for p in properties if p.get('active')]
    if market_props:
        # Simple rotation based on current day
        idx = datetime.now().timetuple().tm_yday % len(market_props)
        return market_props[idx]
    return None


def verify_assets_and_links(all_posts, markets, properties):
    """Verify that all linked assets exist and internal links are valid."""
    print("Verifying assets and links...")
    errors = []

    # Build valid routes
    valid_routes = {'/', '/blog/'}
    for m in markets:
        valid_routes.add(f"/{m['id']}/")
        valid_routes.add(f"/{m['id']}/blog/")
    for p in all_posts:
        valid_routes.add(p['url'])

    # Check all posts
    for post in all_posts:
        html_content = post['content']
        slug = post['slug']
        
        # Extract links and images
        img_matches = re.finditer(r'<img([^>]+)>', html_content)
        for match in img_matches:
            img_attrs = match.group(1)
            src_match = re.search(r'src="([^"]+)"', img_attrs)
            if src_match:
                src = src_match.group(1)
                if src.startswith('/static/'):
                    local_path = os.path.join(BASE_DIR, src.lstrip('/'))
                    if not os.path.exists(local_path):
                        errors.append(f"Post '{slug}': Missing asset '{src}'")

        link_matches = re.finditer(r'<a([^>]+)>', html_content)
        for match in link_matches:
            link_attrs = match.group(1)
            href_match = re.search(r'href="([^"]+)"', link_attrs)
            if href_match:
                href = href_match.group(1)
                if href.startswith('/'):
                    if href not in valid_routes and not href.startswith('/static/'):
                        if not href.startswith('#'):
                            errors.append(f"Post '{slug}': Broken internal link '{href}'")

    if errors:
        print(f"\n❌ Verification failed with {len(errors)} errors:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("✅ All assets and links verified successfully!")


def build():
    """Main build function."""
    print("Loading configuration...")
    config = load_config()
    brand = config['brand']
    markets = config['markets']
    properties = config['properties']
    
    # Load reviews if available
    reviews_path = os.path.join(BASE_DIR, 'config', 'reviews.yaml')
    reviews = []
    if os.path.exists(reviews_path):
        with open(reviews_path, 'r', encoding='utf-8') as f:
            reviews = yaml.safe_load(f) or []

    # Alternate reviews from different properties to ensure diversity
    if reviews:
        from collections import defaultdict
        reviews_by_prop = defaultdict(list)
        for r in reviews:
            reviews_by_prop[r.get('property_name') or r.get('property_public_name')].append(r)
        
        alternated_reviews = []
        max_len = max(len(lst) for lst in reviews_by_prop.values()) if reviews_by_prop else 0
        for i in range(max_len):
            for prop in reviews_by_prop:
                if i < len(reviews_by_prop[prop]):
                    alternated_reviews.append(reviews_by_prop[prop][i])
        reviews = alternated_reviews

    # Enrich properties with images and reviews
    for p in properties:
        # 1. Images
        image_dir = p.get('image_dir')
        if image_dir:
            abs_image_dir = os.path.join(BASE_DIR, image_dir)
            if os.path.exists(abs_image_dir):
                images = glob.glob(os.path.join(abs_image_dir, '*.jpg'))
                # Convert to relative paths for web
                p['images'] = ['/' + os.path.relpath(img, BASE_DIR) for img in images]
            else:
                p['images'] = [p.get('image_url')] if p.get('image_url') else []
        else:
             p['images'] = [p.get('image_url')] if p.get('image_url') else []
             
        # 2. Reviews
        prop_reviews = []
        prop_name = p.get('name')
        prop_headline = p.get('headline')
        
        for r in reviews:
            r_prop_name = r.get('property_name')
            r_prop_public = r.get('property_public_name')
            
            if (prop_name and r_prop_name == prop_name) or (prop_headline and r_prop_public == prop_headline):
                prop_reviews.append(r)
                
        p['reviews'] = prop_reviews
        
        if prop_reviews:
            ratings = [float(r.get('rating', 5)) for r in prop_reviews]
            p['aggregate_rating'] = {
                'rating_value': sum(ratings) / len(ratings),
                'review_count': len(ratings)
            }
        else:
            p['aggregate_rating'] = None

        # 3. Generate JSON-LD for properties
        address_dict = {"@type": "PostalAddress"}
        if p.get('street_address'): address_dict["streetAddress"] = p['street_address']
        if p.get('address_locality'): address_dict["addressLocality"] = p['address_locality']
        if p.get('address_region'): address_dict["addressRegion"] = p['address_region']
        if p.get('postal_code'): address_dict["postalCode"] = p['postal_code']
        if p.get('address_country'): address_dict["addressCountry"] = p['address_country']
        
        # Fallback to full address if street_address is missing
        if "streetAddress" not in address_dict and p.get('address'):
            address_dict["streetAddress"] = p['address']

        json_ld = {
            "@type": "VacationRental",
            "additionalType": "http://www.productontology.org/id/Vacation_rental",
            "identifier": p.get('id'),
            "name": p.get('headline'),
            "url": p.get('booking_url'),
            "description": p.get('description', '').replace('\n', ' '),
            "image": [f"https://springlinestays.com{img}" for img in p.get('images', [])],
            "address": address_dict,
            "containsPlace": {
                "@type": "Accommodation",
                "additionalType": "EntirePlace",
                "numberOfBedrooms": p.get('bedrooms'),
                "numberOfBathroomsTotal": p.get('bathrooms'),
                "occupancy": {
                    "@type": "QuantitativeValue",
                    "value": p.get('guests')
                },
                "amenityFeature": [
                    {
                        "@type": "LocationFeatureSpecification",
                        "name": amenity,
                        "value": True
                    } for amenity in p.get('amenities', [])
                ]
            }
        }

        if p.get('aggregate_rating'):
            json_ld["aggregateRating"] = {
                "@type": "AggregateRating",
                "ratingValue": str(p['aggregate_rating']['rating_value']),
                "reviewCount": str(p['aggregate_rating']['review_count'])
            }

        if p.get('reviews'):
            json_ld["review"] = [
                {
                    "@type": "Review",
                    "author": {"@type": "Person", "name": r.get('author')},
                    "reviewBody": r.get('text'),
                    "datePublished": r.get('date')
                }
                for r in p['reviews']
            ]

        import json
        p['json_ld_str'] = json.dumps(json_ld, indent=2)

    # Create Jinja2 environment
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

    # Global template variables
    env.globals['brand'] = brand
    env.globals['markets'] = markets
    env.globals['current_year'] = datetime.now().year
    env.globals['site_url'] = 'https://springlinestays.com'

    urls = ['/']

    # Collect all posts
    print("Collecting blog posts...")
    all_posts = collect_posts(properties)
    print(f"  Found {len(all_posts)} posts")
    
    # Check for similar posts
    check_for_similar_posts(all_posts)

    # Verify assets and links
    verify_assets_and_links(all_posts, markets, properties)

    # Clean and create output directory
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Copy static files
    if os.path.exists(STATIC_DIR):
        shutil.copytree(STATIC_DIR, os.path.join(OUTPUT_DIR, 'static'))
        # Copy robots.txt to root
        robots_src = os.path.join(STATIC_DIR, 'robots.txt')
        if os.path.exists(robots_src):
            shutil.copy(robots_src, os.path.join(OUTPUT_DIR, 'robots.txt'))
        print("Copied static files")

    # ─── Build Homepage ───
    print("Building homepage...")
    home_template = env.get_template('home.html')
    home_html = home_template.render(
        page_title="Springline Stays — Scenic Retreats and Campus Comforts",
        page_description="Vacation rentals in Colorado Springs, Gainesville, and Panama City Beach. Book direct and save.",
        markets=markets,
        properties=[p for p in properties if p.get('active')],
        latest_posts=select_balanced_posts(all_posts, 6),
        reviews=reviews[:12],
        transparent_nav=True,
        booking_domain=brand.get('hospitable_base', '#'),
        request_path='/',
    )
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(home_html)

    # ─── Build Contact Page ───
    print("Building contact page...")
    contact_template = env.get_template('contact.html')
    contact_dir = os.path.join(OUTPUT_DIR, 'contact')
    os.makedirs(contact_dir, exist_ok=True)
    urls.append("/contact/")
    contact_html = contact_template.render(
        booking_domain=brand.get('hospitable_base', '#'),
        request_path='/contact/',
    )
    with open(os.path.join(contact_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(contact_html)

    # ─── Build Property Management Page ───
    print("Building property management page...")
    pm_template = env.get_template('property_management.html')
    pm_dir = os.path.join(OUTPUT_DIR, 'property-management')
    os.makedirs(pm_dir, exist_ok=True)
    urls.append("/property-management/")
    
    # Load property management config
    pm_config_path = os.path.join(os.path.dirname(CONFIG_PATH), 'property_management.yaml')
    pm_data = {}
    if os.path.exists(pm_config_path):
        with open(pm_config_path, 'r', encoding='utf-8') as f:
            pm_data = yaml.safe_load(f) or {}
            
    # Filter posts for property management
    pm_posts = [p for p in all_posts if p.get('market') == 'property-management']
            
    pm_html = pm_template.render(
        booking_domain=brand.get('hospitable_base', '#'),
        request_path='/property-management/',
        posts=pm_posts,
        **pm_data
    )
    with open(os.path.join(pm_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(pm_html)

    # ─── Build Property Management Blog Posts ───
    pm_blog_dir = os.path.join(pm_dir, 'blog')
    os.makedirs(pm_blog_dir, exist_ok=True)
    post_template = env.get_template('blog_post.html')
    
    synthetic_market = {'id': 'property-management', 'name': 'Property Management'}
    
    for post in pm_posts:
        print(f"  Building property management post: {post['slug']}...")
        
        sidebar_properties = [p for p in properties if p.get('active')]
        related_posts = find_related_posts(post, all_posts)
        
        urls.append(post['url'])
        post_html = post_template.render(
            page_title=f"{post['title']} — Springline Stays",
            page_description=post['description'],
            post=post,
            market=synthetic_market,
            sidebar_properties=sidebar_properties,
            related_posts=related_posts,
            booking_domain=brand.get('hospitable_base', '#'),
            request_path=post['url'],
        )
        
        post_path = os.path.join(pm_blog_dir, f"{post['slug']}.html")
        with open(post_path, 'w', encoding='utf-8') as f:
            f.write(post_html)

    # ─── Build FAQ Page ───
    print("Building FAQ page...")
    faq_template = env.get_template('faq.html')
    faq_dir = os.path.join(OUTPUT_DIR, 'faq')
    os.makedirs(faq_dir, exist_ok=True)
    urls.append("/faq/")
    faq_html = faq_template.render(
        booking_domain=brand.get('hospitable_base', '#'),
        request_path='/faq/',
    )
    with open(os.path.join(faq_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(faq_html)

    # ─── Build Market Pages ───
    for market in markets:
        market_id = market['id']
        if market_id == 'property-management':
            continue
        print(f"Building market page: {market_id}...")

        market_dir = os.path.join(OUTPUT_DIR, market_id)
        os.makedirs(market_dir, exist_ok=True)

        market_properties = [p for p in properties if p['market'] == market_id and p.get('active')]
        market_posts = [p for p in all_posts if p['market'] == market_id]

        hub_template = env.get_template('location_hub.html')
        urls.append(f"/{market_id}/")
        hub_html = hub_template.render(
            page_title=f"{market['name']}, {market['state']} — Springline Stays",
            page_description=market['hero_description'],
            market=market,
            market_properties=market_properties,
            market_posts=market_posts[:9],
            booking_domain=brand.get('hospitable_base', '#'),
            request_path=f'/{market_id}/',
        )
        with open(os.path.join(market_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(hub_html)

        # ─── Build Blog Index for Market ───
        blog_dir = os.path.join(market_dir, 'blog')
        os.makedirs(blog_dir, exist_ok=True)

        blog_index_template = env.get_template('blog_index.html')
        urls.append(f"/{market_id}/blog/")
        blog_index_html = blog_index_template.render(
            page_title=f"Blog — {market['name']} — Springline Stays",
            page_description=f"Travel guides, tips, and things to do in {market['name']}, {market['state']}.",
            market=market,
            posts=market_posts,
            markets=markets,
            booking_domain=brand.get('hospitable_base', '#'),
            request_path=f'/{market_id}/blog/',
        )
        with open(os.path.join(blog_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(blog_index_html)

        # ─── Build Individual Blog Posts ───
        post_template = env.get_template('blog_post.html')
        for post in market_posts:
            print(f"  Building post: {post['slug']}...")

            sidebar_properties = [p for p in properties if p.get('market') == market_id and p.get('active')]
            if not sidebar_properties:
                sidebar_properties = [p for p in properties if p.get('active')]
            related_posts = find_related_posts(post, all_posts)

            urls.append(post['url'])
            post_html = post_template.render(
                page_title=f"{post['title']} — Springline Stays",
                page_description=post['description'],
                post=post,
                market=market,
                sidebar_properties=sidebar_properties,
                related_posts=related_posts,
                booking_domain=brand.get('hospitable_base', '#'),
                request_path=post['url'],
            )

            post_path = os.path.join(blog_dir, f"{post['slug']}.html")
            with open(post_path, 'w', encoding='utf-8') as f:
                f.write(post_html)

    # ─── Build All-Posts Blog Index ───
    print("Building main blog index...")
    blog_all_dir = os.path.join(OUTPUT_DIR, 'blog')
    os.makedirs(blog_all_dir, exist_ok=True)

    blog_index_template = env.get_template('blog_index.html')
    urls.append('/blog/')
    blog_all_html = blog_index_template.render(
        page_title="Blog — Springline Stays",
        page_description="Travel guides, tips, and things to do near our vacation rentals.",
        market=None,
        posts=all_posts,
        markets=markets,
        booking_domain=brand.get('hospitable_base', '#'),
        request_path='/blog/',
    )
    with open(os.path.join(blog_all_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(blog_all_html)

    # ─── Build Sitemap ───
    print("Building sitemap.xml...")
    generate_sitemap(urls, os.path.join(OUTPUT_DIR, 'sitemap.xml'))

    print(f"\n✅ Build complete! {len(all_posts)} posts generated.")
    print(f"   Output: {OUTPUT_DIR}/")


def generate_sitemap(urls, output_path):
    """Generate sitemap.xml from a list of URLs."""
    now = datetime.now().strftime('%Y-%m-%d')
    xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    for url in urls:
        full_url = f"https://springlinestays.com{url}"
        
        # Determine priority based on URL structure
        if url == '/':
            priority = '1.0'
        elif url == '/blog/' or re.match(r'^/[a-zA-Z0-9-]+/blog/$', url):
            priority = '0.8'
        elif url == '/property-management/' or (re.match(r'^/[a-zA-Z0-9-]+/$', url) and url not in ['/faq/', '/contact/']):
            priority = '0.9'
        else:
            priority = '0.7'
            
        xml.append('  <url>')
        xml.append(f'    <loc>{full_url}</loc>')
        xml.append(f'    <lastmod>{now}</lastmod>')
        xml.append(f'    <priority>{priority}</priority>')
        xml.append('  </url>')
        
    xml.append('</urlset>')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(xml))


if __name__ == '__main__':
    build()
