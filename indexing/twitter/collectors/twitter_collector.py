"""
Twitter/X collector for indexing tweets from Regen Network accounts
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import pandas as pd

# Add parent directories to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import from collectors module
from collectors.base_collector import BaseCollector, Document


class TwitterCollector(BaseCollector):
    """
    Collector for Twitter/X content using twscrape
    Handles authentication, rate limiting, and tweet collection
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Twitter collector
        
        Args:
            config: Twitter configuration from sources.yaml
        """
        super().__init__(config)
        self.accounts = config.get('twitter', {}).get('accounts', [])
        self.rate_limits = config.get('twitter', {}).get('rate_limits', {
            'requests_per_hour': 300,
            'retry_attempts': 3,
            'cooldown_seconds': 60
        })
        self.cache_config = config.get('twitter', {}).get('cache', {
            'enabled': True,
            'ttl_hours': 6
        })
        
        # Storage paths
        self.storage_dir = Path(__file__).parent.parent / 'storage'
        self.tweets_dir = self.storage_dir / 'tweets'
        self.cache_dir = self.storage_dir / 'cache'
        self.tweets_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize twscrape API (will be set up in setup_api)
        self.api = None
        self.scraper_type = 'twscrape'  # Using twscrape with cookies
        
    def validate_config(self) -> bool:
        """
        Validate Twitter collector configuration
        """
        if not self.accounts:
            logger.error("No Twitter accounts configured")
            return False
        
        for account in self.accounts:
            if 'username' not in account:
                logger.error(f"Twitter account missing username: {account}")
                return False
        
        return True
    
    async def setup_api(self):
        """
        Set up the Twitter scraping API with authentication
        """
        try:
            if self.scraper_type == 'twscrape':
                from twscrape import API
                
                # Initialize API
                self.api = API()
                
                # Load credentials from environment or credential manager
                auth_file = self.cache_dir / 'twitter_auth.json'
                if auth_file.exists():
                    with open(auth_file, 'r') as f:
                        auth_data = json.load(f)
                    
                    # Add accounts from saved authentication
                    for account in auth_data.get('accounts', []):
                        if 'cookies' in account:
                            # Decrypt cookies if needed
                            from twitter.utils.auth_manager import TwitterAuthManager
                            auth_mgr = TwitterAuthManager()
                            decrypted_account = auth_mgr.get_account(account.get('username'))
                            if decrypted_account and 'cookies' in decrypted_account:
                                cookies_str = decrypted_account['cookies']
                                # twscrape expects cookies as a string, not dict
                                if not isinstance(cookies_str, str):
                                    # Convert dict to string if needed
                                    cookies_str = '; '.join([f"{k}={v}" for k, v in cookies_str.items()])
                                
                                await self.api.pool.add_account(
                                    username=account.get('username'),
                                    password='dummy',  # Not used with cookies
                                    email='dummy@example.com',  # Not used with cookies
                                    email_password='dummy',  # Not used with cookies
                                    cookies=cookies_str  # Pass as string
                                )
                                
                                # Login to activate
                                await self.api.pool.login_all()
                        else:
                            logger.warning(f"Account {account.get('username')} missing cookies")
                else:
                    logger.warning("No authentication file found. Run setup_twitter_auth.py first.")
                    
            elif self.scraper_type == 'ntscraper':
                # Fallback to ntscraper if twscrape fails
                from ntscraper import Nitter
                self.api = Nitter()
                logger.info("Using ntscraper as fallback")
                
        except ImportError as e:
            logger.error(f"Failed to import scraper library: {e}")
            logger.info("Please install with: pip install twscrape ntscraper")
            return False
        except Exception as e:
            logger.error(f"Failed to setup API: {e}")
            return False
        
        return True
    
    async def collect(self, limit: Optional[int] = None) -> List[Document]:
        """
        Collect tweets from configured Twitter accounts
        
        Args:
            limit: Maximum number of tweets to collect
            
        Returns:
            List of collected tweet documents
        """
        if not self.validate_config():
            return []
        
        # Setup API if not already done
        if not self.api:
            if not await self.setup_api():
                logger.error("Failed to setup Twitter API")
                return []
        
        all_documents = []
        doc_count = 0
        
        for account_config in self.accounts:
            if limit and doc_count >= limit:
                break
            
            try:
                username = account_config['username']
                logger.info(f"Collecting tweets from @{username}")
                
                account_docs = await self.collect_user_tweets(
                    username=username,
                    config=account_config,
                    limit=limit - doc_count if limit else None
                )
                
                all_documents.extend(account_docs)
                doc_count += len(account_docs)
                
                # Save documents after each account
                self.save_documents(account_docs)
                
                # Rate limiting cooldown
                if len(self.accounts) > 1:
                    await asyncio.sleep(self.rate_limits['cooldown_seconds'])
                
            except Exception as e:
                logger.error(f"Error collecting tweets from {account_config['username']}: {e}")
                continue
        
        logger.info(f"Collected {len(all_documents)} tweets from {len(self.accounts)} accounts")
        return all_documents
    
    async def collect_user_tweets(
        self, 
        username: str, 
        config: Dict[str, Any],
        limit: Optional[int] = None
    ) -> List[Document]:
        """
        Collect tweets from a specific user
        
        Args:
            username: Twitter username (without @)
            config: Account-specific configuration
            limit: Maximum number of tweets to collect
            
        Returns:
            List of tweet documents
        """
        documents = []
        
        try:
            if self.scraper_type == 'twscrape':
                # Use twscrape API
                # First get user info
                user = await self.api.user_by_login(username)
                if not user:
                    logger.error(f"User @{username} not found")
                    return documents
                
                tweets = []
                async for tweet in self.api.user_tweets(user.id, limit=limit or 1000):
                    tweets.append(tweet)
                    if limit and len(tweets) >= limit:
                        break
                
                # Convert tweets to documents
                for tweet in tweets:
                    doc = self.tweet_to_document(tweet, username)
                    if doc:
                        documents.append(doc)
                        
            elif self.scraper_type == 'ntscraper':
                # Use ntscraper as fallback
                try:
                    tweets_data = self.api.get_tweets(username, mode='user', number=limit or 1000)
                    
                    if tweets_data and 'tweets' in tweets_data:
                        for tweet in tweets_data['tweets']:
                            doc = self.ntscraper_tweet_to_document(tweet, username)
                            if doc:
                                documents.append(doc)
                except Exception as e:
                    logger.error(f"ntscraper error: {e}")
                    # Try without authentication
                    logger.info("Trying anonymous scraping...")
                    from ntscraper import Nitter
                    anonymous_api = Nitter()
                    tweets_data = anonymous_api.get_tweets(username, mode='user', number=limit or 100)
                    if tweets_data and 'tweets' in tweets_data:
                        for tweet in tweets_data['tweets']:
                            doc = self.ntscraper_tweet_to_document(tweet, username)
                            if doc:
                                documents.append(doc)
            
            logger.info(f"Collected {len(documents)} tweets from @{username}")
            
            # Save raw tweets for debugging/backup
            if documents:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                tweets_file = self.tweets_dir / f"{username}_{timestamp}.json"
                with open(tweets_file, 'w') as f:
                    json.dump([d.to_dict() for d in documents], f, indent=2, default=str)
                    
        except Exception as e:
            logger.error(f"Error collecting tweets from @{username}: {e}")
            
        return documents
    
    def tweet_to_document(self, tweet: Any, username: str) -> Optional[Document]:
        """
        Convert a twscrape tweet object to a Document
        
        Args:
            tweet: Tweet object from twscrape
            username: Username of the account
            
        Returns:
            Document object or None if conversion fails
        """
        try:
            # Extract tweet content and metadata
            tweet_id = str(tweet.id)
            content = tweet.rawContent
            created_at = tweet.date
            
            # Build metadata
            metadata = {
                'tweet_id': tweet_id,
                'username': username,
                'likes': tweet.likeCount,
                'retweets': tweet.retweetCount,
                'replies': tweet.replyCount,
                'quotes': tweet.quoteCount,
                'views': getattr(tweet, 'viewCount', 0),
                'is_retweet': bool(tweet.retweetedTweet),
                'is_quote': bool(tweet.quotedTweet),
                'is_reply': bool(tweet.inReplyToTweetId),
                'language': tweet.lang,
                'hashtags': tweet.hashtags if tweet.hashtags else [],
                'mentions': [m.username for m in tweet.mentionedUsers] if tweet.mentionedUsers else [],
                'urls': [u.url for u in tweet.links] if tweet.links else [],
                'media': []  # Fix media handling
            }
            
            # Handle media properly
            if tweet.media:
                try:
                    # Check if media is iterable
                    if hasattr(tweet.media, '__iter__'):
                        metadata['media'] = [getattr(m, 'fullUrl', str(m)) for m in tweet.media]
                    else:
                        # Single media object
                        metadata['media'] = [getattr(tweet.media, 'fullUrl', str(tweet.media))]
                except:
                    pass  # Skip media if there's an issue
            
            # Create document
            doc = Document(
                id=f"twitter_{tweet_id}",
                source=f"twitter:{username}",
                source_type="twitter",
                url=f"https://twitter.com/{username}/status/{tweet_id}",
                title=f"Tweet by @{username} - {content[:50]}..." if len(content) > 50 else f"Tweet by @{username}",
                content=content,
                metadata=metadata,
                collected_at=datetime.now(),
                last_modified=created_at,
                author=f"@{username}",
                tags=['twitter', 'social_media', username] + (tweet.hashtags or [])
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error converting tweet to document: {e}")
            return None
    
    def ntscraper_tweet_to_document(self, tweet: Dict, username: str) -> Optional[Document]:
        """
        Convert an ntscraper tweet dict to a Document
        
        Args:
            tweet: Tweet dictionary from ntscraper
            username: Username of the account
            
        Returns:
            Document object or None if conversion fails
        """
        try:
            # Extract tweet content and metadata
            tweet_id = tweet.get('id', '')
            content = tweet.get('text', '')
            created_at = tweet.get('created_at')
            
            # Parse date if string
            if isinstance(created_at, str):
                created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            
            # Build metadata
            metadata = {
                'tweet_id': tweet_id,
                'username': username,
                'likes': tweet.get('stats', {}).get('likes', 0),
                'retweets': tweet.get('stats', {}).get('retweets', 0),
                'replies': tweet.get('stats', {}).get('comments', 0),
                'is_retweet': tweet.get('is_retweet', False),
                'is_quote': tweet.get('is_quote_status', False),
                'is_reply': tweet.get('is_reply', False),
                'hashtags': tweet.get('hashtags', []),
                'mentions': tweet.get('mentions', []),
                'urls': tweet.get('urls', []),
                'media': tweet.get('media', [])
            }
            
            # Create document
            doc = Document(
                id=f"twitter_{tweet_id}",
                source=f"twitter:{username}",
                source_type="twitter",
                url=tweet.get('link', f"https://twitter.com/{username}/status/{tweet_id}"),
                title=f"Tweet by @{username} - {content[:50]}..." if len(content) > 50 else f"Tweet by @{username}",
                content=content,
                metadata=metadata,
                collected_at=datetime.now(),
                last_modified=created_at,
                author=f"@{username}",
                tags=['twitter', 'social_media', username] + tweet.get('hashtags', [])
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error converting ntscraper tweet to document: {e}")
            return None
    
    def save_documents(self, documents: List[Document]):
        """
        Save documents to storage
        
        Args:
            documents: List of documents to save
        """
        if not documents:
            return
        
        # Save to the main storage directory
        storage_path = Path(__file__).parent.parent.parent / 'storage' / 'documents'
        storage_path.mkdir(parents=True, exist_ok=True)
        
        for doc in documents:
            doc_file = storage_path / f"{doc.id}.json"
            # Use the existing to_json method from Document class
            with open(doc_file, 'w') as f:
                f.write(doc.to_json())
        
        logger.info(f"Saved {len(documents)} documents to storage")