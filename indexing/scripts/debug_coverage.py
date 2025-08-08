#!/usr/bin/env python3
"""
Debug why we don't have all 130 URLs from the user's list
"""

import json
from pathlib import Path

def main():
    """Debug coverage issues"""
    
    # Load user's 130 URLs
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        user_urls = json.load(f)
    
    print(f"User provided: {len(user_urls)} URLs")
    print(f"First 3 user URLs:")
    for url in user_urls[:3]:
        print(f"  - {url}")
    
    # Check for duplicates in user's list
    unique_user_urls = set(url.split('?')[0] for url in user_urls)
    print(f"\nUnique URLs in user's list: {len(unique_user_urls)}")
    if len(unique_user_urls) != len(user_urls):
        print("WARNING: User's list contains duplicates!")
    
    # Load our documents
    our_urls = set()
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    print(f"\nWe have {len(medium_docs)} Medium files")
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                # Get primary URL
                url = doc.get('url', '').split('?')[0]
                if url:
                    our_urls.add(url)
                # Also check alternate URLs
                for alt_url in doc.get('alternate_urls', []):
                    if alt_url:
                        our_urls.add(alt_url.split('?')[0])
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    print(f"Total URLs we have (including alternates): {len(our_urls)}")
    
    # Check each user URL individually
    missing_urls = []
    found_urls = []
    
    for user_url in user_urls:
        normalized = user_url.split('?')[0]
        if normalized in our_urls:
            found_urls.append(normalized)
        else:
            missing_urls.append(normalized)
    
    print(f"\n{'='*60}")
    print(f"DETAILED COVERAGE:")
    print(f"Found {len(found_urls)} of {len(user_urls)} URLs")
    print(f"Missing {len(missing_urls)} URLs")
    
    if missing_urls:
        print(f"\nMissing URLs from user's list:")
        for i, url in enumerate(missing_urls[:10], 1):
            print(f"{i}. {url}")
        if len(missing_urls) > 10:
            print(f"... and {len(missing_urls) - 10} more")
    
    # Debug: Check if URLs are there but with different format
    print(f"\n{'='*60}")
    print("CHECKING URL FORMAT ISSUES:")
    
    # Extract just the article ID from URLs
    def get_article_id(url):
        # Get the last part of the URL (after the last /)
        parts = url.rstrip('/').split('/')
        if parts:
            return parts[-1].split('-')[-1]  # Get the hash at the end
        return None
    
    user_ids = {}
    for url in user_urls:
        article_id = get_article_id(url)
        if article_id:
            user_ids[article_id] = url
    
    our_ids = {}
    for url in our_urls:
        article_id = get_article_id(url)
        if article_id:
            our_ids[article_id] = url
    
    print(f"User article IDs: {len(user_ids)}")
    print(f"Our article IDs: {len(our_ids)}")
    
    # Find IDs we're missing
    missing_ids = set(user_ids.keys()) - set(our_ids.keys())
    if missing_ids:
        print(f"\nMissing article IDs: {len(missing_ids)}")
        for article_id in list(missing_ids)[:5]:
            print(f"  ID: {article_id}")
            print(f"  User URL: {user_ids[article_id]}")

if __name__ == "__main__":
    main()