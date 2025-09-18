#!/usr/bin/env python3
"""
Twitter Sensor for KOI System with Full KOI Integration
Uses Playwright browser automation to collect tweets without API keys
Sends collected tweets to KOI coordinator for processing
"""

import asyncio
import json
import hashlib
import re
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import quote
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle

try:
    from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Playwright not installed. Installing...")
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.run(["playwright", "install", "chromium"])
    from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


class TwitterKOISensor:
    """
    Twitter sensor using Playwright browser automation with KOI integration
    Works without API authentication by scraping the public Twitter interface
    """
    
    def __init__(self):
        """Initialize Twitter sensor with KOI integration"""
        self.headless = True  # Run browser in headless mode
        self.browser = None
        self.context = None
        self.page = None

        # Twitter accounts to monitor - read from environment or use defaults
        env_accounts = os.getenv("TWITTER_ACCOUNTS", "")
        if env_accounts:
            self.accounts = [acc.strip() for acc in env_accounts.split(",")]
        else:
            self.accounts = [
                "regen_network",
                "RegenFoundation",
                "RegenProposed",
                "RNDRegistry"
            ]

        # Search queries for relevant content - read from environment or use defaults
        env_hashtags = os.getenv("TWITTER_HASHTAGS", "")
        if env_hashtags:
            # Convert hashtags to search queries
            self.search_queries = [tag.strip() for tag in env_hashtags.split(",")]
            # Add some default search queries
            self.search_queries.extend([
                "regen network",
                "regen registry",
                "carbon credits blockchain"
            ])
        else:
            self.search_queries = [
                "regen network",
                "regen registry",
                "#RegenNetwork",
                "carbon credits blockchain",
                "eco credits"
            ]
        
        # Initialize KOI node for sending events
        self.koi_node = KOIPartialNode(
            node_name="twitter-sensor",
            coordinator_url="http://localhost:8005"
        )
        
        # Cache for avoiding duplicates
        self.processed_tweets = set()
        self.output_dir = Path(__file__).parent / 'output'
        self.output_dir.mkdir(exist_ok=True)
        
        # Rate limiting settings
        self.min_delay = 3  # Minimum seconds between requests
        self.max_delay = 7  # Maximum seconds between requests
    
    def generate_rid(self, content: str) -> str:
        """Generate RID for content using SHA-256 hash"""
        hash_obj = hashlib.sha256(content.encode('utf-8'))
        return hash_obj.hexdigest()[:16]

    async def send_heartbeat_event(self, response_to: str = None):
        """Send a heartbeat event to register with coordinator"""
        try:
            # Create a heartbeat data
            heartbeat_data = {
                "type": "sensor_heartbeat",
                "sensor": "twitter",
                "node_id": "twitter-sensor",
                "timestamp": datetime.now().isoformat(),
                "status": "active",
                "monitoring": self.accounts + [f"search:{q}" for q in self.search_queries],
                "tweets_processed": len(self.processed_tweets)
            }

            # Add response_to if this is a ping response
            if response_to:
                heartbeat_data["response_to"] = response_to

            # Create document for heartbeat
            heartbeat_doc = {
                'id': f"twitter_heartbeat_{int(datetime.now().timestamp())}",
                'title': 'Twitter Sensor Heartbeat',
                'url': '',
                'type': 'heartbeat',
                'timestamp': datetime.now().isoformat(),
                'content': json.dumps(heartbeat_data),
                'metadata': {
                    'sensor_type': 'twitter',
                    'sensor_id': 'twitter-sensor',
                    'event_type': 'HEARTBEAT'
                }
            }

            # Convert to bundle and emit
            bundle = document_to_bundle(heartbeat_doc)
            await self.koi_node.emit_new_event(bundle)

            if not response_to:
                print(f"💓 Sent heartbeat event to coordinator")
            else:
                print(f"📡 Responded to ping request {response_to}")

        except Exception as e:
            print(f"❌ Error sending heartbeat: {e}")

    async def send_periodic_heartbeats(self):
        """Send periodic heartbeats to stay registered"""
        while True:
            await asyncio.sleep(1800)  # Send heartbeat every 30 minutes
            await self.send_heartbeat_event()

    async def initialize_browser(self):
        """Initialize Playwright browser and context"""
        try:
            print("🌐 Initializing browser...")
            
            self.playwright = await async_playwright().start()
            
            # Launch browser with anti-detection settings
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process'
                ]
            )
            
            # Create context with realistic settings
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York'
            )
            
            # Create page
            self.page = await self.context.new_page()
            
            print("✅ Browser initialized successfully")
            
        except Exception as e:
            print(f"❌ Failed to initialize browser: {e}")
            # Try to install Playwright if not installed
            try:
                import subprocess
                print("📦 Installing Playwright browsers...")
                result = subprocess.run(
                    ["playwright", "install", "chromium"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print("✅ Playwright installed, retrying...")
                    # Retry initialization
                    await self.initialize_browser()
                else:
                    raise Exception(f"Failed to install Playwright: {result.stderr}")
            except Exception as install_error:
                print(f"❌ Could not install Playwright: {install_error}")
                raise
    
    async def close_browser(self):
        """Close browser and cleanup resources"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def wait_and_scroll(self, page: Page):
        """Wait for content to load and scroll to load more tweets"""
        # Wait for tweets to load
        try:
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
        except PlaywrightTimeout:
            print("⚠️  No tweets found on page")
            return
        
        # Scroll to load more tweets
        previous_height = 0
        for i in range(3):  # Scroll 3 times to load more content
            current_height = await page.evaluate('document.body.scrollHeight')
            if current_height == previous_height:
                break
            
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)  # Wait for new content to load
            previous_height = current_height
    
    async def extract_tweet_data(self, tweet_element) -> Optional[Dict[str, Any]]:
        """Extract data from a tweet element"""
        try:
            tweet_data = {}
            
            # Extract tweet text
            text_element = await tweet_element.query_selector('[data-testid="tweetText"]')
            if text_element:
                tweet_data['text'] = await text_element.inner_text()
            
            # Extract timestamp
            time_element = await tweet_element.query_selector('time')
            if time_element:
                tweet_data['created_at'] = await time_element.get_attribute('datetime')
            
            # Extract metrics (likes, retweets, replies)
            metrics = {}
            
            # Like count
            like_element = await tweet_element.query_selector('[data-testid="like"] span')
            if like_element:
                like_text = await like_element.inner_text()
                metrics['likes'] = self.parse_count(like_text)
            
            # Retweet count
            retweet_element = await tweet_element.query_selector('[data-testid="retweet"] span')
            if retweet_element:
                retweet_text = await retweet_element.inner_text()
                metrics['retweets'] = self.parse_count(retweet_text)
            
            # Reply count
            reply_element = await tweet_element.query_selector('[data-testid="reply"] span')
            if reply_element:
                reply_text = await reply_element.inner_text()
                metrics['replies'] = self.parse_count(reply_text)
            
            tweet_data['metrics'] = metrics
            
            # Extract user info
            user_element = await tweet_element.query_selector('[data-testid="User-Name"]')
            if user_element:
                user_text = await user_element.inner_text()
                # Parse username and display name
                parts = user_text.split('\n')
                if parts:
                    tweet_data['author_name'] = parts[0]
                    if len(parts) > 1 and parts[1].startswith('@'):
                        tweet_data['author_username'] = parts[1][1:]  # Remove @
            
            # Extract tweet URL and ID
            link_elements = await tweet_element.query_selector_all('a[href*="/status/"]')
            for link in link_elements:
                href = await link.get_attribute('href')
                if '/status/' in href:
                    tweet_data['url'] = f"https://twitter.com{href}"
                    # Extract tweet ID from URL
                    match = re.search(r'/status/(\d+)', href)
                    if match:
                        tweet_data['id'] = match.group(1)
                    break
            
            return tweet_data if tweet_data.get('text') else None
            
        except Exception as e:
            print(f"❌ Error extracting tweet data: {e}")
            return None
    
    def parse_count(self, text: str) -> int:
        """Parse count from text (e.g., "1.2K" -> 1200)"""
        if not text:
            return 0
        
        text = text.strip().upper()
        if 'K' in text:
            return int(float(text.replace('K', '')) * 1000)
        elif 'M' in text:
            return int(float(text.replace('M', '')) * 1000000)
        else:
            try:
                return int(text)
            except:
                return 0
    
    async def scrape_user_timeline(self, username: str, max_tweets: int = 10) -> List[Dict]:
        """Scrape tweets from a user's timeline with retry logic"""
        tweets = []
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Navigate to user profile
                url = f"https://twitter.com/{username}"
                print(f"   📍 Navigating to {url} (attempt {attempt + 1}/{max_retries})")
                await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)

                # Wait a bit for dynamic content
                await asyncio.sleep(3)

                # Wait and scroll to load tweets
                await self.wait_and_scroll(self.page)

                # Extract tweets
                tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')

                for element in tweet_elements[:max_tweets]:
                    tweet_data = await self.extract_tweet_data(element)
                    if tweet_data:
                        tweet_data['source_type'] = 'timeline'
                        tweet_data['source_user'] = username
                        tweets.append(tweet_data)

                if tweets:
                    print(f"   ✅ Collected {len(tweets)} tweets from @{username}")
                    break
                elif attempt < max_retries - 1:
                    print(f"   ⚠️ No tweets found, retrying...")
                    await asyncio.sleep(5)

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ Error on attempt {attempt + 1}, retrying: {e}")
                    await asyncio.sleep(5)
                else:
                    print(f"   ❌ Error scraping @{username} after {max_retries} attempts: {e}")

        return tweets
    
    async def scrape_search(self, query: str, max_tweets: int = 10) -> List[Dict]:
        """Scrape tweets from search results with retry logic"""
        tweets = []
        max_retries = 2

        for attempt in range(max_retries):
            try:
                # Build search URL
                encoded_query = quote(query)
                url = f"https://twitter.com/search?q={encoded_query}&src=typed_query&f=live"
                print(f"   🔍 Searching for: {query} (attempt {attempt + 1}/{max_retries})")
                await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)

                # Wait a bit for dynamic content
                await asyncio.sleep(3)

                # Wait and scroll to load tweets
                await self.wait_and_scroll(self.page)

                # Extract tweets
                tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')

                for element in tweet_elements[:max_tweets]:
                    tweet_data = await self.extract_tweet_data(element)
                    if tweet_data:
                        tweet_data['source_type'] = 'search'
                        tweet_data['search_query'] = query
                        tweets.append(tweet_data)

                if tweets:
                    print(f"   ✅ Found {len(tweets)} tweets for query: {query}")
                    break
                elif attempt < max_retries - 1:
                    print(f"   ⚠️ No tweets found, retrying...")
                    await asyncio.sleep(5)

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️ Error on attempt {attempt + 1}, retrying: {e}")
                    await asyncio.sleep(5)
                else:
                    print(f"   ❌ Error searching for '{query}' after {max_retries} attempts: {e}")

        return tweets
    
    def process_tweet_to_document(self, tweet: Dict) -> Optional[Dict]:
        """Convert tweet data to KOI document format"""
        # Skip if already processed
        tweet_id = tweet.get('id')
        if not tweet_id or tweet_id in self.processed_tweets:
            return None
        
        # Generate RID
        rid = f"orn:twitter.tweet.{self.generate_rid(f'twitter:{tweet_id}')}"
        
        # Parse timestamp
        created_at = tweet.get('created_at')
        if created_at:
            try:
                created_at = datetime.fromisoformat(
                    created_at.replace('Z', '+00:00')
                ).isoformat()
            except:
                created_at = datetime.now().isoformat()
        else:
            created_at = datetime.now().isoformat()
        
        # Build document
        document = {
            'rid': rid,
            'source': f"twitter:@{tweet.get('author_username', 'unknown')}",
            'source_type': 'twitter',
            'url': tweet.get('url', ''),
            'title': f"Tweet by @{tweet.get('author_username', 'unknown')}",
            'content': tweet.get('text', ''),
            'author': tweet.get('author_username', 'unknown'),
            'timestamp': created_at,
            'metadata': {
                'platform': 'twitter',
                'tweet_id': tweet_id,
                'author_name': tweet.get('author_name'),
                'author_username': tweet.get('author_username'),
                'metrics': tweet.get('metrics', {}),
                'source_type': tweet.get('source_type'),
                'source_user': tweet.get('source_user'),
                'search_query': tweet.get('search_query'),
                # Publication date for daily/weekly digests
                'published_at': created_at,
                'published_confidence': 0.95  # High confidence from Twitter timestamps
            }
        }
        
        self.processed_tweets.add(tweet_id)
        return document
    
    async def send_to_koi(self, document: Dict) -> bool:
        """Send document to KOI coordinator as bundle"""
        try:
            # Create bundle from document
            bundle = document_to_bundle(document)
            
            # Emit as NEW event through KOI node
            await self.koi_node.emit_new_event(bundle)
            
            print(f"      📤 Sent to KOI: {document['title']}")
            return True
            
        except Exception as e:
            print(f"      ❌ Failed to send to KOI: {e}")
            return False
    
    async def collect_tweets(self, max_per_source: int = 10) -> int:
        """Collect tweets from all configured sources"""
        all_tweets = []
        sent_count = 0
        
        # Collect from user timelines
        print("\n📱 Collecting from user timelines...")
        for username in self.accounts:
            tweets = await self.scrape_user_timeline(username, max_per_source)
            
            for tweet in tweets:
                document = self.process_tweet_to_document(tweet)
                if document and await self.send_to_koi(document):
                    sent_count += 1
            
            # Rate limiting
            await asyncio.sleep(self.min_delay)
        
        # Collect from search queries
        print("\n🔍 Collecting from search queries...")
        for query in self.search_queries:
            tweets = await self.scrape_search(query, max_per_source)
            
            for tweet in tweets:
                document = self.process_tweet_to_document(tweet)
                if document and await self.send_to_koi(document):
                    sent_count += 1
            
            # Rate limiting
            await asyncio.sleep(self.min_delay)
        
        return sent_count
    
    async def run(self, continuous: bool = False):
        """Run the Twitter sensor with KOI integration"""
        print("=" * 60)
        print("🐦 TWITTER SENSOR (KOI Integrated - Scraping Method)")
        print("=" * 60)
        
        # Start KOI node
        await self.koi_node.start()

        # Send initial heartbeat to register
        await self.send_heartbeat_event()

        # Start background heartbeat task
        asyncio.create_task(self.send_periodic_heartbeats())

        # Initialize browser
        await self.initialize_browser()
        
        try:
            while True:
                print(f"\n🕐 Starting collection cycle at {datetime.now().isoformat()}")
                
                # Collect tweets
                sent_count = await self.collect_tweets(max_per_source=5)
                
                print("\n" + "=" * 60)
                print(f"📊 COLLECTION SUMMARY")
                print(f"   Total tweets sent to KOI: {sent_count}")
                print("=" * 60)
                
                if not continuous:
                    break
                
                # Wait before next collection cycle
                print("\n💤 Waiting 30 minutes before next collection...")
                await asyncio.sleep(1800)  # 30 minutes
                
        finally:
            # Cleanup
            await self.close_browser()
            await self.koi_node.stop()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close_browser()
        if self.koi_node:
            await self.koi_node.stop()


async def main():
    """Main entry point for continuous monitoring"""
    async with TwitterKOISensor() as sensor:
        # Run continuously with 30-minute intervals
        await sensor.run(continuous=True)


if __name__ == "__main__":
    asyncio.run(main())