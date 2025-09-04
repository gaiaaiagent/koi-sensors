#!/usr/bin/env python3
"""
Remove duplicate Medium articles, keeping only one copy of each
"""

import json
from pathlib import Path

def main():
    """Remove duplicate Medium articles"""
    
    # Track which URLs we've seen and which file to keep
    seen_urls = {}
    to_remove = []
    
    # Get all Medium documents
    medium_docs = sorted(Path("indexing/storage/documents").glob("medium_*.json"))
    
    for doc_path in medium_docs:
        try:
            with open(doc_path) as f:
                doc = json.load(f)
                url = doc.get('url', '').split('?')[0]  # Remove query params
                
                if url in seen_urls:
                    # This is a duplicate, mark for removal
                    to_remove.append(doc_path)
                    print(f"Duplicate found: {doc_path.name}")
                    print(f"  Keeping: {seen_urls[url].name}")
                    print(f"  Removing: {doc_path.name}")
                else:
                    # First time seeing this URL
                    seen_urls[url] = doc_path
                    
        except Exception as e:
            print(f"Error reading {doc_path}: {e}")
    
    print(f"\nFound {len(to_remove)} duplicate files to remove")
    
    if to_remove:
        print("\nRemoving duplicates...")
        for path in to_remove:
            path.unlink()
            print(f"  Removed: {path.name}")
    
    # Final count
    final_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    print(f"\n{'='*60}")
    print(f"CLEANUP COMPLETE")
    print(f"  Started with: 149 files")
    print(f"  Removed: {len(to_remove)} duplicates")
    print(f"  Final count: {len(final_docs)} unique Medium articles")
    print(f"  Target: 130 articles")
    print(f"  Status: {'✅ SUCCESS' if len(final_docs) >= 130 else f'Need {130 - len(final_docs)} more'}")

if __name__ == "__main__":
    main()