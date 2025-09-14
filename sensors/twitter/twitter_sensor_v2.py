#!/usr/bin/env python3
"""
KOI Sensor Network - Twitter/X Sensor Node v2
Monitors Twitter/X for relevant tweets and user data using KOI protocol
"""

import os
import sys
import json
import time
import tweepy
import logging
import hashlib
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID, GenericRID
from koi_protocol.core.bundle_system import Bundle, document_to_bundle


@dataclass
class TwitterConfig:
    """Configuration for Twitter sensor"""
    # API credentials
    bearer_token: str = ""
    consumer_key: str = ""
    consumer_secret: str = ""
    access_token: str = ""
    access_token_secret: str = ""

    # Monitoring settings
    search_queries: List[str] = field(default_factory=lambda: [
        "regenerative agriculture",
        "carbon credits",
        "regen network",
        "ecological credits"
    ])

    hashtags: List[str] = field(default_factory=lambda: [
        "regen",
        "regenag",
        "carboncredits",
        "climatetech"
    ])

    user_handles: List[str] = field(default_factory=lambda: [
        "regen_network"
    ])

    # Collection settings
    max_results: int = 100
    collect_replies: bool = True
    collect_retweets: bool = False
    max_tweet_age_hours: int = 24
    check_interval: int = 300  # 5 minutes

    # KOI settings
    coordinator_url: str = "http://localhost:8005"
    node_name: str = "twitter-sensor"


class TwitterTweetRID(RID):
    """Twitter tweet resource identifier"""

    def __init__(self, user_id: str, tweet_id: str):
        self.user_id = user_id
        self.tweet_id = tweet_id
        super().__init__("orn", f"twitter.tweet.{user_id}.{tweet_id}")


