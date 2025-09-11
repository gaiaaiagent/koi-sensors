#!/usr/bin/env python3
"""
Simple Twitter Scraper using ntscraper - No authentication required
This is a lightweight alternative that doesn't need browser automation
"""

import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger

try:
    from ntscraper import Nitter
except ImportError:
    logger.error("ntscraper not installed. Install with: pip install ntscraper")
    raise

class SimpleTwitterScraper:
    """
    Simple Twitter scraper using ntscraper
    Works without authentication or browser automation
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize the scraper
        
        Args:
            cache_dir: Directory for caching scraped data
        """
        self.cache_dir = cache_dir or Path("./cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.scraper = Nitter()
        self.cached_data = {}
        
    def scrape_user_tweets(
        self,
        username: str,
        max_tweets: int = 50,
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
        try:
            logger.info(f"Scraping tweets from @{username}...")
            
            # Get tweets using ntscraper
            tweets = self.scraper.get_tweets(
                username,
                mode='user',
                number=max_tweets
            )
            
            # Process tweets
            processed_tweets = []
            for tweet in tweets['tweets']:
                tweet_data = {
                    'id': tweet.get('tweet_id', ''),
                    'text': tweet.get('text', ''),
                    'author_username': username,
                    'created_at': tweet.get('created_at', ''),
                    'url': tweet.get('link', ''),
                    'metrics': {
                        'likes': tweet.get('stats', {}).get('likes', 0),
                        'retweets': tweet.get('stats', {}).get('retweets', 0),
                        'replies': tweet.get('stats', {}).get('comments', 0)
                    },
                    'is_reply': tweet.get('is_retweet', False),
                    'source': 'user_timeline'
                }
                
                # Filter replies if needed
                if not include_replies and tweet_data['is_reply']:
                    continue
                    
                processed_tweets.append(tweet_data)
            
            logger.info(f"Collected {len(processed_tweets)} tweets from @{username}")
            
            # Save to cache
            cache_file = self.cache_dir / f"{username}_tweets.json"
            with open(cache_file, 'w') as f:
                json.dump({
                    'username': username,
                    'tweets': processed_tweets,
                    'scraped_at': datetime.now().isoformat()
                }, f, indent=2)
            
            return processed_tweets
            
        except Exception as e:
            logger.error(f"Error scraping tweets for @{username}: {e}")
            return []
    
    def search_tweets(
        self,
        query: str,
        max_tweets: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for tweets matching a query
        
        Args:
            query: Search query (e.g., "@regen_network" for mentions)
            max_tweets: Maximum number of tweets to collect
            
        Returns:
            List of tweet dictionaries
        """
        try:
            logger.info(f"Searching for: {query}")
            
            # Search tweets
            results = self.scraper.get_tweets(
                query,
                mode='search',
                number=max_tweets
            )
            
            # Process results
            processed_tweets = []
            for tweet in results['tweets']:
                tweet_data = {
                    'id': tweet.get('tweet_id', ''),
                    'text': tweet.get('text', ''),
                    'author_username': tweet.get('username', ''),
                    'author_name': tweet.get('name', ''),
                    'created_at': tweet.get('created_at', ''),
                    'url': tweet.get('link', ''),
                    'metrics': {
                        'likes': tweet.get('stats', {}).get('likes', 0),
                        'retweets': tweet.get('stats', {}).get('retweets', 0),
                        'replies': tweet.get('stats', {}).get('comments', 0)
                    },
                    'source': 'search',
                    'query': query
                }
                processed_tweets.append(tweet_data)
            
            logger.info(f"Found {len(processed_tweets)} tweets for query: {query}")
            return processed_tweets
            
        except Exception as e:
            logger.error(f"Error searching tweets for '{query}': {e}")
            return []


def test_simple_scraper():
    """
    Test the simple Twitter scraper
    """
    logger.info("="*50)
    logger.info("SIMPLE TWITTER SCRAPER TEST")
    logger.info("="*50)
    
    scraper = SimpleTwitterScraper()
    
    # Test 1: Scrape user timeline
    logger.info("\n📊 Test 1: Scraping @regen_network timeline...")
    tweets = scraper.scrape_user_tweets(
        username="regen_network",
        max_tweets=10,
        include_replies=False
    )
    
    if tweets:
        logger.success(f"✅ Collected {len(tweets)} tweets")
        logger.info(f"Sample tweet: {tweets[0].get('text', '')[:100]}...")
    else:
        logger.warning("⚠️  No tweets collected")
    
    # Test 2: Search for mentions
    logger.info("\n🔍 Test 2: Searching for mentions...")
    mentions = scraper.search_tweets(
        query="@regen_network",
        max_tweets=5
    )
    
    if mentions:
        logger.success(f"✅ Found {len(mentions)} mentions")
    else:
        logger.warning("⚠️  No mentions found")
    
    # Save combined results
    output_dir = Path("./output")
    output_dir.mkdir(exist_ok=True)
    
    output_file = output_dir / f"simple_scraper_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump({
            'tweets': tweets,
            'mentions': mentions,
            'scraped_at': datetime.now().isoformat()
        }, f, indent=2)
    
    logger.info(f"\n📁 Results saved to: {output_file}")
    
    # Print summary
    logger.info("\n" + "="*50)
    logger.info("📊 TEST SUMMARY")
    logger.info("="*50)
    logger.info(f"✅ Tweets collected: {len(tweets)}")
    logger.info(f"✅ Mentions found: {len(mentions)}")
    
    return tweets, mentions


if __name__ == "__main__":
    test_simple_scraper()