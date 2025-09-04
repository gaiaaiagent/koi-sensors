"""
KOI Sensor Network - Twitter/X Sensor Node
Collects tweets, user data, and threads from Twitter/X platform
"""

import asyncio
import tweepy
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from shared.handlers.base_sensor import BaseSensor
from shared.config.base import BaseSensorConfig, APIConfig
from shared.rid_types import TwitterTweet, TwitterUser, TwitterThread


class TwitterAPIConfig(APIConfig):
    """Twitter-specific API configuration"""
    bearer_token: Optional[str] = None
    consumer_key: Optional[str] = None
    consumer_secret: Optional[str] = None
    access_token: Optional[str] = None
    access_token_secret: Optional[str] = None
    
    # Twitter-specific settings
    max_results: int = 100
    tweet_fields: List[str] = [
        "id", "text", "author_id", "created_at", "context_annotations",
        "conversation_id", "in_reply_to_user_id", "referenced_tweets",
        "public_metrics", "possibly_sensitive", "lang", "source"
    ]
    user_fields: List[str] = [
        "id", "name", "username", "description", "public_metrics",
        "verified", "created_at", "location", "url", "profile_image_url"
    ]
    expansions: List[str] = [
        "author_id", "referenced_tweets.id", "in_reply_to_user_id"
    ]


class TwitterSensorConfig(BaseSensorConfig):
    """Twitter sensor configuration"""
    api: TwitterAPIConfig
    
    # Twitter-specific collection settings
    search_queries: List[str] = []
    user_timelines: List[str] = []  # User IDs or usernames to monitor
    hashtags: List[str] = []
    collect_replies: bool = True
    collect_retweets: bool = False
    max_tweet_age_hours: int = 24


