#!/usr/bin/env python3
"""
Process Twitter/X archive export to extract and index all tweets
This is the recommended approach - no rate limits, complete history
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import zipfile
import re
from loguru import logger

# Add parent directories to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from collectors.base_collector import Document


class TwitterArchiveProcessor:
    """
    Process Twitter/X archive export files
    """
    
    def __init__(self, archive_path: str):
        """
        Initialize the processor
        
        Args:
            archive_path: Path to the Twitter archive .zip or extracted folder
        """
        self.archive_path = Path(archive_path)
        self.documents = []
        self.stats = {
            'total_tweets': 0,
            'retweets': 0,
            'replies': 0,
            'quotes': 0,
            'media_tweets': 0,
            'date_range': {'start': None, 'end': None}
        }
        
        # Output directories
        self.output_dir = Path(__file__).parent.parent / 'storage' / 'archive'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def process(self) -> List[Document]:
        """
        Process the Twitter archive
        
        Returns:
            List of Document objects
        """
        logger.info(f"Processing Twitter archive: {self.archive_path}")
        
        # Check if it's a zip file or directory
        if self.archive_path.suffix == '.zip':
            return self.process_zip()
        elif self.archive_path.is_dir():
            return self.process_directory()
        else:
            logger.error(f"Invalid archive path: {self.archive_path}")
            return []
    
    def process_zip(self) -> List[Document]:
        """
        Process a .zip archive file
        """
        logger.info("Extracting zip archive...")
        
        # Extract to temp directory
        extract_dir = self.output_dir / 'extracted'
        extract_dir.mkdir(exist_ok=True)
        
        with zipfile.ZipFile(self.archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # Process the extracted directory
        return self.process_directory(extract_dir)
    
    def process_directory(self, directory: Path = None) -> List[Document]:
        """
        Process an extracted archive directory
        """
        if directory is None:
            directory = self.archive_path
        
        # Find tweets.js or tweet.js file
        tweets_file = None
        for pattern in ['**/tweets.js', '**/tweet.js', '**/data/tweets.js', '**/data/tweet.js']:
            matches = list(directory.glob(pattern))
            if matches:
                tweets_file = matches[0]
                break
        
        if not tweets_file:
            logger.error("Could not find tweets.js in archive")
            return []
        
        logger.info(f"Found tweets file: {tweets_file}")
        
        # Read and parse tweets
        tweets_data = self.read_tweets_js(tweets_file)
        
        # Convert to documents
        for tweet_obj in tweets_data:
            doc = self.tweet_to_document(tweet_obj)
            if doc:
                self.documents.append(doc)
        
        # Print statistics
        self.print_stats()
        
        # Save documents
        self.save_documents()
        
        return self.documents
    
    def read_tweets_js(self, file_path: Path) -> List[Dict]:
        """
        Read and parse the tweets.js file
        
        Twitter exports have a JavaScript variable assignment at the start
        that needs to be stripped
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Remove JavaScript variable assignment
        # Usually starts with "window.YTD.tweets.part0 = " or similar
        json_start = content.find('[')
        if json_start == -1:
            json_start = content.find('{')
        
        if json_start != -1:
            content = content[json_start:]
        
        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse tweets JSON: {e}")
            # Try to fix common issues
            content = re.sub(r'window\.YTD\.tweets\.part\d+\s*=\s*', '', content)
            content = re.sub(r'window\.YTD\.tweet\.part\d+\s*=\s*', '', content)
            data = json.loads(content)
        
        logger.info(f"Loaded {len(data)} tweets from archive")
        return data
    
    def tweet_to_document(self, tweet_obj: Dict) -> Document:
        """
        Convert a tweet from the archive to a Document
        
        Args:
            tweet_obj: Tweet object from Twitter archive
            
        Returns:
            Document object
        """
        try:
            # Twitter archive structure has tweet nested
            if 'tweet' in tweet_obj:
                tweet = tweet_obj['tweet']
            else:
                tweet = tweet_obj
            
            # Extract basic info
            tweet_id = tweet.get('id', tweet.get('id_str', ''))
            created_at = tweet.get('created_at', '')
            
            # Parse date
            if created_at:
                # Twitter format: "Wed Oct 10 20:19:24 +0000 2018"
                try:
                    date_obj = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
                except:
                    # Alternative format
                    date_obj = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S %z")
            else:
                date_obj = None
            
            # Get full text (handle extended tweets)
            content = tweet.get('full_text', tweet.get('text', ''))
            
            # Extract metadata
            metadata = {
                'tweet_id': tweet_id,
                'created_at': created_at,
                'retweet_count': tweet.get('retweet_count', 0),
                'favorite_count': tweet.get('favorite_count', 0),
                'reply_count': tweet.get('reply_count', 0),
                'quote_count': tweet.get('quote_count', 0),
                'lang': tweet.get('lang', ''),
                'source': tweet.get('source', ''),
                'possibly_sensitive': tweet.get('possibly_sensitive', False)
            }
            
            # Extract entities
            entities = tweet.get('entities', {})
            metadata['hashtags'] = [h['text'] for h in entities.get('hashtags', [])]
            metadata['mentions'] = [m['screen_name'] for m in entities.get('user_mentions', [])]
            metadata['urls'] = [u['expanded_url'] for u in entities.get('urls', [])]
            
            # Check for media
            if 'media' in entities:
                metadata['media'] = [m['media_url_https'] for m in entities['media']]
                self.stats['media_tweets'] += 1
            
            # Check tweet type
            if tweet.get('in_reply_to_status_id'):
                metadata['is_reply'] = True
                self.stats['replies'] += 1
            else:
                metadata['is_reply'] = False
            
            if content.startswith('RT @'):
                metadata['is_retweet'] = True
                self.stats['retweets'] += 1
            else:
                metadata['is_retweet'] = False
            
            if tweet.get('is_quote_status'):
                metadata['is_quote'] = True
                self.stats['quotes'] += 1
            else:
                metadata['is_quote'] = False
            
            # Update stats
            self.stats['total_tweets'] += 1
            if date_obj:
                if not self.stats['date_range']['start'] or date_obj < self.stats['date_range']['start']:
                    self.stats['date_range']['start'] = date_obj
                if not self.stats['date_range']['end'] or date_obj > self.stats['date_range']['end']:
                    self.stats['date_range']['end'] = date_obj
            
            # Create document
            doc = Document(
                id=f"twitter_archive_{tweet_id}",
                source="twitter:regen_network",
                source_type="twitter",
                url=f"https://twitter.com/regen_network/status/{tweet_id}",
                title=f"Tweet by @regen_network - {content[:50]}..." if len(content) > 50 else f"Tweet by @regen_network",
                content=content,
                metadata=metadata,
                collected_at=datetime.now(),
                last_modified=date_obj,
                author="@regen_network",
                tags=['twitter', 'archive', 'regen_network'] + metadata.get('hashtags', [])
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error converting tweet to document: {e}")
            return None
    
    def print_stats(self):
        """Print processing statistics"""
        print("\n" + "="*60)
        print("Twitter Archive Processing Statistics")
        print("="*60)
        print(f"Total tweets: {self.stats['total_tweets']:,}")
        print(f"  Regular tweets: {self.stats['total_tweets'] - self.stats['retweets'] - self.stats['replies']:,}")
        print(f"  Retweets: {self.stats['retweets']:,}")
        print(f"  Replies: {self.stats['replies']:,}")
        print(f"  Quote tweets: {self.stats['quotes']:,}")
        print(f"  With media: {self.stats['media_tweets']:,}")
        
        if self.stats['date_range']['start'] and self.stats['date_range']['end']:
            print(f"\nDate range:")
            print(f"  First tweet: {self.stats['date_range']['start'].strftime('%Y-%m-%d')}")
            print(f"  Last tweet: {self.stats['date_range']['end'].strftime('%Y-%m-%d')}")
            
            # Calculate posting frequency
            days = (self.stats['date_range']['end'] - self.stats['date_range']['start']).days
            if days > 0:
                tweets_per_day = self.stats['total_tweets'] / days
                print(f"  Average: {tweets_per_day:.1f} tweets/day")
        
        print("="*60)
    
    def save_documents(self):
        """Save documents to storage"""
        if not self.documents:
            logger.warning("No documents to save")
            return
        
        # Save to main storage
        storage_dir = Path(__file__).parent.parent.parent / 'storage' / 'documents'
        storage_dir.mkdir(parents=True, exist_ok=True)
        
        saved_count = 0
        for doc in self.documents:
            doc_file = storage_dir / f"{doc.id}.json"
            with open(doc_file, 'w') as f:
                f.write(doc.to_json())
            saved_count += 1
        
        logger.info(f"Saved {saved_count} documents to {storage_dir}")
        
        # Also save a complete archive JSON
        archive_file = self.output_dir / f"twitter_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(archive_file, 'w') as f:
            json.dump({
                'source': 'twitter_archive',
                'processed_at': datetime.now().isoformat(),
                'stats': self.stats,
                'document_count': len(self.documents),
                'documents': [json.loads(doc.to_json()) for doc in self.documents]
            }, f, indent=2, default=str)
        
        logger.info(f"Saved complete archive to {archive_file}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Process Twitter/X archive')
    parser.add_argument(
        'archive_path',
        help='Path to Twitter archive (.zip file or extracted directory)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of tweets to process'
    )
    
    args = parser.parse_args()
    
    if not Path(args.archive_path).exists():
        print(f"Error: Archive not found: {args.archive_path}")
        print("\nPlease provide the path to:")
        print("  1. The .zip file downloaded from Twitter, OR")
        print("  2. The extracted archive directory")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("Twitter/X Archive Processor")
    print("="*60)
    print(f"Archive: {args.archive_path}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Process archive
    processor = TwitterArchiveProcessor(args.archive_path)
    documents = processor.process()
    
    if args.limit and len(documents) > args.limit:
        documents = documents[:args.limit]
        print(f"\nLimited to {args.limit} documents")
    
    print(f"\n✓ Successfully processed {len(documents)} tweets")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()