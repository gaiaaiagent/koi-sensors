#!/usr/bin/env python3
"""
Simple test to verify Twitter scraping works
"""

import ntscraper
import json

def test_ntscraper():
    """Test ntscraper directly"""
    print("Testing ntscraper...")
    
    # Create instance
    scraper = ntscraper.Nitter()
    
    # Try to get tweets from regen_network
    print("Fetching tweets from @regen_network...")
    
    try:
        # Get user tweets
        tweets = scraper.get_tweets("regen_network", mode="user", number=5)
        
        if tweets and 'tweets' in tweets:
            print(f"Found {len(tweets['tweets'])} tweets!")
            for i, tweet in enumerate(tweets['tweets'][:3], 1):
                print(f"\nTweet {i}:")
                print(f"  Text: {tweet.get('text', 'N/A')[:100]}...")
                print(f"  Date: {tweet.get('date', 'N/A')}")
                print(f"  Link: {tweet.get('link', 'N/A')}")
        else:
            print("No tweets found")
            print(f"Response: {tweets}")
            
    except Exception as e:
        print(f"Error: {e}")
        print("\nTrying with different Nitter instance...")
        
        # Try with different instances
        instances = ntscraper.get_instances()
        print(f"Available instances: {len(instances)}")
        
        for instance in instances[:3]:
            print(f"\nTrying {instance}...")
            scraper = ntscraper.Nitter(instance)
            try:
                tweets = scraper.get_tweets("regen_network", mode="user", number=2)
                if tweets and 'tweets' in tweets and tweets['tweets']:
                    print(f"Success with {instance}!")
                    print(f"Got {len(tweets['tweets'])} tweets")
                    break
            except:
                print(f"Failed with {instance}")
                continue

if __name__ == "__main__":
    test_ntscraper()