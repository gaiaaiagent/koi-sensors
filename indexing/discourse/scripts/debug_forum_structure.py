#!/usr/bin/env python3
"""
Debug script to understand forum.regen.network HTML structure
"""

import httpx
from bs4 import BeautifulSoup
import json
from loguru import logger


def analyze_page(url: str):
    """Analyze the HTML structure of a page"""
    logger.info(f"Analyzing: {url}")
    
    client = httpx.Client(follow_redirects=True)
    response = client.get(url)
    
    logger.info(f"Status: {response.status_code}")
    logger.info(f"Final URL: {response.url}")
    
    if response.status_code != 200:
        logger.error(f"Failed to fetch page")
        return
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Check for Discourse-specific elements
    logger.info("\n=== Checking for Discourse elements ===")
    
    # Check for posts
    post_selectors = [
        'article.boxed',
        'div.topic-post',
        'article[data-post-id]',
        'div.post-stream',
        'div.posts-wrapper',
        'div.post-content',
        'div.cooked'
    ]
    
    for selector in post_selectors:
        elements = soup.select(selector)
        if elements:
            logger.success(f"✅ Found {len(elements)} elements with selector: {selector}")
            # Show first element's structure
            if elements:
                first = elements[0]
                logger.info(f"   Classes: {first.get('class', [])}")
                logger.info(f"   Text preview: {first.get_text()[:100]}...")
    
    # Check for JSON data
    logger.info("\n=== Checking for embedded JSON data ===")
    
    # Look for Discourse's preloaded store
    scripts = soup.find_all('script')
    for script in scripts:
        if script.string and 'PreloadStore' in script.string:
            logger.success("✅ Found PreloadStore data")
            # Try to extract topic data
            if '"topic"' in script.string:
                logger.info("   Contains topic data")
        if script.string and '__DISCOURSE_RAW_DATA__' in script.string:
            logger.success("✅ Found raw Discourse data")
    
    # Look for meta tags with data
    meta_tags = soup.find_all('meta', attrs={'name': True})
    discourse_meta = [m for m in meta_tags if 'discourse' in m.get('name', '').lower()]
    if discourse_meta:
        logger.success(f"✅ Found {len(discourse_meta)} Discourse meta tags")
        for meta in discourse_meta[:3]:
            logger.info(f"   {meta.get('name')}: {meta.get('content', '')[:50]}...")
    
    # Check if we need authentication
    if 'login' in str(response.url).lower() or 'You need to log in' in response.text:
        logger.warning("⚠️ Page might require authentication")
    
    # Save sample HTML for inspection
    with open('forum_sample.html', 'w', encoding='utf-8') as f:
        f.write(response.text)
    logger.info("\n📄 Saved full HTML to forum_sample.html for inspection")


def test_json_api(base_url: str, topic_id: str):
    """Test if JSON API endpoints work"""
    logger.info("\n=== Testing JSON API endpoints ===")
    
    client = httpx.Client(follow_redirects=True)
    
    endpoints = [
        f"{base_url}/t/{topic_id}.json",
        f"{base_url}/t/{topic_id}/posts.json",
        f"{base_url}/posts.json?topic_id={topic_id}",
    ]
    
    for endpoint in endpoints:
        try:
            logger.info(f"Testing: {endpoint}")
            response = client.get(endpoint)
            logger.info(f"  Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.success(f"  ✅ Got JSON with {len(data)} keys")
                
                # Check for posts
                if 'post_stream' in data:
                    posts = data['post_stream'].get('posts', [])
                    logger.info(f"  Found {len(posts)} posts")
                    if posts:
                        logger.info(f"  First post by: {posts[0].get('username', 'unknown')}")
                        
                # Save JSON for inspection
                with open(f'forum_api_sample_{topic_id}.json', 'w') as f:
                    json.dump(data, f, indent=2)
                logger.info(f"  📄 Saved to forum_api_sample_{topic_id}.json")
                return True
                
        except Exception as e:
            logger.error(f"  ❌ Error: {e}")
    
    return False


def main():
    """Run analysis"""
    # Test a specific topic page
    topic_url = "https://forum.regen.network/t/welcome-to-regen-network/5"
    analyze_page(topic_url)
    
    # Test JSON API
    test_json_api("https://forum.regen.network", "5")
    
    # Also test homepage
    logger.info("\n=== Analyzing homepage ===")
    analyze_page("https://forum.regen.network")


if __name__ == "__main__":
    main()