class TwitterSensor(BaseSensor):
    """Twitter sensor node implementation"""
    
    def __init__(self, config: TwitterSensorConfig):
        super().__init__(config)
        self.config: TwitterSensorConfig = config
        self.client = self._initialize_twitter_client()
        self.last_tweet_id = None
    
    def _initialize_twitter_client(self) -> tweepy.Client:
        """Initialize Twitter API client"""
        return tweepy.Client(
            bearer_token=self.config.api.bearer_token,
            consumer_key=self.config.api.consumer_key,
            consumer_secret=self.config.api.consumer_secret,
            access_token=self.config.api.access_token,
            access_token_secret=self.config.api.access_token_secret,
            wait_on_rate_limit=True
        )
    
    async def collect_data(self) -> List[Dict[str, Any]]:
        """Collect tweets from various sources"""
        all_tweets = []
        
        try:
            # Collect from search queries
            for query in self.config.search_queries:
                tweets = await self._collect_search_tweets(query)
                all_tweets.extend(tweets)
            
            # Collect from user timelines
            for user in self.config.user_timelines:
                tweets = await self._collect_user_timeline(user)
                all_tweets.extend(tweets)
            
            # Collect from hashtag searches
            for hashtag in self.config.hashtags:
                query = f"#{hashtag}"
                tweets = await self._collect_search_tweets(query)
                all_tweets.extend(tweets)
        
        except Exception as e:
            self.logger.error(f"Error collecting Twitter data: {e}")
            raise
        
        return all_tweets
    
    async def _collect_search_tweets(self, query: str) -> List[Dict[str, Any]]:
        """Collect tweets from search API"""
        tweets = []
        
        try:
            response = self.client.search_recent_tweets(
                query=query,
                max_results=self.config.api.max_results,
                tweet_fields=self.config.api.tweet_fields,
                user_fields=self.config.api.user_fields,
                expansions=self.config.api.expansions,
                since_id=self.last_tweet_id
            )
            
            if response.data:
                for tweet in response.data:
                    tweet_dict = tweet.data.copy()
                    
                    # Add user data if available
                    if hasattr(response, 'includes') and 'users' in response.includes:
                        users_dict = {user.id: user.data for user in response.includes['users']}
                        tweet_dict['user'] = users_dict.get(tweet.author_id, {})
                    
                    # Add metadata
                    tweet_dict['collection_query'] = query
                    tweet_dict['collection_method'] = 'search'
                    
                    tweets.append(tweet_dict)
                
                # Update last seen tweet ID for pagination
                if tweets:
                    self.last_tweet_id = max(int(tweet['id']) for tweet in tweets)
        
        except Exception as e:
            self.logger.error(f"Error collecting search tweets for '{query}': {e}")
        
        return tweets
    
    async def _collect_user_timeline(self, user_identifier: str) -> List[Dict[str, Any]]:
        """Collect tweets from user timeline"""
        tweets = []
        
        try:
            # Get user ID if username provided
            if not user_identifier.isdigit():
                user = self.client.get_user(username=user_identifier)
                user_id = user.data.id
            else:
                user_id = user_identifier
            
            response = self.client.get_users_tweets(
                id=user_id,
                max_results=self.config.api.max_results,
                tweet_fields=self.config.api.tweet_fields,
                user_fields=self.config.api.user_fields,
                expansions=self.config.api.expansions,
                exclude=['retweets'] if not self.config.collect_retweets else None,
                exclude=['replies'] if not self.config.collect_replies else None
            )
            
            if response.data:
                for tweet in response.data:
                    tweet_dict = tweet.data.copy()
                    
                    # Add user data
                    if hasattr(response, 'includes') and 'users' in response.includes:
                        users_dict = {user.id: user.data for user in response.includes['users']}
                        tweet_dict['user'] = users_dict.get(tweet.author_id, {})
                    
                    # Add metadata
                    tweet_dict['collection_method'] = 'user_timeline'
                    tweet_dict['collection_user'] = user_identifier
                    
                    tweets.append(tweet_dict)
        
        except Exception as e:
            self.logger.error(f"Error collecting user timeline for '{user_identifier}': {e}")
        
        return tweets
    
    def create_rid(self, item_data: Dict[str, Any]) -> TwitterTweet:
        """Create TwitterTweet RID from tweet data"""
        return TwitterTweet(
            user_id=str(item_data['author_id']),
            tweet_id=str(item_data['id'])
        )
    
    def extract_content(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract normalized content from tweet data"""
        return {
            "text": item_data.get('text', ''),
            "author_id": item_data.get('author_id'),
            "author_username": item_data.get('user', {}).get('username', ''),
            "author_name": item_data.get('user', {}).get('name', ''),
            "created_at": item_data.get('created_at'),
            "tweet_id": item_data.get('id'),
            "conversation_id": item_data.get('conversation_id'),
            "in_reply_to_user_id": item_data.get('in_reply_to_user_id'),
            "language": item_data.get('lang'),
            "source": item_data.get('source'),
            "public_metrics": item_data.get('public_metrics', {}),
            "referenced_tweets": item_data.get('referenced_tweets', []),
            "context_annotations": item_data.get('context_annotations', []),
            "possibly_sensitive": item_data.get('possibly_sensitive', False),
            
            # Collection metadata
            "collection_method": item_data.get('collection_method'),
            "collection_query": item_data.get('collection_query'),
            "collection_user": item_data.get('collection_user')
        }
    
    def apply_content_filters(self, item_data: Dict[str, Any]) -> bool:
        """Apply Twitter-specific content filtering"""
        # Apply base filters first
        if not super().apply_content_filters(item_data):
            return False
        
        # Filter retweets if configured
        if self.config.content_filter.filter_retweets:
            if item_data.get('referenced_tweets'):
                for ref in item_data['referenced_tweets']:
                    if ref.get('type') == 'retweeted':
                        return False
        
        # Filter replies if configured
        if self.config.content_filter.filter_replies:
            if item_data.get('in_reply_to_user_id'):
                return False
        
        # Filter by possibly sensitive content
        if item_data.get('possibly_sensitive', False):
            return False
        
        # Filter by language
        tweet_lang = item_data.get('lang', 'en')
        if tweet_lang not in self.config.content_filter.languages:
            return False
        
        return True


# Example usage
async def main():
    """Example usage of TwitterSensor"""
    config = TwitterSensorConfig(
        sensor_name="twitter-regen",
        platform="twitter",
        api=TwitterAPIConfig(
            bearer_token="your_bearer_token_here",
            consumer_key="your_consumer_key_here",
            consumer_secret="your_consumer_secret_here",
            access_token="your_access_token_here",
            access_token_secret="your_access_token_secret_here"
        ),
        koi_net=KoiNetConfig(
            node_name="twitter-regen-sensor",
            coordinator_url="http://localhost:8000/koi-net"
        ),
        search_queries=[
            "regenerative agriculture",
            "carbon credits",
            "regen network",
            "climate solutions"
        ],
        hashtags=[
            "regen",
            "regenag",
            "carboncredits",
            "climatetech"
        ]
    )
    
    sensor = TwitterSensor(config)
    await sensor.start()


if __name__ == "__main__":
    asyncio.run(main())