#!/usr/bin/env python3
"""
Complete Notion crawl for all 729 pages
Runs in batches to avoid timeouts
"""
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
import sys

class NotionCompleteCrawler:
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
        log_file = self.output_dir / 'logs' / f'complete_crawl_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
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
                    self.logger.error(f'Error {response.status_code}: {response.text[:200]}')
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        
            except Exception as e:
                self.logger.error(f'Request failed: {e}')
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
        return None
        
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
                    # Skip recursive child blocks for speed
                    
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
                    
        return text
        
    def blocks_to_markdown(self, blocks: List[Dict]) -> str:
        markdown = ''
        
        for block in blocks:
            block_type = block.get('type')
            
            if block_type == 'paragraph':
                text = self.extract_text_from_block(block)
                if text:
                    markdown += f'{text}\n\n'
                    
            elif block_type in ['heading_1', 'heading_2', 'heading_3']:
                text = self.extract_text_from_block(block)
                level_num = int(block_type[-1])
                markdown += f'{"#" * level_num} {text}\n\n'
                
            elif block_type == 'bulleted_list_item':
                text = self.extract_text_from_block(block)
                markdown += f'- {text}\n'
                
            elif block_type == 'numbered_list_item':
                text = self.extract_text_from_block(block)
                markdown += f'1. {text}\n'
                
            elif block_type == 'code':
                text = self.extract_text_from_block(block)
                language = block.get('code', {}).get('language', '')
                markdown += f'```{language}\n{text}\n```\n\n'
                
            elif block_type == 'divider':
                markdown += '---\n\n'
                
            elif block_type == 'quote':
                text = self.extract_text_from_block(block)
                markdown += f'> {text}\n\n'
                
        return markdown
        
    def crawl_page_batch(self, pages: List[Dict], batch_name: str):
        """Crawl a batch of pages"""
        self.logger.info(f'\nCrawling batch: {batch_name}')
        
        for i, page in enumerate(pages, 1):
            try:
                self.logger.info(f'[{i}/{len(pages)}] {page["title"]}')
                
                # Get page blocks
                blocks = self.get_page_blocks(page['id'])
                
                # Convert to markdown
                markdown_content = f'# {page["title"]}\n\n'
                markdown_content += f'**Page ID:** {page["id"]}\n'
                markdown_content += f'**URL:** {page.get("url", "")}\n'
                markdown_content += f'**Last Edited:** {page.get("last_edited", "")}\n\n'
                markdown_content += '---\n\n'
                markdown_content += self.blocks_to_markdown(blocks)
                
                # Save files
                safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', page["title"])[:50]
                safe_title = f'{safe_title}_{page["id"][:8]}'  # Add ID prefix to avoid duplicates
                
                # Save markdown
                md_path = self.output_dir / 'pages' / f'{safe_title}.md'
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                    
            except Exception as e:
                self.logger.error(f'Error crawling page {page["title"]}: {e}')
                
    def run_complete_crawl(self):
        # Load manifest
        manifest_path = self.output_dir / 'manifest.json'
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
            
        self.logger.info('=' * 60)
        self.logger.info('COMPLETE PAGE EXTRACTION')
        self.logger.info('=' * 60)
        
        all_pages = manifest['pages']
        self.logger.info(f'Total pages to crawl: {len(all_pages)}')
        
        # Process in batches
        batch_size = 50
        for start_idx in range(0, len(all_pages), batch_size):
            end_idx = min(start_idx + batch_size, len(all_pages))
            batch = all_pages[start_idx:end_idx]
            batch_name = f'Pages {start_idx+1}-{end_idx} of {len(all_pages)}'
            
            self.crawl_page_batch(batch, batch_name)
            
            # Progress update
            self.logger.info(f'Progress: {end_idx}/{len(all_pages)} pages completed')
            
            # Small break between batches
            if end_idx < len(all_pages):
                time.sleep(2)
                
        self.logger.info('\n' + '=' * 60)
        self.logger.info('COMPLETE CRAWL FINISHED!')
        self.logger.info(f'Total pages processed: {len(all_pages)}')
        self.logger.info('=' * 60)
        
        # Create summary report
        self.create_summary_report()
        
    def create_summary_report(self):
        """Create a summary report of the crawl"""
        report_path = self.output_dir / 'crawl_summary.md'
        
        # Count files
        pages_dir = self.output_dir / 'pages'
        db_dir = self.output_dir / 'databases'
        
        page_files = list(pages_dir.glob('*.md'))
        db_folders = [d for d in db_dir.iterdir() if d.is_dir()]
        
        with open(report_path, 'w') as f:
            f.write('# Notion Crawl Summary Report\n\n')
            f.write(f'**Completed:** {datetime.now().isoformat()}\n\n')
            f.write('## Statistics\n\n')
            f.write(f'- **Pages extracted:** {len(page_files)}\n')
            f.write(f'- **Databases extracted:** {len(db_folders)}\n')
            f.write(f'- **Total content items:** {len(page_files) + len(db_folders)}\n\n')
            
            f.write('## Databases\n\n')
            for db_folder in sorted(db_folders):
                f.write(f'- {db_folder.name}\n')
                
            f.write(f'\n## Sample Pages (first 20)\n\n')
            for page_file in sorted(page_files)[:20]:
                f.write(f'- {page_file.name}\n')
                
        self.logger.info(f'Summary report saved to {report_path}')

if __name__ == '__main__':
    NOTION_SECRET = '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'
    
    # Check if we want to continue from a specific batch
    start_from = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    
    crawler = NotionCompleteCrawler(NOTION_SECRET)
    crawler.run_complete_crawl()