#!/usr/bin/env python3
"""
Test Website Sensor in Standalone Mode (without coordinator)
Shows how sensors can work independently for testing/development
"""

import asyncio
import logging
import yaml
import sys
from pathlib import Path

# Add parent directories to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sensors.websites.website_sensor import WebsiteKOISensor, WebsiteMonitorConfig
from koi_protocol.core.rid_system import WebPageRID

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StandaloneWebsiteSensor:
    """Simplified website sensor for standalone testing"""
    
    def __init__(self):
        self.page_hashes = {}
        
    async def test_rid_generation(self):
        """Test RID generation for different websites"""
        test_urls = [
            "https://docs.regen.network/getting-started",
            "https://guides.regen.network/validators",
            "https://registry.regen.network/credit-classes/C01",
            "https://www.regen.foundation/publications"
        ]
        
        print("=== Testing RID Generation ===")
        for url in test_urls:
            # Extract domain from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            
            # Create RID
            rid = WebPageRID(domain, url)
            print(f"URL: {url}")
            print(f"RID: {rid.to_orn()}")
            print(f"Domain: {domain}")
            print(f"Hash: {rid.path_hash}")
            print("-" * 60)
    
    async def test_content_monitoring(self):
        """Simulate content monitoring without coordinator"""
        print("\n=== Testing Content Monitoring (Standalone) ===")
        
        # Simulate page content changes
        test_page = "https://docs.regen.network/getting-started"
        domain = "docs.regen.network"
        
        # First visit - new content
        content_v1 = "Welcome to Regen Network documentation..."
        rid_v1 = WebPageRID(domain, test_page)
        
        print(f"First visit: {test_page}")
        print(f"RID: {rid_v1.to_orn()}")
        print(f"Event: NEW (would emit to coordinator if available)")
        
        # Store hash
        import hashlib
        hash_v1 = hashlib.sha256(content_v1.encode()).hexdigest()
        self.page_hashes[test_page] = hash_v1
        
        # Second visit - same content
        print(f"\nSecond visit: Same content")
        hash_v2 = hashlib.sha256(content_v1.encode()).hexdigest()
        if hash_v2 == self.page_hashes[test_page]:
            print(f"Event: NO_CHANGE (no event emitted)")
        
        # Third visit - updated content
        content_v3 = "Welcome to Regen Network documentation... [UPDATED CONTENT]"
        hash_v3 = hashlib.sha256(content_v3.encode()).hexdigest()
        
        print(f"\nThird visit: Updated content")
        if hash_v3 != self.page_hashes[test_page]:
            print(f"Event: UPDATE (would emit to coordinator if available)")
            self.page_hashes[test_page] = hash_v3

async def main():
    """Run standalone sensor tests"""
    print("🔧 KOI Website Sensor - Standalone Mode Test")
    print("=" * 60)
    print("This demonstrates sensor functionality WITHOUT a coordinator")
    print("Sensors can work independently for testing and development")
    print("=" * 60)
    
    sensor = StandaloneWebsiteSensor()
    
    # Test RID generation
    await sensor.test_rid_generation()
    
    # Test content monitoring
    await sensor.test_content_monitoring()
    
    print("\n" + "=" * 60)
    print("✅ Standalone Mode Test Complete!")
    print("\nNext steps:")
    print("1. Start KOI Coordinator: python koi_protocol/coordinator/run_coordinator.py")
    print("2. Run full sensor: python run_website_sensor.py")
    print("3. Sensor will connect to coordinator and emit real events")

if __name__ == "__main__":
    asyncio.run(main())