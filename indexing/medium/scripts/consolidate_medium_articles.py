#!/usr/bin/env python3
"""
Consolidate Medium articles - keep one copy per unique article with all URLs in metadata
"""

import json
from pathlib import Path
import re

def normalize_title(title):
    """Normalize title for comparison"""
    title = re.sub(r'[^\w\s]', '', title.lower())
    title = ' '.join(title.split())
    return title

def main():
    """Consolidate duplicate articles"""
    
    # Load all Medium documents
    medium_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    print(f"Starting with {len(medium_docs)} Medium article files")
    
    # Group articles by normalized title
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
                    'file': doc_path,
                    'doc': doc,
                    'url': url
                })
                
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    print(f"Found {len(articles_by_title)} unique articles by title")
    
    # Process each unique article
    files_to_remove = []
    consolidated_count = 0
    
    for norm_title, articles in articles_by_title.items():
        if len(articles) > 1:
            # Multiple files for same article - consolidate
            consolidated_count += 1
            
            # Collect all URLs
            all_urls = [a['url'] for a in articles]
            
            # Keep the first file, update it with all URLs
            keeper = articles[0]
            keeper_doc = keeper['doc']
            
            # Add alternate_urls field if not exists
            if 'alternate_urls' not in keeper_doc:
                keeper_doc['alternate_urls'] = []
            
            # Add all other URLs to alternate_urls
            for article in articles[1:]:
                if article['url'] not in keeper_doc['alternate_urls']:
                    keeper_doc['alternate_urls'].append(article['url'])
                files_to_remove.append(article['file'])
            
            # Save updated document
            with open(keeper['file'], 'w') as f:
                json.dump(keeper_doc, f, indent=2)
            
            print(f"Consolidated: {keeper_doc['title']}")
            print(f"  Primary URL: {keeper['url']}")
            print(f"  Alternate URLs: {keeper_doc['alternate_urls']}")
    
    # Remove duplicate files
    print(f"\nRemoving {len(files_to_remove)} duplicate files...")
    for file_path in files_to_remove:
        file_path.unlink()
        print(f"  Removed: {file_path.name}")
    
    # Final count
    final_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    
    print(f"\n{'='*60}")
    print(f"CONSOLIDATION COMPLETE")
    print(f"  Started with: {len(medium_docs)} files")
    print(f"  Unique articles: {len(articles_by_title)}")
    print(f"  Consolidated: {consolidated_count} articles with multiple URLs")
    print(f"  Removed: {len(files_to_remove)} duplicate files")
    print(f"  Final count: {len(final_docs)} unique Medium articles")
    
    # Verify against user's list
    with open("indexing/storage/user_provided_medium_urls.json") as f:
        user_urls = json.load(f)
    
    # Check coverage
    user_urls_normalized = set(url.split('?')[0] for url in user_urls)
    
    covered = 0
    for doc_path in final_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]
                alt_urls = doc.get('alternate_urls', [])
                
                all_doc_urls = [url] + alt_urls
                for doc_url in all_doc_urls:
                    if doc_url in user_urls_normalized:
                        covered += 1
                        break
        except:
            pass
    
    print(f"\n  Coverage of user's 130 articles: {covered}/130 ({covered/130*100:.1f}%)")

if __name__ == "__main__":
    main()