"""
Twitter Scraper using Playwright - No authentication required
This scraper uses browser automation to collect tweets without API keys
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import quote

from loguru import logger
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
import diskcache
from tenacity import retry, stop_after_attempt, wait_exponential

class TwitterPlaywrightScraper:
    """
    Twitter scraper using Playwright browser automation
    Works without authentication by scraping the public Twitter interface
    """
    
    def __init__(self, cache_dir: Optional[Path] = None, headless: bool = True):
        """
        Initialize the Twitter scraper
        
        Args:
            cache_dir: Directory for caching scraped data
            headless: Run browser in headless mode (no UI)
        """
        self.cache_dir = cache_dir or Path("./cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = diskcache.Cache(str(self.cache_dir / "twitter_cache"))
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        
        # Rate limiting settings
        self.min_delay = 2  # Minimum seconds between requests
        self.max_delay = 5  # Maximum seconds between requests
        self.last_request_time = 0
        
        # Twitter URL patterns
        self.base_url = "https://twitter.com"
        self.search_url = "https://twitter.com/search"
        
    async def initialize(self):
        """
        Initialize Playwright browser and context
        """
        try:
            logger.info("Initializing Playwright browser...")
            
            try:
                self.playwright = await async_playwright().start()
                
                # Try to launch Chromium first
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    ]
                )
            except Exception as e:
                logger.warning(f"Chromium not installed: {e}")
                logger.info("Installing Playwright browsers...")
                
                # Install browsers
                import subprocess
                result = subprocess.run(
                    ["playwright", "install", "chromium"],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    raise Exception(f"Failed to install Playwright browsers: {result.stderr}")
                
                # Try again after installation
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox'
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
            
            logger.info("Browser initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise
    
    async def close(self):
        """
        Close browser and cleanup resources
        """
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
    
    async def _wait_and_scroll(self, page: Page):
        """
        Wait for content to load and scroll to load more tweets
        """
        # Wait for tweets to load
        try:
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
        except PlaywrightTimeout:
            logger.warning("No tweets found on page")
            return
        
        # Scroll to load more tweets
        previous_height = 0
        for _ in range(3):  # Scroll 3 times to load more content
            current_height = await page.evaluate('document.body.scrollHeight')
            if current_height == previous_height:
                break
            
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)  # Wait for new content to load
            previous_height = current_height
    
    async def _extract_tweet_data(self, tweet_element) -> Optional[Dict[str, Any]]:
        """
        Extract data from a tweet element
        """
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
                metrics['likes'] = self._parse_count(like_text)
            
            # Retweet count
            retweet_element = await tweet_element.query_selector('[data-testid="retweet"] span')
            if retweet_element:
                retweet_text = await retweet_element.inner_text()
                metrics['retweets'] = self._parse_count(retweet_text)
            
            # Reply count
            reply_element = await tweet_element.query_selector('[data-testid="reply"] span')
            if reply_element:
                reply_text = await reply_element.inner_text()
                metrics['replies'] = self._parse_count(reply_text)
            
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
            
            # Extract tweet URL
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
            
            # Check if it's a reply
            reply_element = await tweet_element.query_selector('[data-testid="Tweet-User-Avatar"]')
            if reply_element:
                parent = await reply_element.evaluate_handle('node => node.parentElement.parentElement')
                reply_text = await parent.inner_text()
                if 'Replying to' in reply_text:
                    tweet_data['is_reply'] = True
            
            return tweet_data if tweet_data.get('text') else None
            
        except Exception as e:
            logger.error(f"Error extracting tweet data: {e}")
            return None
    
    def _parse_count(self, text: str) -> int:
        """
        Parse count from text (e.g., "1.2K" -> 1200)
        """
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
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def scrape_user_timeline(
        self, 
        username: str, 
        max_tweets: int = 100,
        include_replies: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Scrape tweets from a user's timeline
        
        Args:
            username: Twitter username (without @)
            max_tweets: Maximum number of tweets to collect
            include_replies: Whether to include replies
            
        Returns:
            List of tweet dictionaries
        """
        # Check cache first
        cache_key = f"user:{username}:{max_tweets}:{include_replies}"
        cached = self.cache.get(cache_key)
        if cached and datetime.fromisoformat(cached['timestamp']) > datetime.now() - timedelta(hours=1):
            logger.info(f"Using cached data for @{username}")
            return cached['tweets']
        
        tweets = []
        
        try:
            # Navigate to user profile
            url = f"{self.base_url}/{username}"
            if not include_replies:
                url += "?f=tweets"  # Filter to exclude replies
            
            logger.info(f"Navigating to {url}")
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for content and scroll
            await self._wait_and_scroll(self.page)
            
            # Extract tweets
            tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')
            
            for element in tweet_elements[:max_tweets]:
                tweet_data = await self._extract_tweet_data(element)
                if tweet_data:
                    tweet_data['source'] = 'user_timeline'
                    tweet_data['username'] = username
                    tweets.append(tweet_data)
            
            logger.info(f"Scraped {len(tweets)} tweets from @{username}")
            
            # Cache the results
            self.cache.set(cache_key, {
                'tweets': tweets,
                'timestamp': datetime.now().isoformat()
            }, expire=3600)  # Cache for 1 hour
            
        except Exception as e:
            logger.error(f"Error scraping user timeline for @{username}: {e}")
            raise
        
        return tweets
    
    async def scrape_user_replies(
        self,
        username: str,
        max_replies: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Scrape replies from a user
        
        Args:
            username: Twitter username (without @)
            max_replies: Maximum number of replies to collect
            
        Returns:
            List of reply dictionaries
        """
        # Check cache
        cache_key = f"replies:{username}:{max_replies}"
        cached = self.cache.get(cache_key)
        if cached and datetime.fromisoformat(cached['timestamp']) > datetime.now() - timedelta(hours=1):
            logger.info(f"Using cached replies for @{username}")
            return cached['replies']
        
        replies = []
        
        try:
            # Navigate to user's replies
            url = f"{self.base_url}/{username}/with_replies"
            logger.info(f"Navigating to {url}")
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait and scroll
            await self._wait_and_scroll(self.page)
            
            # Extract tweets
            tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')
            
            for element in tweet_elements[:max_replies]:
                tweet_data = await self._extract_tweet_data(element)
                if tweet_data and tweet_data.get('is_reply'):
                    tweet_data['source'] = 'user_replies'
                    tweet_data['username'] = username
                    replies.append(tweet_data)
            
            logger.info(f"Scraped {len(replies)} replies from @{username}")
            
            # Cache results
            self.cache.set(cache_key, {
                'replies': replies,
                'timestamp': datetime.now().isoformat()
            }, expire=3600)
            
        except Exception as e:
            logger.error(f"Error scraping replies for @{username}: {e}")
            raise
        
        return replies
    
    async def search_mentions(
        self,
        username: str,
        max_tweets: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for tweets mentioning a user
        
        Args:
            username: Twitter username (without @)
            max_tweets: Maximum number of tweets to collect
            
        Returns:
            List of tweet dictionaries
        """
        # Check cache
        cache_key = f"mentions:{username}:{max_tweets}"
        cached = self.cache.get(cache_key)
        if cached and datetime.fromisoformat(cached['timestamp']) > datetime.now() - timedelta(hours=1):
            logger.info(f"Using cached mentions for @{username}")
            return cached['mentions']
        
        mentions = []
        
        try:
            # Search for mentions
            query = f"@{username}"
            encoded_query = quote(query)
            url = f"{self.search_url}?q={encoded_query}&f=live"  # Latest tweets
            
            logger.info(f"Searching for mentions of @{username}")
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait and scroll
            await self._wait_and_scroll(self.page)
            
            # Extract tweets
            tweet_elements = await self.page.query_selector_all('article[data-testid="tweet"]')
            
            for element in tweet_elements[:max_tweets]:
                tweet_data = await self._extract_tweet_data(element)
                if tweet_data:
                    tweet_data['source'] = 'mentions'
                    tweet_data['mentioned_user'] = username
                    mentions.append(tweet_data)
            
            logger.info(f"Found {len(mentions)} mentions of @{username}")
            
            # Cache results
            self.cache.set(cache_key, {
                'mentions': mentions,
                'timestamp': datetime.now().isoformat()
            }, expire=3600)
            
        except Exception as e:
            logger.error(f"Error searching mentions for @{username}: {e}")
            raise
        
        return mentions


async def main():
    """
    Example usage of the Twitter scraper
    """
    scraper = TwitterPlaywrightScraper(headless=True)
    
    try:
        # Initialize browser
        await scraper.initialize()
        
        # Scrape @regen_network timeline
        logger.info("Scraping @regen_network timeline...")
        tweets = await scraper.scrape_user_timeline(
            username="regen_network",
            max_tweets=20,
            include_replies=False
        )
        
        logger.info(f"Collected {len(tweets)} tweets")
        for tweet in tweets[:5]:  # Show first 5
            logger.info(f"Tweet: {tweet.get('text', '')[:100]}...")
        
        # Scrape replies
        logger.info("\nScraping @regen_network replies...")
        replies = await scraper.scrape_user_replies(
            username="regen_network",
            max_replies=10
        )
        
        logger.info(f"Collected {len(replies)} replies")
        
        # Search for mentions
        logger.info("\nSearching for mentions of @regen_network...")
        mentions = await scraper.search_mentions(
            username="regen_network",
            max_tweets=10
        )
        
        logger.info(f"Found {len(mentions)} mentions")
        
        # Save results
        output_dir = Path("./output")
        output_dir.mkdir(exist_ok=True)
        
        with open(output_dir / "regen_tweets.json", "w") as f:
            json.dump({
                'tweets': tweets,
                'replies': replies,
                'mentions': mentions,
                'scraped_at': datetime.now().isoformat()
            }, f, indent=2)
        
        logger.info(f"Results saved to {output_dir / 'regen_tweets.json'}")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())