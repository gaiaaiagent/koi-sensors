#!/usr/bin/env python3
"""
Analyze the difference between what we have and what the user provided
"""

import json
from pathlib import Path

def main():
    """Find the exact differences"""
    
    # Load user-provided URLs (the 130 they counted)
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        user_urls = json.load(f)
    
    user_urls_normalized = set(url.split('?')[0] for url in user_urls)
    print(f"User counted and provided: {len(user_urls_normalized)} articles")
    
    # Load what we have
    our_urls = {}  # url -> filename
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]
                title = doc.get('title', 'No title')
                our_urls[url] = {'file': doc_path.name, 'title': title}
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    our_urls_set = set(our_urls.keys())
    print(f"We have: {len(our_urls_set)} unique articles")
    
    # Find the extra 8 articles we have that user didn't provide
    extra_articles = our_urls_set - user_urls_normalized
    
    print(f"\n{'='*60}")
    print(f"EXTRA ARTICLES (not in user's list of 130):")
    print(f"Found {len(extra_articles)} articles we collected that weren't in the user's list")
    print("="*60)
    
    # Group by domain pattern
    regen_medium = []
    medium_regen = []
    other = []
    
    for url in sorted(extra_articles):
        if 'regen-network.medium.com' in url:
            regen_medium.append(url)
        elif 'medium.com/regen-network' in url:
            medium_regen.append(url)
        else:
            other.append(url)
    
    if medium_regen:
        print(f"\nFrom medium.com/regen-network ({len(medium_regen)} articles):")
        for url in medium_regen:
            info = our_urls[url]
            print(f"\n  URL: {url}")
            print(f"  Title: {info['title']}")
            print(f"  File: {info['file']}")
    
    if regen_medium:
        print(f"\nFrom regen-network.medium.com ({len(regen_medium)} articles):")
        for url in regen_medium:
            info = our_urls[url]
            print(f"\n  URL: {url}")
            print(f"  Title: {info['title']}")
            print(f"  File: {info['file']}")
    
    if other:
        print(f"\nOther domains ({len(other)} articles):")
        for url in other:
            info = our_urls[url]
            print(f"\n  URL: {url}")
            print(f"  Title: {info['title']}")
            print(f"  File: {info['file']}")
    
    # Also check what we're missing from user's list
    missing = user_urls_normalized - our_urls_set
    if missing:
        print(f"\n{'='*60}")
        print(f"MISSING ARTICLES (in user's list but not collected):")
        print(f"Found {len(missing)} articles we haven't collected")
        print("="*60)
        for url in sorted(missing)[:10]:
            print(f"  {url}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")

if __name__ == "__main__":
    main()