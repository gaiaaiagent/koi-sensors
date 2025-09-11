#!/usr/bin/env python3
"""
Comprehensive scraper for @regen_network tweets
This script attempts to collect as many tweets as possible
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

async def scrape_all_regen_tweets():
    """
    Scrape as many @regen_network tweets as possible
    """
    print("="*60)
    print("COMPREHENSIVE TWITTER SCRAPER FOR @regen_network")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    browser = None
    all_tweets = []
    unique_tweets = set()
    
    try:
        print("\n[1/6] Starting Playwright...")
        playwright = await async_playwright().start()
        
        print("[2/6] Launching browser in headless mode...")
        browser = await playwright.chromium.launch(
            headless=True,  # Run headless for automated scraping
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ]
        )
        
        print("[3/6] Creating browser context...")
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        print("[4/6] Navigating to @regen_network profile...")
        await page.goto("https://x.com/regen_network", wait_until='domcontentloaded', timeout=30000)
        
        # Wait for initial tweets to load
        print("[5/6] Waiting for tweets to load...")
        await page.wait_for_selector('article', timeout=15000)
        await asyncio.sleep(3)
        
        print("[6/6] Scrolling and collecting tweets...")
        print("    This may take several minutes...")
        
        no_new_tweets_count = 0
        scroll_count = 0
        max_scrolls = 50  # Maximum number of scrolls to prevent infinite loop
        
        while scroll_count < max_scrolls:
            # Get current tweets
            tweet_elements = await page.query_selector_all('article[data-testid="tweet"]')
            
            current_batch_tweets = []
            for element in tweet_elements:
                try:
                    # Extract tweet text
                    tweet_text_element = await element.query_selector('[data-testid="tweetText"]')
                    if not tweet_text_element:
                        continue
                    
                    tweet_text = await tweet_text_element.inner_text()
                    
                    # Skip if we've already seen this tweet
                    if tweet_text in unique_tweets:
                        continue
                    
                    unique_tweets.add(tweet_text)
                    
                    # Extract timestamp
                    time_element = await element.query_selector('time')
                    timestamp = ""
                    if time_element:
                        timestamp = await time_element.get_attribute('datetime')
                    
                    # Extract metrics
                    metrics = {}
                    
                    # Like count
                    like_element = await element.query_selector('[data-testid="like"]')
                    if like_element:
                        like_text = await like_element.inner_text()
                        # Clean and extract number
                        like_count = ''.join(filter(str.isdigit, like_text))
                        metrics['likes'] = int(like_count) if like_count else 0
                    
                    # Retweet count
                    retweet_element = await element.query_selector('[data-testid="retweet"]')
                    if retweet_element:
                        retweet_text = await retweet_element.inner_text()
                        retweet_count = ''.join(filter(str.isdigit, retweet_text))
                        metrics['retweets'] = int(retweet_count) if retweet_count else 0
                    
                    # Reply count
                    reply_element = await element.query_selector('[data-testid="reply"]')
                    if reply_element:
                        reply_text = await reply_element.inner_text()
                        reply_count = ''.join(filter(str.isdigit, reply_text))
                        metrics['replies'] = int(reply_count) if reply_count else 0
                    
                    # Extract user info to verify it's from @regen_network
                    user_element = await element.query_selector('[data-testid="User-Name"]')
                    is_regen = False
                    if user_element:
                        user_text = await user_element.inner_text()
                        if "regen_network" in user_text.lower():
                            is_regen = True
                    
                    # Only add if it's from @regen_network
                    if is_regen:
                        tweet_data = {
                            'text': tweet_text,
                            'timestamp': timestamp,
                            'metrics': metrics,
                            'scraped_at': datetime.now().isoformat()
                        }
                        current_batch_tweets.append(tweet_data)
                        all_tweets.append(tweet_data)
                
                except Exception as e:
                    # Silently skip problematic tweets
                    pass
            
            # Check if we got new tweets
            if len(current_batch_tweets) == 0:
                no_new_tweets_count += 1
                if no_new_tweets_count >= 3:
                    print(f"    No new tweets found after {scroll_count} scrolls. Stopping...")
                    break
            else:
                no_new_tweets_count = 0
                print(f"    Scroll {scroll_count + 1}: Collected {len(current_batch_tweets)} new tweets (Total: {len(all_tweets)})")
            
            # Scroll down
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)  # Wait for new content to load
            
            scroll_count += 1
            
            # Optional: Save progress periodically
            if scroll_count % 10 == 0:
                print(f"    Progress saved: {len(all_tweets)} tweets collected so far...")
        
        print(f"\n✓ Scraping completed after {scroll_count} scrolls")
        
    except Exception as e:
        print(f"\n✗ Error during scraping: {e}")
    
    finally:
        if browser:
            await browser.close()
        if 'playwright' in locals():
            await playwright.stop()
    
    return all_tweets


def analyze_tweets(tweets):
    """
    Analyze the collected tweets
    """
    print("\n" + "="*60)
    print("TWEET ANALYSIS")
    print("="*60)
    
    if not tweets:
        print("No tweets to analyze")
        return
    
    print(f"Total tweets collected: {len(tweets)}")
    
    # Date range analysis
    timestamps = []
    for tweet in tweets:
        if tweet.get('timestamp'):
            try:
                dt = datetime.fromisoformat(tweet['timestamp'].replace('Z', '+00:00'))
                timestamps.append(dt)
            except:
                pass
    
    if timestamps:
        timestamps.sort()
        oldest = timestamps[0]
        newest = timestamps[-1]
        
        print(f"\nDate range:")
        print(f"  Oldest tweet: {oldest.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Newest tweet: {newest.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Time span: {(newest - oldest).days} days")
        
        # Group by year
        years = {}
        for ts in timestamps:
            year = ts.year
            if year not in years:
                years[year] = 0
            years[year] += 1
        
        print(f"\nTweets by year:")
        for year in sorted(years.keys()):
            print(f"  {year}: {years[year]} tweets")
    
    # Engagement analysis
    total_likes = sum(t.get('metrics', {}).get('likes', 0) for t in tweets)
    total_retweets = sum(t.get('metrics', {}).get('retweets', 0) for t in tweets)
    total_replies = sum(t.get('metrics', {}).get('replies', 0) for t in tweets)
    
    if len(tweets) > 0:
        print(f"\nEngagement metrics:")
        print(f"  Total likes: {total_likes:,}")
        print(f"  Total retweets: {total_retweets:,}")
        print(f"  Total replies: {total_replies:,}")
        print(f"  Average likes per tweet: {total_likes/len(tweets):.1f}")
        print(f"  Average retweets per tweet: {total_retweets/len(tweets):.1f}")
    
    # Top tweets by engagement
    sorted_tweets = sorted(tweets, 
                          key=lambda t: t.get('metrics', {}).get('likes', 0), 
                          reverse=True)
    
    print(f"\nTop 3 most liked tweets:")
    for i, tweet in enumerate(sorted_tweets[:3], 1):
        likes = tweet.get('metrics', {}).get('likes', 0)
        text_preview = tweet['text'][:100] + "..." if len(tweet['text']) > 100 else tweet['text']
        print(f"  {i}. ({likes} likes) {text_preview}")


async def main():
    """
    Main function
    """
    # Scrape tweets
    tweets = await scrape_all_regen_tweets()
    
    # Save results
    if tweets:
        output_dir = Path("./output")
        output_dir.mkdir(exist_ok=True)
        
        filename = f"regen_all_tweets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_file = output_dir / filename
        
        with open(output_file, 'w') as f:
            json.dump({
                'account': 'regen_network',
                'total_tweets': len(tweets),
                'tweets': tweets,
                'scraped_at': datetime.now().isoformat()
            }, f, indent=2)
        
        print(f"\n✓ Results saved to: {output_file}")
    
    # Analyze tweets
    analyze_tweets(tweets)
    
    print("\n" + "="*60)
    print("SCRAPING COMPLETE")
    print("="*60)
    print(f"Total tweets collected: {len(tweets)}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())