class TwitterUserRID(RID):
    """Twitter user resource identifier"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__("orn", f"twitter.user.{user_id}")


class TwitterKOISensor:
    """Twitter monitoring sensor using KOI protocol"""

    def __init__(self, config: TwitterConfig):
        self.config = config
        self.logger = self._setup_logging()

        # Initialize KOI node
        self.koi_node = KOIPartialNode(
            node_name=config.node_name,
            coordinator_url=config.coordinator_url,
            poll_interval=30
        )

        # Twitter client setup
        self.client = self._setup_twitter_client()

        # Track processed tweets
        self.processed_tweets: Set[str] = set()
        self.processed_users: Set[str] = set()

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('koi.sensor.twitter')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            logger.addHandler(handler)

        return logger

    def _setup_twitter_client(self) -> Optional[tweepy.Client]:
        """Setup Twitter API client"""
        try:
            # Try to get credentials from environment first
            bearer_token = os.getenv('TWITTER_BEARER_TOKEN', self.config.bearer_token)

            if not bearer_token or bearer_token == "":
                self.logger.warning("No Twitter bearer token configured")
                return None

            client = tweepy.Client(
                bearer_token=bearer_token,
                consumer_key=os.getenv('TWITTER_CONSUMER_KEY', self.config.consumer_key),
                consumer_secret=os.getenv('TWITTER_CONSUMER_SECRET', self.config.consumer_secret),
                access_token=os.getenv('TWITTER_ACCESS_TOKEN', self.config.access_token),
                access_token_secret=os.getenv('TWITTER_ACCESS_TOKEN_SECRET', self.config.access_token_secret),
                wait_on_rate_limit=True
            )

            # Test the connection
            client.get_me()
            self.logger.info("Twitter API client initialized successfully")
            return client

        except Exception as e:
            self.logger.error(f"Failed to setup Twitter client: {e}")
            return None

    def search_tweets(self, query: str) -> List[Dict[str, Any]]:
        """Search for tweets matching query"""
        if not self.client:
            return []

        try:
            # Calculate time window
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=self.config.max_tweet_age_hours)

            response = self.client.search_recent_tweets(
                query=query,
                max_results=self.config.max_results,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                tweet_fields=['id', 'text', 'author_id', 'created_at', 'public_metrics'],
                user_fields=['id', 'name', 'username', 'description'],
                expansions=['author_id']
            )

            if not response.data:
                return []

            tweets = []
            users = {user.id: user for user in (response.includes.get('users', []) or [])}

            for tweet in response.data:
                if tweet.id in self.processed_tweets:
                    continue

                tweet_data = {
                    'id': tweet.id,
                    'text': tweet.text,
                    'author_id': tweet.author_id,
                    'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                    'metrics': tweet.public_metrics
                }

                # Add author info if available
                if tweet.author_id in users:
                    user = users[tweet.author_id]
                    tweet_data['author'] = {
                        'id': user.id,
                        'name': user.name,
                        'username': user.username,
                        'description': user.description
                    }

                tweets.append(tweet_data)
                self.processed_tweets.add(tweet.id)

            return tweets

        except Exception as e:
            self.logger.error(f"Error searching tweets for '{query}': {e}")
            return []

    def process_tweet(self, tweet_data: Dict[str, Any]):
        """Process and emit a tweet as KOI event"""
        try:
            # Create RID for tweet
            rid = TwitterTweetRID(
                user_id=str(tweet_data['author_id']),
                tweet_id=str(tweet_data['id'])
            )

            # Create document
            document = {
                'rid': rid.to_string(),
                'type': 'twitter_tweet',
                'content': {
                    'text': tweet_data['text'],
                    'author': tweet_data.get('author', {}),
                    'metrics': tweet_data.get('metrics', {}),
                    'created_at': tweet_data.get('created_at')
                },
                'metadata': {
                    'source': 'twitter',
                    'collected_at': datetime.now(timezone.utc).isoformat(),
                    'sensor': self.config.node_name
                }
            }

            # Convert to bundle
            bundle = document_to_bundle(document)

            # Emit as KOI event
            self.koi_node.emit_new_event(bundle)
            self.logger.info(f"Emitted tweet {tweet_data['id']} from @{tweet_data.get('author', {}).get('username', 'unknown')}")

        except Exception as e:
            self.logger.error(f"Error processing tweet: {e}")

    def monitor_queries(self):
        """Monitor configured search queries"""
        for query in self.config.search_queries:
            self.logger.info(f"Searching for: {query}")
            tweets = self.search_tweets(query)

            for tweet in tweets:
                self.process_tweet(tweet)

            if tweets:
                self.logger.info(f"Processed {len(tweets)} tweets for query: {query}")

    def monitor_hashtags(self):
        """Monitor configured hashtags"""
        for hashtag in self.config.hashtags:
            query = f"#{hashtag}"
            self.logger.info(f"Searching hashtag: {query}")
            tweets = self.search_tweets(query)

            for tweet in tweets:
                self.process_tweet(tweet)

            if tweets:
                self.logger.info(f"Processed {len(tweets)} tweets for hashtag: {hashtag}")

    def monitor_users(self):
        """Monitor tweets from specific users"""
        for handle in self.config.user_handles:
            query = f"from:{handle}"
            self.logger.info(f"Checking tweets from: @{handle}")
            tweets = self.search_tweets(query)

            for tweet in tweets:
                self.process_tweet(tweet)

            if tweets:
                self.logger.info(f"Processed {len(tweets)} tweets from @{handle}")

    async def run(self):
        """Main sensor loop"""
        self.logger.info("Starting Twitter KOI Sensor")
        await self.koi_node.start()

        if not self.client:
            self.logger.error("Twitter client not configured. Please set TWITTER_BEARER_TOKEN environment variable.")
            self.logger.info("Sensor will run in passive mode (processing events only)")

        try:
            while True:
                if self.client:
                    self.logger.info("Starting Twitter monitoring cycle")

                    # Monitor different sources
                    self.monitor_queries()
                    self.monitor_hashtags()
                    self.monitor_users()

                    self.logger.info(f"Monitoring cycle complete. Sleeping for {self.config.check_interval} seconds")

                time.sleep(self.config.check_interval)

        except KeyboardInterrupt:
            self.logger.info("Shutting down Twitter sensor")
        except Exception as e:
            self.logger.error(f"Sensor error: {e}")
            raise
        finally:
            self.koi_node.stop()


async def main():
    """Main entry point"""
    # Load configuration (can be from file or environment)
    config = TwitterConfig()

    # Override with environment variables if present
    if os.getenv('KOI_COORDINATOR_URL'):
        config.coordinator_url = os.getenv('KOI_COORDINATOR_URL')

    # Create and run sensor
    sensor = TwitterKOISensor(config)
    await sensor.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())