#!/usr/bin/env python3
"""
Check for duplicate Medium articles in our collection
"""

import json
from pathlib import Path
from collections import Counter

def main():
    """Check for duplicates in Medium articles"""
    
    # Get all Medium documents
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    print(f"Found {len(medium_docs)} Medium article files")
    
    # Track URLs and titles
    urls = []
    titles = []
    url_to_file = {}
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]  # Remove query params
                title = doc.get('title', '')
                
                urls.append(url)
                titles.append(title)
                
                if url in url_to_file:
                    url_to_file[url].append(doc_path.name)
                else:
                    url_to_file[url] = [doc_path.name]
                    
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    # Find duplicate URLs
    url_counts = Counter(urls)
    duplicate_urls = {url: count for url, count in url_counts.items() if count > 1}
    
    print(f"\nUnique URLs: {len(url_counts)}")
    
    if duplicate_urls:
        print(f"Found {len(duplicate_urls)} duplicate URLs:")
        for url, count in duplicate_urls.items():
            print(f"\n  {url}")
            print(f"  Appears {count} times in files:")
            for filename in url_to_file[url]:
                print(f"    - {filename}")
    else:
        print("No duplicate URLs found!")
    
    # Check against user-provided list
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        user_urls = json.load(f)
    
    user_urls_normalized = [url.split('?')[0] for url in user_urls]
    
    print(f"\n{'='*60}")
    print(f"User provided: {len(user_urls_normalized)} URLs")
    print(f"We have: {len(set(urls))} unique URLs")
    
    # Find what we're missing
    missing = []
    for url in user_urls_normalized:
        if url not in urls:
            missing.append(url)
    
    if missing:
        print(f"\nMissing {len(missing)} articles from user's list:")
        for url in missing[:10]:  # Show first 10
            print(f"  - {url}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")
    
    # Find what we have that user didn't provide
    extra = []
    for url in set(urls):
        if url and url not in user_urls_normalized:
            extra.append(url)
    
    if extra:
        print(f"\nWe have {len(extra)} articles not in user's list:")
        for url in extra[:10]:  # Show first 10
            print(f"  - {url}")
        if len(extra) > 10:
            print(f"  ... and {len(extra) - 10} more")
    
    print(f"\n{'='*60}")
    print(f"SUMMARY:")
    print(f"  Files: {len(medium_docs)}")
    print(f"  Unique URLs: {len(set(urls))}")
    print(f"  Duplicates: {sum(count - 1 for count in url_counts.values() if count > 1)}")
    print(f"  Target: 130 articles")
    print(f"  Status: {'✅ COMPLETE' if len(set(urls)) >= 130 else f'Need {130 - len(set(urls))} more'}")

if __name__ == "__main__":
    main()