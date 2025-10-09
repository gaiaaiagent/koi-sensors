#!/usr/bin/env python3
"""
Test script for Playwright functionality in website sensor
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sensors.websites.website_sensor import WebsiteMonitorConfig, WebsiteKOISensor

async def test_playwright_fetch():
    """Test Playwright fetch for regentokenomics.org"""

    print("🧪 Testing Playwright fetch for regentokenomics.org...")
    print()

    # Create minimal config with required fields
    from shared.config.base import KoiNetConfig, APIConfig

    config = WebsiteMonitorConfig(
        sensor_name="website-test",
        platform="test",
        api=APIConfig(),
        koi_net=KoiNetConfig(
            node_name="website-test",
            coordinator_url='http://localhost:8005'
        ),
        websites=[
            {
                "url": "https://regentokenomics.org/weekly-meetups/oct-7",
                "check_interval": 3600
            }
        ],
        playwright_domains=["regentokenomics.org"],
        playwright_expand_toggles=True,
        playwright_wait_time=3000
    )

    # Create sensor
    sensor = WebsiteKOISensor(config)

    try:
        # Initialize Playwright
        await sensor._initialize_playwright()

        if not sensor.browser_context:
            print("❌ Failed to initialize Playwright")
            return

        print("✅ Playwright initialized")
        print()

        # Test fetch
        url = "https://regentokenomics.org/weekly-meetups/oct-7"
        print(f"📜 Fetching: {url}")
        print()

        html_content = await sensor._fetch_with_playwright(url)

        if html_content:
            print(f"✅ Fetched {len(html_content)} characters of HTML")
            print()

            # Parse and extract text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            text_content = sensor.extract_clean_content(soup, url)

            print(f"📝 Extracted {len(text_content)} characters of text")
            print()
            print("=" * 80)
            print("CONTENT PREVIEW (first 2000 chars):")
            print("=" * 80)
            print(text_content[:2000])
            print()
            print("=" * 80)
            print("CONTENT END (last 500 chars):")
            print("=" * 80)
            print(text_content[-500:])
            print()

            # Check if we got the transcript
            if "transcript" in text_content.lower() and len(text_content) > 1000:
                print("✅ SUCCESS: Appears to have captured expanded content!")
            else:
                print("⚠️  WARNING: Content seems limited, toggles may not have expanded")

        else:
            print("❌ Failed to fetch content")

    finally:
        # Cleanup
        if sensor.browser_context:
            await sensor.browser_context.close()
        if sensor.browser:
            await sensor.browser.close()
        if sensor.playwright:
            await sensor.playwright.stop()

        print()
        print("🧹 Cleaned up Playwright resources")

if __name__ == "__main__":
    asyncio.run(test_playwright_fetch())
