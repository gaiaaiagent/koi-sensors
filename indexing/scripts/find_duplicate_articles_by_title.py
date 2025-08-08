#!/usr/bin/env python3
"""
Find duplicate articles by comparing titles (since same article might have different URLs)
"""

import json
from pathlib import Path
import re

def normalize_title(title):
    """Normalize title for comparison"""
    # Remove special characters and lowercase
    title = re.sub(r'[^\w\s]', '', title.lower())
    # Remove extra whitespace
    title = ' '.join(title.split())
    return title

def main():
    """Find duplicate articles by title"""
    
    # Load all Medium documents
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    
    # Track articles by normalized title
    articles_by_title = {}
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]
                title = doc.get('title', 'No title')
                normalized = normalize_title(title)
                
                if normalized not in articles_by_title:
                    articles_by_title[normalized] = []
                
                articles_by_title[normalized].append({
                    'file': doc_path.name,
                    'url': url,
                    'title': title
                })
                
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    # Find duplicates (same title, different URLs)
    duplicates = {}
    for norm_title, articles in articles_by_title.items():
        if len(articles) > 1:
            duplicates[norm_title] = articles
    
    print(f"Total unique titles: {len(articles_by_title)}")
    print(f"Titles with multiple URLs: {len(duplicates)}")
    
    if duplicates:
        print(f"\n{'='*60}")
        print("DUPLICATE ARTICLES (same title, different URLs):")
        print(f"{'='*60}")
        
        for norm_title, articles in sorted(duplicates.items()):
            print(f"\nTitle: {articles[0]['title']}")
            print(f"Found in {len(articles)} files:")
            for article in articles:
                # Check URL format
                if 'regen-network.medium.com' in article['url']:
                    url_format = "NEW FORMAT"
                elif 'medium.com/regen-network' in article['url']:
                    url_format = "OLD FORMAT"
                else:
                    url_format = "OTHER"
                    
                print(f"  [{url_format}] {article['url']}")
                print(f"    File: {article['file']}")
    
    # Also check specific examples
    print(f"\n{'='*60}")
    print("CHECKING SPECIFIC EXAMPLES:")
    print(f"{'='*60}")
    
    # Look for articles that should be duplicates
    examples = [
        "planetary regeneration podcast episode 19",
        "urban forestry part",
        "mercedes",
        "terrasos"
    ]
    
    for example in examples:
        print(f"\nSearching for '{example}':")
        found = []
        for norm_title, articles in articles_by_title.items():
            if example in norm_title:
                found.extend(articles)
        
        if found:
            for article in found:
                print(f"  - {article['title']}")
                print(f"    URL: {article['url']}")

if __name__ == "__main__":
    main()