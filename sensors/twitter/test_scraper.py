#!/usr/bin/env python3
"""
Test script for Twitter scraper
This tests the basic functionality of scraping tweets from @regen_network
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from loguru import logger

# Add parent path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from twitter_scraper_playwright import TwitterPlaywrightScraper

async def test_twitter_scraper():
    """
    Test the Twitter scraper with @regen_network account
    """
    logger.info("Starting Twitter scraper test...")
    
    # Initialize scraper
    scraper = TwitterPlaywrightScraper(
        cache_dir=Path("./test_cache"),
        headless=True  # Set to False to see the browser
    )
    
    results = {
        'test_run': datetime.now().isoformat(),
        'account': 'regen_network',
        'tweets': [],
        'replies': [],
        'mentions': [],
        'errors': []
    }
    
    try:
        # Initialize browser
        logger.info("Initializing browser...")
        await scraper.initialize()
        logger.success("Browser initialized successfully")
        
        # Test 1: Scrape user timeline
        logger.info("\n📊 Test 1: Scraping @regen_network timeline...")
        try:
            tweets = await scraper.scrape_user_timeline(
                username="regen_network",
                max_tweets=5,  # Just get 5 tweets for testing
                include_replies=False
            )
            results['tweets'] = tweets
            logger.success(f"✅ Collected {len(tweets)} tweets from timeline")
            
            if tweets:
                logger.info(f"Sample tweet: {tweets[0].get('text', '')[:100]}...")
        except Exception as e:
            error_msg = f"Failed to scrape timeline: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
        
        # Test 2: Scrape replies
        logger.info("\n💬 Test 2: Scraping @regen_network replies...")
        try:
            replies = await scraper.scrape_user_replies(
                username="regen_network",
                max_replies=3  # Just get 3 replies for testing
            )
            results['replies'] = replies
            logger.success(f"✅ Collected {len(replies)} replies")
            
            if replies:
                logger.info(f"Sample reply: {replies[0].get('text', '')[:100]}...")
        except Exception as e:
            error_msg = f"Failed to scrape replies: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
        
        # Test 3: Search for mentions
        logger.info("\n🔍 Test 3: Searching for mentions of @regen_network...")
        try:
            mentions = await scraper.search_mentions(
                username="regen_network",
                max_tweets=3  # Just get 3 mentions for testing
            )
            results['mentions'] = mentions
            logger.success(f"✅ Found {len(mentions)} mentions")
            
            if mentions:
                logger.info(f"Sample mention: {mentions[0].get('text', '')[:100]}...")
        except Exception as e:
            error_msg = f"Failed to search mentions: {e}"
            logger.error(error_msg)
            results['errors'].append(error_msg)
        
        # Save test results
        output_dir = Path("./test_output")
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n📁 Test results saved to: {output_file}")
        
        # Print summary
        logger.info("\n" + "="*50)
        logger.info("📊 TEST SUMMARY")
        logger.info("="*50)
        logger.info(f"✅ Tweets collected: {len(results['tweets'])}")
        logger.info(f"✅ Replies collected: {len(results['replies'])}")
        logger.info(f"✅ Mentions found: {len(results['mentions'])}")
        
        if results['errors']:
            logger.warning(f"⚠️  Errors encountered: {len(results['errors'])}")
            for error in results['errors']:
                logger.warning(f"  - {error}")
        else:
            logger.success("✅ All tests passed successfully!")
        
        return results
        
    except Exception as e:
        logger.error(f"Critical error during testing: {e}")
        results['errors'].append(f"Critical error: {e}")
        return results
        
    finally:
        logger.info("\nClosing browser...")
        await scraper.close()
        logger.info("Browser closed")


def main():
    """
    Run the test
    """
    logger.add("test_scraper.log", rotation="10 MB")
    
    logger.info("="*50)
    logger.info("TWITTER SCRAPER TEST")
    logger.info("="*50)
    
    # Run async test
    results = asyncio.run(test_twitter_scraper())
    
    # Return exit code based on results
    if results['errors']:
        logger.error("❌ Tests completed with errors")
        return 1
    else:
        logger.success("✅ All tests completed successfully")
        return 0


if __name__ == "__main__":
    exit(main())