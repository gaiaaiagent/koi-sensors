#!/usr/bin/env python3
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

def analyze_crawl(crawl_dir='notion_crawl'):
    crawl_path = Path(crawl_dir)
    
    print('=' * 60)
    print('NOTION CRAWL ANALYSIS REPORT')
    print('=' * 60)
    print(f'Analysis Date: {datetime.now().isoformat()}\n')
    
    # Load manifest
    manifest_path = crawl_path / 'manifest.json'
    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        print(f"Manifest Created: {manifest['crawl_date']}")
        print(f"Total Pages Discovered: {manifest['total_pages']}")
        print(f"Total Databases Discovered: {manifest['total_databases']}\n")
    
    # Analyze databases
    print('=' * 60)
    print('DATABASE ANALYSIS')
    print('=' * 60)
    
    db_dir = crawl_path / 'databases'
    if db_dir.exists():
        db_folders = [d for d in db_dir.iterdir() if d.is_dir()]
        print(f'Databases Extracted: {len(db_folders)}\n')
        
        for db_folder in sorted(db_folders)[:5]:  # Show first 5
            print(f'\nDatabase: {db_folder.name}')
            print('-' * 40)
            
            entries_json = db_folder / 'entries.json'
            if entries_json.exists():
                with open(entries_json, 'r') as f:
                    entries = json.load(f)
                print(f'  Entries: {len(entries)}')
    
    # Analyze pages
    print('\n' + '=' * 60)
    print('PAGE EXTRACTION ANALYSIS')
    print('=' * 60)
    
    pages_dir = crawl_path / 'pages'
    if pages_dir.exists():
        md_files = list(pages_dir.glob('*.md'))
        print(f'Pages Extracted: {len(md_files)}')
        
        if manifest_path.exists():
            progress = (len(md_files) / manifest['total_pages']) * 100
            print(f'Progress: {progress:.1f}% of {manifest["total_pages"]} pages')
    
    print('\n' + '=' * 60)
    print('ANALYSIS COMPLETE')
    print('=' * 60)
    print(f'\nData Location: {os.path.abspath(crawl_dir)}')

if __name__ == '__main__':
    analyze_crawl()
