#!/usr/bin/env python3
"""
Springline Stays — Static Site Generator

Reads property config + markdown blog posts, renders Jinja2 templates,
and outputs a complete static site to public/.
"""

import os
import glob
import re
import math
import shutil
import yaml
import markdown
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
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

    # Estimate reading time (~200 words per minute)
    word_count = len(md_content.split())
    meta['reading_time'] = max(1, math.ceil(word_count / 200))

    return meta, html_content


def collect_posts():
    """Collect all blog posts from content/ directories."""
    posts = []

    for market_dir in glob.glob(os.path.join(CONTENT_DIR, '*')):
        if not os.path.isdir(market_dir):
            continue
        market_id = os.path.basename(market_dir)

        for md_file in glob.glob(os.path.join(market_dir, '*.md')):
            meta, html_content = parse_markdown_file(md_file)
            slug = os.path.splitext(os.path.basename(md_file))[0]

            hero_image = meta.get('hero_image', '')
            if not hero_image:
                title = meta.get('title', 'Untitled')
                print(f"  Topic image missing for '{title}'. Fetching from Unsplash...")
                blog_images_dir = os.path.join(STATIC_DIR, 'images', 'blog', market_id)
                os.makedirs(blog_images_dir, exist_ok=True)
                hero_image = fetch_unsplash_image(title, blog_images_dir)
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

            post = {
                'title': meta.get('title', 'Untitled'),
                'date': str(meta.get('date', '')),
                'description': meta.get('description', ''),
                'hero_image': hero_image,
                'tags': meta.get('tags', []),
                'market': market_id,
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


def build():
    """Main build function."""
    print("Loading configuration...")
    config = load_config()
    brand = config['brand']
    markets = config['markets']
    properties = config['properties']

    # Create Jinja2 environment
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

    # Global template variables
    env.globals['brand'] = brand
    env.globals['markets'] = markets
    env.globals['current_year'] = datetime.now().year

    # Collect all posts
    print("Collecting blog posts...")
    all_posts = collect_posts()
    print(f"  Found {len(all_posts)} posts")

    # Clean and create output directory
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Copy static files
    if os.path.exists(STATIC_DIR):
        shutil.copytree(STATIC_DIR, os.path.join(OUTPUT_DIR, 'static'))
        print("Copied static files")

    # ─── Build Homepage ───
    print("Building homepage...")
    home_template = env.get_template('home.html')
    home_html = home_template.render(
        page_title="Springline Stays — Scenic Retreats and Campus Comforts",
        page_description="Vacation rentals in Colorado Springs, Gainesville, and Panama City Beach. Book direct and save.",
        markets=markets,
        properties=[p for p in properties if p.get('active')],
        latest_posts=all_posts[:6],
        transparent_nav=True,
        booking_domain=brand.get('hospitable_base', '#'),
    )
    with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(home_html)

    # ─── Build Market Pages ───
    for market in markets:
        market_id = market['id']
        print(f"Building market page: {market_id}...")

        market_dir = os.path.join(OUTPUT_DIR, market_id)
        os.makedirs(market_dir, exist_ok=True)

        market_properties = [p for p in properties if p['market'] == market_id and p.get('active')]
        market_posts = [p for p in all_posts if p['market'] == market_id]

        hub_template = env.get_template('location_hub.html')
        hub_html = hub_template.render(
            page_title=f"{market['name']}, {market['state']} — Springline Stays",
            page_description=market['hero_description'],
            market=market,
            market_properties=market_properties,
            market_posts=market_posts[:9],
            booking_domain=brand.get('hospitable_base', '#'),
        )
        with open(os.path.join(market_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(hub_html)

        # ─── Build Blog Index for Market ───
        blog_dir = os.path.join(market_dir, 'blog')
        os.makedirs(blog_dir, exist_ok=True)

        blog_index_template = env.get_template('blog_index.html')
        blog_index_html = blog_index_template.render(
            page_title=f"Blog — {market['name']} — Springline Stays",
            page_description=f"Travel guides, tips, and things to do in {market['name']}, {market['state']}.",
            market=market,
            posts=market_posts,
            markets=markets,
            booking_domain=brand.get('hospitable_base', '#'),
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

            post_html = post_template.render(
                page_title=f"{post['title']} — Springline Stays",
                page_description=post['description'],
                post=post,
                market=market,
                sidebar_properties=sidebar_properties,
                related_posts=related_posts,
                booking_domain=brand.get('hospitable_base', '#'),
            )

            post_path = os.path.join(blog_dir, f"{post['slug']}.html")
            with open(post_path, 'w', encoding='utf-8') as f:
                f.write(post_html)

    # ─── Build All-Posts Blog Index ───
    print("Building main blog index...")
    blog_all_dir = os.path.join(OUTPUT_DIR, 'blog')
    os.makedirs(blog_all_dir, exist_ok=True)

    blog_index_template = env.get_template('blog_index.html')
    blog_all_html = blog_index_template.render(
        page_title="Blog — Springline Stays",
        page_description="Travel guides, tips, and things to do near our vacation rentals.",
        market=None,
        posts=all_posts,
        markets=markets,
        booking_domain=brand.get('hospitable_base', '#'),
    )
    with open(os.path.join(blog_all_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(blog_all_html)

    print(f"\n✅ Build complete! {len(all_posts)} posts generated.")
    print(f"   Output: {OUTPUT_DIR}/")


if __name__ == '__main__':
    build()
