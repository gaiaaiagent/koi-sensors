"""
Twitter Archive Collector
Processes Twitter/X archive exports to index tweets and replies
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
import hashlib
from loguru import logger

from .base_collector import BaseCollector


class TwitterCollector(BaseCollector):
    """Collector for Twitter/X archive data"""
    
    def __init__(self, archive_path: str, cache_dir: str = "indexing/cache/twitter"):
        """
        Initialize Twitter collector
        
        Args:
            archive_path: Path to extracted Twitter archive directory
            cache_dir: Directory for caching processed tweets
        """
        super().__init__(cache_dir)
        self.cache_dir = Path(cache_dir)
        self.archive_path = Path(archive_path)
        self.data_dir = self.archive_path / "data"
        
        if not self.data_dir.exists():
            # Try to find the data directory in subdirectories
            for subdir in self.archive_path.glob("*/data"):
                if subdir.is_dir():
                    self.data_dir = subdir
                    break
        
        if not self.data_dir.exists():
            raise ValueError(f"Twitter data directory not found in {archive_path}")
        
        logger.info(f"Twitter collector initialized with archive at {self.data_dir}")
    
    def validate_config(self, config: Dict) -> bool:
        """Validate collector configuration"""
        # Twitter collector doesn't need external config
        return True
    
    def _parse_twitter_date(self, date_str: str) -> datetime:
        """Parse Twitter's date format"""
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    
    def _extract_urls(self, tweet: Dict) -> List[str]:
        """Extract URLs from tweet entities"""
        urls = []
        entities = tweet.get('entities', {})
        
        # Extract from URLs
        for url_entity in entities.get('urls', []):
            expanded_url = url_entity.get('expanded_url')
            if expanded_url:
                urls.append(expanded_url)
        
        # Extract from media
        for media in entities.get('media', []):
            media_url = media.get('expanded_url')
            if media_url:
                urls.append(media_url)
        
        return urls
    
    def _extract_hashtags(self, tweet: Dict) -> List[str]:
        """Extract hashtags from tweet"""
        hashtags = []
        entities = tweet.get('entities', {})
        
        for hashtag in entities.get('hashtags', []):
            tag = hashtag.get('text')
            if tag:
                hashtags.append(f"#{tag}")
        
        return hashtags
    
    def _extract_mentions(self, tweet: Dict) -> List[str]:
        """Extract user mentions from tweet"""
        mentions = []
        entities = tweet.get('entities', {})
        
        for mention in entities.get('user_mentions', []):
            screen_name = mention.get('screen_name')
            if screen_name:
                mentions.append(f"@{screen_name}")
        
        return mentions
    
    def _load_tweets_data(self) -> List[Dict]:
        """Load tweets from the archive JS file"""
        tweets_file = self.data_dir / "tweets.js"
        
        if not tweets_file.exists():
            tweets_file = self.data_dir / "tweet.js"
        
        if not tweets_file.exists():
            logger.error(f"No tweets file found in {self.data_dir}")
            return []
        
        with open(tweets_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remove JavaScript wrapper
        content = re.sub(r'^window\.YTD\.tweets?\.part\d+ = ', '', content)
        
        try:
            tweets_data = json.loads(content)
            logger.info(f"Loaded {len(tweets_data)} tweets from archive")
            return tweets_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tweets data: {e}")
            return []
    
    def _process_tweet(self, tweet_data: Dict) -> Optional[Dict]:
        """Process a single tweet into document format"""
        tweet = tweet_data.get('tweet', tweet_data)
        
        # Generate unique ID
        tweet_id = tweet.get('id_str', tweet.get('id'))
        if not tweet_id:
            return None
        
        # Extract basic info
        full_text = tweet.get('full_text', tweet.get('text', ''))
        created_at = tweet.get('created_at')
        
        if not full_text or not created_at:
            return None
        
        # Parse date
        try:
            tweet_date = self._parse_twitter_date(created_at)
        except ValueError:
            logger.warning(f"Failed to parse date for tweet {tweet_id}: {created_at}")
            return None
        
        # Determine tweet type
        is_reply = bool(tweet.get('in_reply_to_status_id'))
        is_retweet = full_text.startswith('RT @')
        
        tweet_type = 'retweet' if is_retweet else ('reply' if is_reply else 'original')
        
        # Extract metadata
        urls = self._extract_urls(tweet)
        hashtags = self._extract_hashtags(tweet)
        mentions = self._extract_mentions(tweet)
        
        # Create document
        doc = {
            'id': f"twitter_{tweet_id}",
            'source': 'twitter',
            'source_id': tweet_id,
            'title': f"Tweet from {tweet_date.strftime('%Y-%m-%d')}",
            'content': full_text,
            'url': f"https://twitter.com/RegenNetwork/status/{tweet_id}",
            'author': 'RegenNetwork',
            'created_at': tweet_date.isoformat(),
            'collected_at': datetime.now().isoformat(),
            'metadata': {
                'type': tweet_type,
                'favorite_count': tweet.get('favorite_count', 0),
                'retweet_count': tweet.get('retweet_count', 0),
                'reply_to_id': tweet.get('in_reply_to_status_id_str'),
                'reply_to_user': tweet.get('in_reply_to_screen_name'),
                'urls': urls,
                'hashtags': hashtags,
                'mentions': mentions,
                'lang': tweet.get('lang', 'en'),
                'source_app': tweet.get('source', ''),
            }
        }
        
        # Generate KOI RID (unique identifier for this tweet)
        koi_content = f"twitter:{tweet_id}:{full_text[:100]}"
        doc['koi_rid'] = hashlib.sha256(koi_content.encode()).hexdigest()[:16]
        
        return doc
    
    async def collect(self, limit: Optional[int] = None, **kwargs) -> List[Dict]:
        """
        Collect and process tweets from archive
        
        Args:
            limit: Maximum number of tweets to process
            **kwargs: Additional options (e.g., filter_replies, filter_retweets)
        
        Returns:
            List of processed tweet documents
        """
        logger.info(f"Starting Twitter archive collection from {self.archive_path}")
        
        # Load tweets data
        tweets_data = self._load_tweets_data()
        
        if not tweets_data:
            logger.warning("No tweets found in archive")
            return []
        
        # Filter options - NOW INCLUDING RETWEETS BY DEFAULT
        include_replies = kwargs.get('include_replies', True)
        include_retweets = kwargs.get('include_retweets', True)  # Changed default to True
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        
        documents = []
        processed = 0
        skipped = 0
        
        for tweet_data in tweets_data:
            if limit and processed >= limit:
                break
            
            # Process tweet
            doc = self._process_tweet(tweet_data)
            
            if not doc:
                skipped += 1
                continue
            
            # Apply filters
            if not include_replies and doc['metadata']['type'] == 'reply':
                skipped += 1
                continue
            
            if not include_retweets and doc['metadata']['type'] == 'retweet':
                skipped += 1
                continue
            
            # Date filtering
            if start_date or end_date:
                tweet_date = datetime.fromisoformat(doc['created_at'])
                if start_date and tweet_date < start_date:
                    skipped += 1
                    continue
                if end_date and tweet_date > end_date:
                    skipped += 1
                    continue
            
            # Save to cache
            cache_path = self.cache_dir / f"twitter_{doc['source_id']}.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Only write if not already cached
            if not cache_path.exists():
                with open(cache_path, 'w') as f:
                    json.dump(doc, f, indent=2)
            
            documents.append(doc)
            
            processed += 1
            
            if processed % 500 == 0:
                logger.info(f"Processed {processed} tweets, skipped {skipped}")
        
        logger.info(f"Twitter collection complete: {processed} tweets processed, {skipped} skipped")
        
        # Sort by date (newest first)
        documents.sort(key=lambda x: x['created_at'], reverse=True)
        
        return documents
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the Twitter archive"""
        tweets_data = self._load_tweets_data()
        
        if not tweets_data:
            return {'error': 'No tweets found'}
        
        stats = {
            'total_tweets': len(tweets_data),
            'original_tweets': 0,
            'replies': 0,
            'retweets': 0,
            'date_range': {'start': None, 'end': None},
            'tweets_by_year': {},
            'top_hashtags': {},
            'top_mentions': {},
        }
        
        dates = []
        hashtag_counts = {}
        mention_counts = {}
        
        for tweet_data in tweets_data:
            tweet = tweet_data.get('tweet', tweet_data)
            
            # Count types
            full_text = tweet.get('full_text', tweet.get('text', ''))
            if full_text.startswith('RT @'):
                stats['retweets'] += 1
            elif tweet.get('in_reply_to_status_id'):
                stats['replies'] += 1
            else:
                stats['original_tweets'] += 1
            
            # Extract date
            created_at = tweet.get('created_at')
            if created_at:
                try:
                    tweet_date = self._parse_twitter_date(created_at)
                    dates.append(tweet_date)
                    
                    # Count by year
                    year = tweet_date.year
                    stats['tweets_by_year'][year] = stats['tweets_by_year'].get(year, 0) + 1
                except ValueError:
                    pass
            
            # Count hashtags
            for hashtag in self._extract_hashtags(tweet):
                hashtag_counts[hashtag] = hashtag_counts.get(hashtag, 0) + 1
            
            # Count mentions
            for mention in self._extract_mentions(tweet):
                mention_counts[mention] = mention_counts.get(mention, 0) + 1
        
        # Set date range
        if dates:
            dates.sort()
            stats['date_range']['start'] = dates[0].strftime('%Y-%m-%d')
            stats['date_range']['end'] = dates[-1].strftime('%Y-%m-%d')
        
        # Top hashtags and mentions
        stats['top_hashtags'] = dict(sorted(hashtag_counts.items(), 
                                           key=lambda x: x[1], reverse=True)[:20])
        stats['top_mentions'] = dict(sorted(mention_counts.items(), 
                                           key=lambda x: x[1], reverse=True)[:20])
        
        return stats