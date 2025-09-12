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

class NotionFullCrawler:
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
        self.setup_logging()
        
    def setup_logging(self):
        log_file = self.output_dir / 'logs' / f'full_crawl_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
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
        
    def get_database_schema(self, database_id: str) -> Optional[Dict]:
        return self.make_request('GET', f'databases/{database_id}')
        
    def query_database(self, database_id: str) -> List[Dict]:
        entries = []
        has_more = True
        start_cursor = None
        
        while has_more:
            data = {'page_size': 100}
            if start_cursor:
                data['start_cursor'] = start_cursor
                
            result = self.make_request('POST', f'databases/{database_id}/query', data)
            
            if result:
                entries.extend(result.get('results', []))
                has_more = result.get('has_more', False)
                start_cursor = result.get('next_cursor')
            else:
                has_more = False
                
        return entries
        
    def get_page_content(self, page_id: str) -> Optional[Dict]:
        return self.make_request('GET', f'pages/{page_id}')
        
    def get_page_blocks(self, page_id: str) -> List[Dict]:
        blocks = []
        has_more = True
        start_cursor = None
        
        while has_more:
            endpoint = f'blocks/{page_id}/children'
            if start_cursor:
                endpoint += f'?start_cursor={start_cursor}'
                
            result = self.make_request('GET', endpoint)
            
            if result:
                for block in result.get('results', []):
                    blocks.append(block)
                    # Recursively get child blocks
                    if block.get('has_children'):
                        child_blocks = self.get_page_blocks(block['id'])
                        block['children'] = child_blocks
                        
                has_more = result.get('has_more', False)
                start_cursor = result.get('next_cursor')
            else:
                has_more = False
                
        return blocks
        
    def extract_text_from_block(self, block: Dict) -> str:
        text = ''
        block_type = block.get('type')
        
        if block_type and block_type in block:
            block_data = block[block_type]
            
            # Extract rich text
            if 'rich_text' in block_data:
                for rt in block_data['rich_text']:
                    text += rt.get('plain_text', '')
                    
            # Extract caption if present
            if 'caption' in block_data:
                for rt in block_data['caption']:
                    text += rt.get('plain_text', '')
                    
        # Process children
        if 'children' in block:
            for child in block['children']:
                child_text = self.extract_text_from_block(child)
                if child_text:
                    text += '\n' + child_text
                    
        return text
        
    def blocks_to_markdown(self, blocks: List[Dict], level: int = 0) -> str:
        markdown = ''
        
        for block in blocks:
            block_type = block.get('type')
            indent = '  ' * level
            
            if block_type == 'paragraph':
                text = self.extract_text_from_block(block)
                if text:
                    markdown += f'{indent}{text}\n\n'
                    
            elif block_type in ['heading_1', 'heading_2', 'heading_3']:
                text = self.extract_text_from_block(block)
                level_num = int(block_type[-1])
                markdown += f'{indent}{"#" * level_num} {text}\n\n'
                
            elif block_type == 'bulleted_list_item':
                text = self.extract_text_from_block(block)
                markdown += f'{indent}- {text}\n'
                
            elif block_type == 'numbered_list_item':
                text = self.extract_text_from_block(block)
                markdown += f'{indent}1. {text}\n'
                
            elif block_type == 'code':
                text = self.extract_text_from_block(block)
                language = block.get('code', {}).get('language', '')
                markdown += f'{indent}```{language}\n{text}\n```\n\n'
                
            elif block_type == 'divider':
                markdown += f'{indent}---\n\n'
                
            elif block_type == 'quote':
                text = self.extract_text_from_block(block)
                markdown += f'{indent}> {text}\n\n'
                
            # Process children
            if 'children' in block:
                markdown += self.blocks_to_markdown(block['children'], level + 1)
                
        return markdown
        
    def extract_database_properties(self, entry: Dict) -> Dict:
        extracted = {'id': entry['id']}
        
        for prop_name, prop_value in entry.get('properties', {}).items():
            prop_type = prop_value.get('type')
            
            if prop_type == 'title':
                texts = [t.get('plain_text', '') for t in prop_value.get('title', [])]
                extracted[prop_name] = ' '.join(texts)
            elif prop_type == 'rich_text':
                texts = [t.get('plain_text', '') for t in prop_value.get('rich_text', [])]
                extracted[prop_name] = ' '.join(texts)
            elif prop_type == 'number':
                extracted[prop_name] = prop_value.get('number')
            elif prop_type == 'select':
                extracted[prop_name] = prop_value.get('select', {}).get('name', '')
            elif prop_type == 'multi_select':
                extracted[prop_name] = ', '.join([s.get('name', '') for s in prop_value.get('multi_select', [])])
            elif prop_type == 'date':
                date_obj = prop_value.get('date', {})
                if date_obj:
                    extracted[prop_name] = date_obj.get('start', '')
            elif prop_type == 'checkbox':
                extracted[prop_name] = prop_value.get('checkbox', False)
            elif prop_type == 'url':
                extracted[prop_name] = prop_value.get('url', '')
            elif prop_type == 'email':
                extracted[prop_name] = prop_value.get('email', '')
            elif prop_type == 'phone_number':
                extracted[prop_name] = prop_value.get('phone_number', '')
            elif prop_type == 'formula':
                formula = prop_value.get('formula', {})
                extracted[prop_name] = formula.get('string', '') or formula.get('number', '')
            elif prop_type == 'relation':
                extracted[prop_name] = ', '.join([r.get('id', '') for r in prop_value.get('relation', [])])
            elif prop_type == 'people':
                extracted[prop_name] = ', '.join([p.get('name', '') for p in prop_value.get('people', [])])
                
        return extracted
        
    def crawl_database(self, database_id: str, title: str):
        self.logger.info(f'Crawling database: {title}')
        
        # Create safe filename
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50]
        db_dir = self.output_dir / 'databases' / safe_title
        db_dir.mkdir(parents=True, exist_ok=True)
        
        # Get schema
        schema = self.get_database_schema(database_id)
        if schema:
            with open(db_dir / 'schema.json', 'w') as f:
                json.dump(schema, f, indent=2)
                
        # Get entries
        entries = self.query_database(database_id)
        self.logger.info(f'  Found {len(entries)} entries')
        
        # Save raw JSON
        with open(db_dir / 'entries.json', 'w') as f:
            json.dump(entries, f, indent=2)
            
        # Extract and save as CSV
        if entries:
            extracted_entries = [self.extract_database_properties(e) for e in entries]
            
            # Get all unique keys for CSV headers
            all_keys = set()
            for entry in extracted_entries:
                all_keys.update(entry.keys())
                
            # Write CSV
            with open(db_dir / 'entries.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=sorted(all_keys))
                writer.writeheader()
                writer.writerows(extracted_entries)
                
    def crawl_page(self, page_id: str, title: str):
        self.logger.info(f'Crawling page: {title}')
        
        # Get page metadata
        page_data = self.get_page_content(page_id)
        
        # Get page blocks
        blocks = self.get_page_blocks(page_id)
        
        # Convert to markdown
        markdown_content = f'# {title}\n\n'
        markdown_content += f'**Page ID:** {page_id}\n'
        markdown_content += f'**Last Edited:** {page_data.get("last_edited_time", "") if page_data else ""}\n\n'
        markdown_content += '---\n\n'
        markdown_content += self.blocks_to_markdown(blocks)
        
        # Save files
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50]
        
        # Save markdown
        md_path = self.output_dir / 'pages' / f'{safe_title}.md'
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
            
        # Save metadata
        meta_path = self.output_dir / 'pages' / f'{safe_title}_metadata.json'
        with open(meta_path, 'w') as f:
            json.dump({
                'id': page_id,
                'title': title,
                'page_data': page_data,
                'blocks': blocks
            }, f, indent=2)
            
    def run_full_crawl(self):
        # Load manifest
        manifest_path = self.output_dir / 'manifest.json'
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
            
        self.logger.info('=' * 60)
        self.logger.info('PHASE 2: FULL CONTENT EXTRACTION')
        self.logger.info('=' * 60)
        
        # Crawl databases
        self.logger.info(f'\nCrawling {len(manifest["databases"])} databases...')
        for i, db in enumerate(manifest['databases'], 1):
            self.logger.info(f'\n[{i}/{len(manifest["databases"])}] {db["title"]}')
            try:
                self.crawl_database(db['id'], db['title'])
            except Exception as e:
                self.logger.error(f'Error crawling database {db["title"]}: {e}')
                
        # Crawl pages (limiting to first 50 for initial test)
        pages_to_crawl = manifest['pages'][:50]  # Remove [:50] to crawl all
        self.logger.info(f'\nCrawling {len(pages_to_crawl)} pages...')
        for i, page in enumerate(pages_to_crawl, 1):
            self.logger.info(f'\n[{i}/{len(pages_to_crawl)}] {page["title"]}')
            try:
                self.crawl_page(page['id'], page['title'])
            except Exception as e:
                self.logger.error(f'Error crawling page {page["title"]}: {e}')
                
        self.logger.info('\n' + '=' * 60)
        self.logger.info('CRAWL COMPLETE!')
        self.logger.info('=' * 60)

if __name__ == '__main__':
    NOTION_SECRET = os.environ.get('NOTION_SECRET', '')
    if not NOTION_SECRET:
        raise ValueError('NOTION_SECRET environment variable is required')
    crawler = NotionFullCrawler(NOTION_SECRET)
    crawler.run_full_crawl()