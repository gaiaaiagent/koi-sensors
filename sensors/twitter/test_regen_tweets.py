#!/usr/bin/env python3
"""
Test script specifically for scraping @regen_network tweets
This script tests how many tweets we can access and saves them
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
import sys

# Try using Playwright with direct browser access
from playwright.async_api import async_playwright

async def test_regen_network_scraping():
    """
    Test scraping @regen_network tweets using Playwright
    """
    print("="*60)
    print("TESTING TWITTER SCRAPER FOR @regen_network")
    print("="*60)
    
    browser = None
    tweets_collected = []
    
    try:
        print("\n[1/5] Starting Playwright...")
        playwright = await async_playwright().start()
        
        print("[2/5] Launching browser (this may take a moment)...")
        # Launch browser with more options for stability
        browser = await playwright.chromium.launch(
            headless=False,  # Set to False so we can see what's happening
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        print("[3/5] Creating browser context...")
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = await context.new_page()
        
        print("[4/5] Navigating to @regen_network Twitter profile...")
        # Try Twitter/X URL
        url = "https://x.com/regen_network"
        print(f"    URL: {url}")
        
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            print("    ✓ Page loaded")
        except Exception as e:
            print(f"    ✗ Error loading page: {e}")
            # Try alternative URL
            url = "https://twitter.com/regen_network"
            print(f"    Trying alternative URL: {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        
        # Wait a bit for content to load
        print("[5/5] Waiting for tweets to load...")
        await asyncio.sleep(5)
        
        # Try to detect if we need to handle any popups or login prompts
        print("\nChecking page state...")
        
        # Check if tweets are visible
        try:
            # Wait for tweet articles to appear
            await page.wait_for_selector('article', timeout=10000)
            print("    ✓ Tweet elements found")
            
            # Scroll to load more tweets
            print("\nScrolling to load more tweets...")
            for i in range(5):  # Scroll 5 times
                print(f"    Scroll {i+1}/5...")
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(2)
            
            # Extract tweet data
            print("\nExtracting tweet data...")
            
            # Get all tweet articles
            tweet_elements = await page.query_selector_all('article')
            print(f"    Found {len(tweet_elements)} tweet elements")
            
            for idx, element in enumerate(tweet_elements):
                try:
                    # Extract text content
                    text_content = await element.inner_text()
                    
                    # Try to extract tweet text specifically
                    tweet_text_element = await element.query_selector('[data-testid="tweetText"]')
                    tweet_text = ""
                    if tweet_text_element:
                        tweet_text = await tweet_text_element.inner_text()
                    
                    # Try to extract timestamp
                    time_element = await element.query_selector('time')
                    timestamp = ""
                    if time_element:
                        timestamp = await time_element.get_attribute('datetime')
                    
                    # Extract metrics if available
                    metrics = {}
                    
                    # Save tweet data
                    if tweet_text:
                        tweet_data = {
                            'index': idx,
                            'text': tweet_text,
                            'timestamp': timestamp,
                            'full_content': text_content[:500],  # First 500 chars
                            'scraped_at': datetime.now().isoformat()
                        }
                        tweets_collected.append(tweet_data)
                        
                        # Print first few tweets
                        if idx < 3:
                            print(f"\n    Tweet {idx+1}:")
                            print(f"      Text: {tweet_text[:100]}...")
                            if timestamp:
                                print(f"      Time: {timestamp}")
                
                except Exception as e:
                    print(f"    Error extracting tweet {idx}: {e}")
            
        except Exception as e:
            print(f"    ✗ Could not find tweets: {e}")
            
            # Take a screenshot for debugging
            screenshot_path = Path("./twitter_debug.png")
            await page.screenshot(path=str(screenshot_path))
            print(f"    Screenshot saved to: {screenshot_path}")
            
            # Check page content
            page_content = await page.content()
            print(f"    Page title: {await page.title()}")
            
            # Check for common issues
            if "login" in page_content.lower():
                print("    ⚠️  Login page detected - Twitter may require authentication")
            elif "suspended" in page_content.lower():
                print("    ⚠️  Account may be suspended or restricted")
            elif "not found" in page_content.lower():
                print("    ⚠️  Account not found")
            else:
                print("    ⚠️  Unknown page state")
        
        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"✓ Tweets collected: {len(tweets_collected)}")
        
        if tweets_collected:
            # Save to file
            output_dir = Path("./output")
            output_dir.mkdir(exist_ok=True)
            
            output_file = output_dir / f"regen_tweets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    'account': 'regen_network',
                    'tweets_count': len(tweets_collected),
                    'tweets': tweets_collected,
                    'scraped_at': datetime.now().isoformat()
                }, f, indent=2)
            
            print(f"✓ Results saved to: {output_file}")
            
            # Analyze date range
            if tweets_collected:
                timestamps = [t['timestamp'] for t in tweets_collected if t.get('timestamp')]
                if timestamps:
                    timestamps.sort()
                    print(f"✓ Date range: {timestamps[0][:10]} to {timestamps[-1][:10]}")
        else:
            print("✗ No tweets collected")
            print("\nPossible reasons:")
            print("  - Twitter requires login for this content")
            print("  - Rate limiting or IP blocking")
            print("  - Page structure has changed")
            print("  - Network issues")
        
        print("\nPress Enter to close the browser...")
        input()
        
    except Exception as e:
        print(f"\n✗ Error during scraping: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if browser:
            print("\nClosing browser...")
            await browser.close()
        
        if 'playwright' in locals():
            await playwright.stop()
    
    return tweets_collected


async def test_with_alternative_method():
    """
    Test using alternative scraping method (nitter instances)
    """
    print("\n" + "="*60)
    print("TESTING ALTERNATIVE METHOD (Nitter)")
    print("="*60)
    
    import httpx
    
    # List of public Nitter instances
    nitter_instances = [
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.esmailelbob.xyz",
        "https://nitter.woodland.cafe"
    ]
    
    tweets = []
    
    for instance in nitter_instances:
        try:
            print(f"\nTrying {instance}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{instance}/regen_network")
                
                if response.status_code == 200:
                    print(f"  ✓ Connected to {instance}")
                    # Parse the response (would need BeautifulSoup here)
                    # For now, just check if we can connect
                    content = response.text
                    if "regen_network" in content.lower():
                        print(f"  ✓ Found @regen_network profile")
                        # Count approximate tweets (rough estimate)
                        tweet_count = content.count('class="tweet-')
                        print(f"  ✓ Approximate tweets visible: {tweet_count}")
                    break
                else:
                    print(f"  ✗ Status code: {response.status_code}")
                    
        except Exception as e:
            print(f"  ✗ Failed: {e}")
    
    return tweets


async def main():
    """
    Run all tests
    """
    print("Twitter Scraper Test for @regen_network")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("")
    
    # Test 1: Playwright method
    tweets = await test_regen_network_scraping()
    
    # Test 2: Alternative method
    # await test_with_alternative_method()
    
    return tweets


if __name__ == "__main__":
    # Run the test
    tweets = asyncio.run(main())
    print(f"\nTest completed. Total tweets collected: {len(tweets)}")