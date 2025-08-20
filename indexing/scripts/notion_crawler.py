#!/usr/bin/env python3
import os
import json
import csv
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
import requests
from pathlib import Path
import re

class NotionCrawler:
    def __init__(self, secret: str, output_dir: str = 'notion_crawl'):
        self.secret = secret
        self.base_url = 'https://api.notion.com/v1'
        self.headers = {
            'Authorization': f'Bearer {secret}',
            'Notion-Version': '2022-06-28',
            'Content-Type': 'application/json'
        }
        self.output_dir = Path(output_dir)
        self.rate_limit_delay = 0.35
        self.setup_directories()
        self.setup_logging()
        self.manifest = {
            'crawl_date': datetime.now().isoformat(),
            'pages': [],
            'databases': [],
            'total_pages': 0,
            'total_databases': 0
        }
        
    def setup_directories(self):
        dirs = [
            self.output_dir,
            self.output_dir / 'databases',
            self.output_dir / 'pages',
            self.output_dir / 'logs'
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            
    def setup_logging(self):
        log_file = self.output_dir / 'logs' / f'crawl_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, max_retries: int = 3) -> Optional[Dict]:
        url = f'{self.base_url}/{endpoint}'
        
        for attempt in range(max_retries):
            try:
                time.sleep(self.rate_limit_delay)
                
                if method == 'GET':
                    response = requests.get(url, headers=self.headers)
                elif method == 'POST':
                    response = requests.post(url, headers=self.headers, json=data or {})
                else:
                    raise ValueError(f'Unsupported method: {method}')
                    
                self.logger.debug(f'{method} {endpoint} - Status: {response.status_code}')
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 5))
                    self.logger.warning(f'Rate limited. Waiting {retry_after} seconds...')
                    time.sleep(retry_after)
                else:
                    self.logger.error(f'Error {response.status_code}: {response.text}')
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        
            except Exception as e:
                self.logger.error(f'Request failed: {e}')
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
        return None
        
    def search_all_content(self) -> Dict[str, List]:
        self.logger.info('Starting content discovery...')
        
        all_pages = []
        all_databases = []
        
        has_more = True
        start_cursor = None
        
        while has_more:
            data = {'page_size': 100}
            if start_cursor:
                data['start_cursor'] = start_cursor
                
            result = self.make_request('POST', 'search', data)
            
            if result:
                for item in result.get('results', []):
                    if item['object'] == 'page':
                        all_pages.append({
                            'id': item['id'],
                            'title': self.get_title(item),
                            'url': item.get('url', ''),
                            'last_edited': item.get('last_edited_time', ''),
                            'created': item.get('created_time', '')
                        })
                    elif item['object'] == 'database':
                        all_databases.append({
                            'id': item['id'],
                            'title': self.get_title(item),
                            'url': item.get('url', ''),
                            'last_edited': item.get('last_edited_time', ''),
                            'created': item.get('created_time', '')
                        })
                        
                has_more = result.get('has_more', False)
                start_cursor = result.get('next_cursor')
            else:
                has_more = False
                
        self.logger.info(f'Discovered {len(all_pages)} pages and {len(all_databases)} databases')
        
        self.manifest['pages'] = all_pages
        self.manifest['databases'] = all_databases
        self.manifest['total_pages'] = len(all_pages)
        self.manifest['total_databases'] = len(all_databases)
        
        return {'pages': all_pages, 'databases': all_databases}
        
    def get_title(self, item: Dict) -> str:
        if 'title' in item:
            if isinstance(item['title'], list) and item['title']:
                return item['title'][0].get('plain_text', 'Untitled')
            return 'Untitled'
        elif 'properties' in item:
            for prop_name in ['title', 'Title', 'Name', 'name']:
                if prop_name in item['properties']:
                    prop = item['properties'][prop_name]
                    if prop['type'] == 'title' and prop.get('title'):
                        return prop['title'][0].get('plain_text', 'Untitled')
            return 'Untitled'
        return 'Untitled'
        
    def save_discovery_report(self, content: Dict):
        manifest_path = self.output_dir / 'manifest.json'
        with open(manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
            
        report_path = self.output_dir / 'discovery_report.md'
        with open(report_path, 'w') as f:
            f.write('# Notion Workspace Discovery Report\n\n')
            f.write(f'**Crawl Date:** {self.manifest["crawl_date"]}\n\n')
            f.write(f'## Summary\n\n')
            f.write(f'- **Total Pages:** {len(content["pages"])}\n')
            f.write(f'- **Total Databases:** {len(content["databases"])}\n\n')
            
            f.write('## Databases\n\n')
            for db in content['databases']:
                f.write(f'- **{db["title"]}**\n')
                f.write(f'  - ID: {db["id"]}\n')
                f.write(f'  - URL: {db["url"]}\n')
                f.write(f'  - Last edited: {db["last_edited"]}\n\n')
                
            f.write('## Pages\n\n')
            for page in content['pages'][:50]:
                f.write(f'- **{page["title"]}**\n')
                f.write(f'  - ID: {page["id"]}\n')
                f.write(f'  - URL: {page["url"]}\n')
                f.write(f'  - Last edited: {page["last_edited"]}\n\n')
                
            if len(content['pages']) > 50:
                f.write(f'\n*... and {len(content["pages"]) - 50} more pages*\n')
                
        self.logger.info(f'Discovery report saved to {report_path}')
        
    def run_discovery(self):
        self.logger.info('=' * 60)
        self.logger.info('PHASE 1: DISCOVERY')
        self.logger.info('=' * 60)
        
        content = self.search_all_content()
        self.save_discovery_report(content)
        
        self.logger.info('Discovery phase complete!')
        self.logger.info(f'Results saved to {self.output_dir}')
        
        return content

if __name__ == '__main__':
    NOTION_SECRET = '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'
    crawler = NotionCrawler(NOTION_SECRET)
    content = crawler.run_discovery()
    
    print('\n' + '=' * 60)
    print('DISCOVERY COMPLETE')
    print('=' * 60)
    print(f'Found {len(content["pages"])} pages and {len(content["databases"])} databases')
    print(f'Check {crawler.output_dir} for detailed results')
