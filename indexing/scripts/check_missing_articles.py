#!/usr/bin/env python3
"""
Check which of the 130 user-provided articles we're missing
"""

import json
from pathlib import Path

def main():
    """Find exactly which articles we're missing"""
    
    # Load user's 130 articles
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        user_urls = json.load(f)
    
    print(f"User provided: {len(user_urls)} article URLs")
    
    # Load what we have
    our_articles = {}  # normalized_url -> doc
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]
                alt_urls = doc.get('alternate_urls', [])
                
                # Store all URLs for this article
                for u in [url] + alt_urls:
                    if u:
                        our_articles[u.split('?')[0]] = doc
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    print(f"We have: {len(medium_docs)} files")
    print(f"Covering: {len(our_articles)} unique URLs")
    
    # Check each user URL
    found = []
    missing = []
    
    for user_url in user_urls:
        normalized = user_url.split('?')[0]
        if normalized in our_articles:
            found.append(normalized)
        else:
            missing.append(normalized)
    
    print(f"\n{'='*60}")
    print(f"COVERAGE REPORT:")
    print(f"{'='*60}")
    print(f"Found: {len(found)}/{len(user_urls)} articles from your list")
    print(f"Missing: {len(missing)}/{len(user_urls)} articles")
    
    if missing:
        print(f"\n{'='*60}")
        print(f"MISSING ARTICLES ({len(missing)} total):")
        print(f"{'='*60}")
        for i, url in enumerate(missing, 1):
            # Extract title from URL
            title_part = url.split('/')[-1]
            title = title_part.replace('-', ' ').split('?')[0]
            print(f"{i:3}. {url}")
            print(f"     Title hint: {title[:60]}...")
    
    # Group missing by pattern
    podcast_missing = [u for u in missing if 'podcast' in u.lower()]
    other_missing = [u for u in missing if 'podcast' not in u.lower()]
    
    print(f"\n{'='*60}")
    print(f"MISSING BY TYPE:")
    print(f"{'='*60}")
    print(f"Podcast episodes: {len(podcast_missing)}")
    print(f"Other articles: {len(other_missing)}")

if __name__ == "__main__":
    main()