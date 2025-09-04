#!/usr/bin/env python3
"""
Quick collection script that saves tweets we already fetched
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from twscrape import API

async def quick_collect():
    """Collect tweets quickly and save them"""
    
    # Initialize API
    api = API()
    
    # Your cookies
    cookies = "auth_token=994ffb9622fc4a8b17a4b7f1e44c53403354477e; ct0=6d95e2203609cc2990e98c960bb90c4fb066cc7f5b0b9df0f3049d095642a221422ad4f6062b0abcc908f0aafbc09800258701455f11bc43e8c562c05c3fa67c814d638c9e9677f03e68fd102cc7280e; guest_id=v1%3A175460676768999756; kdt=70RceDuHWdmwtXtalBI1JP9bKCUVQzXDQbleNKuD; twid=u%3D1752823506524651520"
    
    # Add account
    await api.pool.add_account(
        username="ReFiChat",
        password="dummy",
        email="dummy@example.com",
        email_password="dummy",
        cookies=cookies
    )
    
    # Login
    await api.pool.login_all()
    
    # Get user
    user = await api.user_by_login("regen_network")
    if not user:
        print("User not found")
        return
    
    print(f"Found @{user.username} ({user.followersCount} followers)")
    
    # Collect tweets (limited to avoid rate limit)
    tweets = []
    count = 0
    max_tweets = 25  # Small batch to avoid rate limit
    
    async for tweet in api.user_tweets(user.id, limit=max_tweets):
        count += 1
        
        # Convert to simple dict
        tweet_data = {
            'id': str(tweet.id),
            'date': tweet.date.isoformat() if tweet.date else None,
            'content': tweet.rawContent,
            'likes': tweet.likeCount,
            'retweets': tweet.retweetCount,
            'replies': tweet.replyCount,
            'url': f"https://twitter.com/{user.username}/status/{tweet.id}",
            'hashtags': tweet.hashtags if tweet.hashtags else [],
            'is_retweet': bool(tweet.retweetedTweet),
            'is_reply': bool(tweet.inReplyToTweetId)
        }
        
        tweets.append(tweet_data)
        print(f"  Tweet {count}: {tweet_data['content'][:50]}...")
        
        if count >= max_tweets:
            break
    
    # Save tweets
    output_dir = Path(__file__).parent.parent / 'storage' / 'tweets'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"regen_network_{timestamp}.json"
    
    with open(output_file, 'w') as f:
        json.dump({
            'username': user.username,
            'collected_at': datetime.now().isoformat(),
            'tweet_count': len(tweets),
            'tweets': tweets
        }, f, indent=2)
    
    print(f"\n✓ Saved {len(tweets)} tweets to {output_file}")
    
    # Also save to main documents directory
    docs_dir = Path(__file__).parent.parent.parent / 'storage' / 'documents'
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert to document format
    for tweet in tweets[:10]:  # Save first 10 as documents
        doc = {
            'id': f"twitter_{tweet['id']}",
            'source': 'twitter:regen_network',
            'source_type': 'twitter',
            'url': tweet['url'],
            'title': f"Tweet by @regen_network",
            'content': tweet['content'],
            'metadata': {
                'likes': tweet['likes'],
                'retweets': tweet['retweets'],
                'replies': tweet['replies'],
                'hashtags': tweet['hashtags']
            },
            'collected_at': datetime.now().isoformat(),
            'last_modified': tweet['date'],
            'author': '@regen_network',
            'tags': ['twitter', 'social_media', 'regen_network']
        }
        
        doc_file = docs_dir / f"twitter_{tweet['id']}.json"
        with open(doc_file, 'w') as f:
            json.dump(doc, f, indent=2)
    
    print(f"✓ Saved {min(10, len(tweets))} documents to main storage")

if __name__ == "__main__":
    asyncio.run(quick_collect())