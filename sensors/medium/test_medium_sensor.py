#!/usr/bin/env python3
"""
Test suite for Medium KOI Sensor
Tests RSS collection, web scraping, and KOI integration
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

async def test_standalone_sensor():
    """Test the standalone Medium sensor"""
    print("\n" + "="*60)
    print("TEST 1: STANDALONE MEDIUM SENSOR")
    print("="*60)
    
    from medium_sensor_standalone import StandaloneMediumSensor
    
    sensor = StandaloneMediumSensor()
    
    # Test with limited articles
    articles = await sensor.collect_articles(limit=3)
    
    if articles:
        print(f"✅ Successfully collected {len(articles)} articles")
        for article in articles:
            print(f"  - {article['title'][:50]}...")
            print(f"    Words: {article['word_count']}, Tags: {len(article['tags'])}")
    else:
        print("❌ No articles collected")
    
    return len(articles) > 0


async def test_rss_collection():
    """Test RSS feed collection"""
    print("\n" + "="*60)
    print("TEST 2: RSS FEED COLLECTION")
    print("="*60)
    
    import aiohttp
    import feedparser
    
    rss_url = "https://medium.com/feed/@regen-network"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(rss_url) as response:
                if response.status == 200:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    print(f"Feed title: {feed.feed.get('title', 'Unknown')}")
                    print(f"Number of entries: {len(feed.entries)}")
                    
                    if feed.entries:
                        print("\nRecent articles from RSS:")
                        for i, entry in enumerate(feed.entries[:5], 1):
                            print(f"{i}. {entry.get('title', 'No title')}")
                            print(f"   Link: {entry.get('link', 'No link')}")
                            print(f"   Published: {entry.get('published', 'Unknown')}")
                        
                        print(f"\n✅ RSS feed working - {len(feed.entries)} articles available")
                        return True
                    else:
                        print("❌ RSS feed empty")
                        return False
                else:
                    print(f"❌ RSS feed returned status {response.status}")
                    return False
        except Exception as e:
            print(f"❌ RSS feed error: {e}")
            return False


async def test_article_extraction():
    """Test article content extraction"""
    print("\n" + "="*60)
    print("TEST 3: ARTICLE CONTENT EXTRACTION")
    print("="*60)
    
    from medium_sensor_standalone import StandaloneMediumSensor
    
    sensor = StandaloneMediumSensor()
    
    # Use a known Medium article URL for testing
    test_url = "https://medium.com/@regen-network"
    
    print(f"Testing content extraction from: {test_url}")
    
    session = aiohttp.ClientSession()
    sensor.session = session
    
    try:
        # First get article URLs
        article_urls = await sensor.collect_from_rss()
        
        if article_urls:
            # Test processing first article
            first_url = list(article_urls)[0]
            print(f"\nProcessing article: {first_url}")
            
            article = await sensor.process_article(first_url)
            
            if article:
                print(f"✅ Article extracted successfully:")
                print(f"  Title: {article['title'][:60]}...")
                print(f"  Author: {article['author']}")
                print(f"  Word count: {article['word_count']}")
                print(f"  Tags: {', '.join(article['tags'])}")
                print(f"  Content preview: {article['content'][:200]}...")
                return True
            else:
                print("❌ Failed to extract article content")
                return False
        else:
            print("❌ No article URLs found")
            return False
    
    finally:
        await session.close()


async def test_koi_integration():
    """Test KOI Event Bridge integration"""
    print("\n" + "="*60)
    print("TEST 4: KOI EVENT BRIDGE INTEGRATION")
    print("="*60)
    
    try:
        # Try to import KOI modules
        from medium_sensor import MediumKOISensor, MediumMonitorConfig, MediumArticleRID
        from shared.config.base import KoiNetConfig, MonitoringConfig, APIConfig
        
        print("✅ KOI modules imported successfully")
        
        # Test RID generation
        test_url = "https://medium.com/@regen-network/test-article-123abc"
        rid = MediumArticleRID(test_url)
        print(f"✅ RID generated: {rid.to_string()}")
        
        # Test configuration
        config = MediumMonitorConfig(
            sensor_name="medium-test",
            platform="medium",
            api=APIConfig(),
            koi_net=KoiNetConfig(
                node_name="medium-test-sensor",
                coordinator_url="http://localhost:8000"
            ),
            monitoring=MonitoringConfig(log_level="INFO")
        )
        
        print("✅ Configuration created successfully")
        
        # Create sensor instance (don't start it)
        sensor = MediumKOISensor(config)
        print("✅ KOI sensor instantiated successfully")
        
        # Test auto-tagging
        test_content = "This article discusses governance proposals and ecocredits in the marketplace"
        tags = sensor.generate_auto_tags(test_content)
        print(f"✅ Auto-tags generated: {tags}")
        
        return True
        
    except ImportError as e:
        print(f"⚠️  KOI integration not available (expected if KOI not installed): {e}")
        return False
    except Exception as e:
        print(f"❌ KOI integration error: {e}")
        return False


async def test_scraping_fallback():
    """Test web scraping as fallback when RSS fails"""
    print("\n" + "="*60)
    print("TEST 5: WEB SCRAPING FALLBACK")
    print("="*60)
    
    from medium_sensor_standalone import StandaloneMediumSensor
    import aiohttp
    
    sensor = StandaloneMediumSensor()
    sensor.session = aiohttp.ClientSession()
    
    try:
        # Try scraping the main page
        article_urls = await sensor.scrape_for_articles()
        
        if article_urls:
            print(f"✅ Found {len(article_urls)} articles via scraping")
            for i, url in enumerate(list(article_urls)[:3], 1):
                print(f"  {i}. {url}")
            return True
        else:
            print("⚠️  No articles found via scraping (may need browser automation)")
            return False
    
    finally:
        await sensor.session.close()


async def main():
    """Run all tests"""
    print("="*60)
    print("MEDIUM SENSOR TEST SUITE")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60)
    
    # Check required packages
    required_packages = {'aiohttp': 'aiohttp', 'beautifulsoup4': 'bs4', 'html2text': 'html2text', 'feedparser': 'feedparser'}
    missing_packages = []
    
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)
    
    if missing_packages:
        print(f"\n⚠️  Missing packages: {', '.join(missing_packages)}")
        print("Install with: pip install " + ' '.join(missing_packages))
        print("\nOr run the standalone script which auto-installs dependencies:")
        print("  python medium_sensor_standalone.py")
        return
    
    # Run tests
    test_results = []
    
    # Test 1: Standalone sensor
    try:
        result = await test_standalone_sensor()
        test_results.append(("Standalone Sensor", result))
    except Exception as e:
        print(f"❌ Standalone sensor test failed: {e}")
        test_results.append(("Standalone Sensor", False))
    
    # Test 2: RSS collection
    try:
        result = await test_rss_collection()
        test_results.append(("RSS Collection", result))
    except Exception as e:
        print(f"❌ RSS test failed: {e}")
        test_results.append(("RSS Collection", False))
    
    # Test 3: Article extraction
    try:
        result = await test_article_extraction()
        test_results.append(("Article Extraction", result))
    except Exception as e:
        print(f"❌ Article extraction test failed: {e}")
        test_results.append(("Article Extraction", False))
    
    # Test 4: KOI integration
    try:
        result = await test_koi_integration()
        test_results.append(("KOI Integration", result))
    except Exception as e:
        print(f"❌ KOI integration test failed: {e}")
        test_results.append(("KOI Integration", False))
    
    # Test 5: Scraping fallback
    try:
        result = await test_scraping_fallback()
        test_results.append(("Scraping Fallback", result))
    except Exception as e:
        print(f"❌ Scraping test failed: {e}")
        test_results.append(("Scraping Fallback", False))
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in test_results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<30} {status}")
    
    passed_count = sum(1 for _, passed in test_results if passed)
    total_count = len(test_results)
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! Medium sensor is ready.")
    elif passed_count >= 3:
        print("\n✅ Core functionality working. Some features may need attention.")
    else:
        print("\n⚠️  Several tests failed. Please review the errors above.")


if __name__ == "__main__":
    import sys
    
    # Check for --import flag to just import modules
    if len(sys.argv) > 1 and sys.argv[1] == "--import":
        print("Testing imports only...")
        try:
            from medium_sensor_standalone import StandaloneMediumSensor
            print("✅ Standalone sensor imported")
        except ImportError as e:
            print(f"❌ Failed to import standalone sensor: {e}")
        
        try:
            from medium_sensor import MediumKOISensor
            print("✅ KOI sensor imported")
        except ImportError as e:
            print(f"⚠️  KOI sensor not available: {e}")
    else:
        asyncio.run(main())