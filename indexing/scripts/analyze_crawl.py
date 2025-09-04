#!/usr/bin/env python3
"""
Analyze the crawled Notion data and create a comprehensive report
"""
import json
import os
from datetime import datetime
import csv

def analyze_crawl(crawl_dir='notion_crawl'):
    crawl_path = Path(crawl_dir)
    
    print("=" * 60)
    print("NOTION CRAWL ANALYSIS REPORT")
    print("=" * 60)
    print(f"Analysis Date: {datetime.now().isoformat()}\n")
    
    # Load manifest
    manifest_path = crawl_path / 'manifest.json'
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        print(f"Manifest Created: {manifest['crawl_date']}")
        print(f"Total Pages Discovered: {manifest['total_pages']}")
        print(f"Total Databases Discovered: {manifest['total_databases']}\n")
    
    # Analyze databases
    print("=" * 60)
    print("DATABASE ANALYSIS")
    print("=" * 60)
    
    db_dir = crawl_path / 'databases'
    if db_dir.exists():
        db_folders = [d for d in db_dir.iterdir() if d.is_dir()]
        print(f"Databases Extracted: {len(db_folders)}\n")
        
        for db_folder in sorted(db_folders):
            print(f"\n📊 {db_folder.name}")
            print("-" * 40)
            
            # Check for files
            entries_json = db_folder / 'entries.json'
            schema_json = db_folder / 'schema.json'
            entries_csv = db_folder / 'entries.csv'
            
            if entries_json.exists():
                with open(entries_json, 'r') as f:
                    entries = json.load(f)
                print(f"  Entries: {len(entries)}")
                
            if schema_json.exists():
                with open(schema_json, 'r') as f:
                    schema = json.load(f)
                if 'properties' in schema:
                    print(f"  Properties: {len(schema['properties'])}")
                    print(f"  Property Names: {', '.join(list(schema['properties'].keys())[:5])}...")
                    
            if entries_csv.exists():
                print(f"  CSV Export: ✅")
            else:
                print(f"  CSV Export: ❌ (may have failed)")
    
    # Analyze pages
    print("\n" + "=" * 60)
    print("PAGE EXTRACTION ANALYSIS")
    print("=" * 60)
    
    pages_dir = crawl_path / 'pages'
    if pages_dir.exists():
        md_files = list(pages_dir.glob('*.md'))
        json_files = list(pages_dir.glob('*_metadata.json'))
        
        print(f"Pages Extracted: {len(md_files)}")
        print(f"Metadata Files: {len(json_files)}")
        
        # Sample content analysis
        if md_files:
            print("\n📄 Sample Page Content (first 5):")
            print("-" * 40)
            for md_file in sorted(md_files)[:5]:
                file_size = md_file.stat().st_size
                print(f"  • {md_file.name} ({file_size:,} bytes)")
                
                # Read first few lines
                with open(md_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:5]
                    for line in lines:
                        if line.strip() and not line.startswith('**'):
                            print(f"    → {line.strip()[:80]}...")
                            break
    
    # Extraction progress
    print("\n" + "=" * 60)
    print("EXTRACTION PROGRESS")
    print("=" * 60)
    
    if manifest_path.exists():
        total_expected = manifest['total_pages'] + manifest['total_databases']
        total_extracted = len(md_files) + len(db_folders)
        progress = (total_extracted / total_expected) * 100 if total_expected > 0 else 0
        
        print(f"Expected Items: {total_expected}")
        print(f"Extracted Items: {total_extracted}")
        print(f"Progress: {progress:.1f}%")
        
        if progress < 100:
            print(f"\n⚠️  Extraction still in progress...")
            print(f"   Remaining: {total_expected - total_extracted} items")
    
    # Logs analysis
    print("\n" + "=" * 60)
    print("LOG FILES")
    print("=" * 60)
    
    logs_dir = crawl_path / 'logs'
    if logs_dir.exists():
        log_files = list(logs_dir.glob('*.log'))
        print(f"Log Files: {len(log_files)}")
        for log_file in sorted(log_files)[-3:]:  # Show last 3 logs
            file_size = log_file.stat().st_size
            print(f"  • {log_file.name} ({file_size:,} bytes)")
    
    # Key content categories
    print("\n" + "=" * 60)
    print("KEY CONTENT DISCOVERED")
    print("=" * 60)
    
    if manifest_path.exists():
        # Look for KOI-related content
        koi_pages = [p for p in manifest['pages'] if 'KOI' in p.get('title', '').upper() or 'koi' in p.get('url', '')]
        print(f"\n🔍 KOI-Related Pages: {len(koi_pages)}")
        
        # Look for PRP/Podcast content
        podcast_pages = [p for p in manifest['pages'] if 'PRP' in p.get('title', '').upper() or 'podcast' in p.get('title', '').lower()]
        print(f"🎙️  Podcast Pages: {len(podcast_pages)}")
        
        # Recent content (last 30 days)
        from datetime import datetime, timedelta
        recent_date = datetime.now() - timedelta(days=30)
        recent_pages = [p for p in manifest['pages'] 
                       if p.get('last_edited') and 
                       datetime.fromisoformat(p['last_edited'].replace('Z', '+00:00')) > recent_date]
        print(f"📅 Recently Updated (30 days): {len(recent_pages)}")
    
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"\nData Location: {os.path.abspath(crawl_dir)}")
    print("\nNext Steps:")
    print("1. Wait for crawl to complete if still running")
    print("2. Review extracted markdown files in 'pages' directory")
    print("3. Analyze database CSVs for structured data")
    print("4. Use content for knowledge base indexing")

if __name__ == '__main__':
    analyze_crawl()