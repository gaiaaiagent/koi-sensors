#!/usr/bin/env python3
"""
Standalone Medium Blog Sensor for Regen Network
Can run without KOI infrastructure dependencies for testing
"""

import asyncio
import aiohttp
import hashlib
import feedparser
import re
import json
from typing import Dict, List, Set, Optional
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import html2text


class StandaloneMediumSensor:
    """Standalone Medium sensor for testing without KOI dependencies"""
    
    def __init__(self):
        self.medium_url = "https://regen-network.medium.com"
        self.rss_url = "https://medium.com/feed/@regen-network"
        self.collected_articles = []
        self.session = None
        
        # Content converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        self.html_converter.ignore_images = True
        self.html_converter.body_width = 0
    
    async def collect_articles(self, limit: int = 10) -> List[Dict]:
        """Collect Medium articles"""
        print(f"[INFO] Starting Medium article collection from {self.medium_url}")
        
        # Initialize session
        self.session = aiohttp.ClientSession(
            headers={'User-Agent': 'Mozilla/5.0 (compatible; KOI-Sensor/1.0)'}
        )
        
        try:
            # Collect from RSS first
            print("[INFO] Fetching RSS feed...")
            article_urls = await self.collect_from_rss()
            print(f"[INFO] Found {len(article_urls)} articles from RSS")
            
            # If RSS fails or returns nothing, try scraping
            if not article_urls:
                print("[INFO] RSS empty, trying web scraping...")
                article_urls = await self.scrape_for_articles()
                print(f"[INFO] Found {len(article_urls)} articles from scraping")
            
            # Process articles up to limit
            article_urls = list(article_urls)[:limit]
            
            for i, url in enumerate(article_urls, 1):
                print(f"[INFO] Processing article {i}/{len(article_urls)}: {url}")
                article = await self.process_article(url)
                if article:
                    self.collected_articles.append(article)
                
                # Small delay between requests
                await asyncio.sleep(1)
            
            print(f"[SUCCESS] Collected {len(self.collected_articles)} articles")
            
        finally:
            await self.session.close()
        
        return self.collected_articles
    
    async def collect_from_rss(self) -> Set[str]:
        """Collect article URLs from RSS feed"""
        article_urls = set()
        
        try:
            async with self.session.get(self.rss_url) as response:
                if response.status == 200:
                    rss_content = await response.text()
                    feed = feedparser.parse(rss_content)
                    
                    for entry in feed.entries:
                        if hasattr(entry, 'link'):
                            url = entry.link
                            # Clean Medium redirect URLs
                            if '?source=rss' in url:
                                url = url.split('?source=rss')[0]
                            article_urls.add(url)
                            
                            # Also extract metadata from RSS
                            print(f"  - {entry.get('title', 'No title')}")
        
        except Exception as e:
            print(f"[ERROR] RSS fetch failed: {e}")
        
        return article_urls
    
    async def scrape_for_articles(self) -> Set[str]:
        """Scrape Medium page for article URLs"""
        article_urls = set()
        
        # Try multiple endpoints
        endpoints = [
            self.medium_url,
            f"{self.medium_url}/archive",
            f"{self.medium_url}/latest"
        ]
        
        for endpoint in endpoints:
            try:
                print(f"[INFO] Trying endpoint: {endpoint}")
                async with self.session.get(endpoint) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for article links
                        links = soup.find_all('a', href=True)
                        for link in links:
                            href = link.get('href', '')
                            if href:
                                full_url = urljoin(self.medium_url, href)
                                if self._is_article_url(full_url):
                                    article_urls.add(full_url)
                        
                        # Extract from JavaScript
                        post_ids = re.findall(r'"postId":"([a-f0-9]+)"', html)
                        for post_id in post_ids:
                            article_urls.add(f"https://medium.com/p/{post_id}")
                        
                        if article_urls:
                            break  # Found articles, stop trying endpoints
            
            except Exception as e:
                print(f"[WARNING] Failed to scrape {endpoint}: {e}")
        
        return article_urls
    
    def _is_article_url(self, url: str) -> bool:
        """Check if URL is likely an article"""
        excluded = ['/about', '/archive', '/tag/', '/signin', '/signup']
        path = urlparse(url).path.lower()
        
        if any(ex in path for ex in excluded):
            return False
        
        # Check positive patterns
        if re.search(r'-[a-f0-9]{8,}$', path):  # Article ID
            return True
        if '/p/' in path:  # Medium pattern
            return True
        
        return False
    
    async def process_article(self, url: str) -> Optional[Dict]:
        """Process a single article"""
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    print(f"[WARNING] HTTP {response.status} for {url}")
                    return None
                
                html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract article data
            article = {
                "url": url,
                "title": "",
                "author": "",
                "content": "",
                "published_date": "",
                "tags": [],
                "word_count": 0,
                "rid": f"orn:medium.article.{hashlib.sha256(url.encode()).hexdigest()[:16]}"
            }
            
            # Title
            title_elem = soup.find('h1') or soup.find('title')
            if title_elem:
                article["title"] = title_elem.get_text().strip()
            
            # Author
            author_meta = soup.find('meta', {'name': 'author'})
            if author_meta:
                article["author"] = author_meta.get('content', '')
            
            # Published date
            time_elem = soup.find('time')
            if time_elem:
                article["published_date"] = time_elem.get('datetime', '')
            
            # Tags
            for tag_link in soup.find_all('a', href=re.compile('/tag/')):
                tag = tag_link.get_text().strip()
                if tag:
                    article["tags"].append(tag)
            
            # Content
            article_elem = soup.find('article') or soup.find('main')
            if article_elem:
                # Clean up
                for elem in article_elem.find_all(['script', 'style', 'nav', 'footer']):
                    elem.decompose()
                
                # Convert to text
                text = self.html_converter.handle(str(article_elem))
                text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text).strip()
                article["content"] = text
                article["word_count"] = len(text.split())
            
            # Auto-tag based on content
            if article["content"]:
                content_lower = article["content"].lower()
                if "governance" in content_lower:
                    article["tags"].append("governance")
                if "ecocredit" in content_lower or "carbon" in content_lower:
                    article["tags"].append("ecocredits")
                if "marketplace" in content_lower:
                    article["tags"].append("marketplace")
                if "climate" in content_lower:
                    article["tags"].append("climate")
            
            print(f"[SUCCESS] Processed: {article['title'][:50]}... ({article['word_count']} words)")
            return article
        
        except Exception as e:
            print(f"[ERROR] Failed to process {url}: {e}")
            return None
    
    def save_to_file(self, filename: str = "medium_articles.json"):
        """Save collected articles to JSON file"""
        with open(filename, 'w') as f:
            json.dump(self.collected_articles, f, indent=2, default=str)
        print(f"[INFO] Saved {len(self.collected_articles)} articles to {filename}")
    
    def print_summary(self):
        """Print summary of collected articles"""
        print("\n" + "="*60)
        print("COLLECTION SUMMARY")
        print("="*60)
        print(f"Total articles collected: {len(self.collected_articles)}")
        
        if self.collected_articles:
            print("\nArticles:")
            for i, article in enumerate(self.collected_articles, 1):
                print(f"\n{i}. {article['title'][:60]}...")
                print(f"   Author: {article['author']}")
                print(f"   Date: {article['published_date'][:10] if article['published_date'] else 'Unknown'}")
                print(f"   Words: {article['word_count']}")
                print(f"   Tags: {', '.join(article['tags']) if article['tags'] else 'None'}")
                print(f"   RID: {article['rid']}")
        
        # Calculate stats
        total_words = sum(a['word_count'] for a in self.collected_articles)
        all_tags = set()
        for article in self.collected_articles:
            all_tags.update(article['tags'])
        
        print(f"\nTotal word count: {total_words:,}")
        print(f"Unique tags: {', '.join(sorted(all_tags)) if all_tags else 'None'}")


async def main():
    """Run standalone Medium sensor"""
    print("="*60)
    print("MEDIUM BLOG SENSOR - STANDALONE MODE")
    print("="*60)
    print(f"Target: https://regen-network.medium.com")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60 + "\n")
    
    sensor = StandaloneMediumSensor()
    
    # Collect articles (limit to 5 for testing)
    await sensor.collect_articles(limit=5)
    
    # Print summary
    sensor.print_summary()
    
    # Save to file
    sensor.save_to_file("medium_articles_test.json")
    
    print("\n[COMPLETE] Medium sensor test finished")


if __name__ == "__main__":
    # Install required packages if missing
    import subprocess
    import sys
    
    required = ['aiohttp', 'beautifulsoup4', 'html2text', 'feedparser']
    
    for package in required:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    # Run the sensor
    asyncio.run(main())