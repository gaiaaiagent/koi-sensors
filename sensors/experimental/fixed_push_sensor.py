#!/usr/bin/env python3
"""
Fixed Push-Only Sensor for KOI Pipeline
Sensors are event PRODUCERS that push content, not consumers that poll
"""

import requests
import time
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("koi.sensor.push")


class PushOnlySensor:
    """
    Base class for sensors that PUSH content to coordinator
    No polling - sensors are producers, not consumers
    """
    
    def __init__(self, sensor_name: str, coordinator_url: str = "http://localhost:8005"):
        self.sensor_name = sensor_name
        self.coordinator_url = coordinator_url
        self.api_endpoint = f"{coordinator_url}/api/event"  # Our fixed coordinator endpoint
        self.seen_content = set()  # Track what we've already sent
        
        logger.info(f"Initialized {sensor_name} sensor")
        logger.info(f"Will push to: {self.api_endpoint}")
    
    def push_content(self, content: Dict[str, Any], source_type: str = None) -> bool:
        """
        Push content to the coordinator
        This is the ONLY way sensors communicate - PUSH, not POLL
        """
        try:
            # Generate unique ID for deduplication
            content_str = json.dumps(content, sort_keys=True)
            content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:12]
            
            # Check if already sent
            if content_hash in self.seen_content:
                logger.debug(f"Skipping duplicate content: {content_hash}")
                return False
            
            # Create event structure for our fixed coordinator
            event = {
                "source_sensor": f"{self.sensor_name}.{source_type or 'default'}.{content_hash}",
                "content": content,
                "metadata": {
                    "sensor": self.sensor_name,
                    "type": source_type or "content",
                    "hash": content_hash,
                    "pushed_at": datetime.now().isoformat()
                }
            }
            
            # PUSH to coordinator (no polling!)
            response = requests.post(self.api_endpoint, json=event, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                self.seen_content.add(content_hash)
                logger.info(f"✅ Pushed content: {content_hash} -> RID: {result.get('rid', 'unknown')}")
                
                # Limit memory usage
                if len(self.seen_content) > 10000:
                    self.seen_content = set(list(self.seen_content)[-5000:])
                
                return True
            else:
                logger.error(f"❌ Push failed ({response.status_code}): {response.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error pushing content: {e}")
            return False


class WebContentSensor(PushOnlySensor):
    """
    Web content sensor - pushes website content
    """
    
    def __init__(self):
        super().__init__("web_content")
        self.websites = [
            {"url": "https://www.regen.network", "name": "main"},
            {"url": "https://blog.regen.network", "name": "blog"},
            {"url": "https://docs.regen.network", "name": "docs"},
            {"url": "https://registry.regen.network", "name": "registry"}
        ]
    
    def scrape_and_push(self, site: Dict[str, str]):
        """Scrape website and push content"""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            response = requests.get(site["url"], timeout=10)
            if response.status_code != 200:
                return
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract meaningful content
            for article in soup.find_all(['article', 'section', 'main'], limit=5):
                text = article.get_text(strip=True)
                if len(text) > 200:  # Meaningful content only
                    content = {
                        "url": site["url"],
                        "site": site["name"],
                        "title": soup.title.string if soup.title else site["name"],
                        "text": text[:1000],  # Limit size
                        "scraped_at": datetime.now().isoformat()
                    }
                    
                    self.push_content(content, source_type=f"web.{site['name']}")
                    time.sleep(1)  # Rate limiting
                    
        except Exception as e:
            logger.error(f"Error scraping {site['url']}: {e}")
    
    def run(self):
        """Main loop - scrape and push"""
        logger.info("Starting web content sensor...")
        
        while True:
            for site in self.websites:
                logger.info(f"Checking {site['name']}...")
                self.scrape_and_push(site)
            
            logger.info("Waiting 5 minutes before next check...")
            time.sleep(300)  # Check every 5 minutes


class RSSFeedSensor(PushOnlySensor):
    """
    RSS feed sensor - pushes RSS content
    """
    
    def __init__(self):
        super().__init__("rss_feed")
        self.feeds = [
            {
                "url": "https://blog.regen.network/rss/",
                "name": "blog"
            },
            {
                "url": "https://medium.com/feed/regen-network",
                "name": "medium"
            }
        ]
    
    def check_and_push(self, feed: Dict[str, str]):
        """Check RSS feed and push new items"""
        try:
            import feedparser
            
            parsed = feedparser.parse(feed["url"])
            
            for entry in parsed.entries[:10]:  # Latest 10 items
                content = {
                    "title": entry.get("title", "No title"),
                    "link": entry.get("link", ""),
                    "description": entry.get("description", "")[:500],
                    "published": entry.get("published", ""),
                    "feed": feed["name"]
                }
                
                self.push_content(content, source_type=f"rss.{feed['name']}")
                time.sleep(1)  # Rate limiting
                
        except Exception as e:
            logger.error(f"Error checking feed {feed['name']}: {e}")
    
    def run(self):
        """Main loop - check feeds and push"""
        logger.info("Starting RSS feed sensor...")
        
        while True:
            for feed in self.feeds:
                logger.info(f"Checking {feed['name']} feed...")
                self.check_and_push(feed)
            
            logger.info("Waiting 30 minutes before next check...")
            time.sleep(1800)  # Check every 30 minutes


class ManualContentPusher(PushOnlySensor):
    """
    Manual content pusher for testing and direct content injection
    """
    
    def __init__(self):
        super().__init__("manual_pusher")
    
    def push_regen_content(self):
        """Push some real Regen Network content"""
        contents = [
            {
                "title": "Carbon Methodology VM0042",
                "text": "VM0042 is a methodology for improved agricultural land management that enables farmers to generate carbon credits through regenerative practices including cover cropping, reduced tillage, and organic amendments.",
                "category": "methodology"
            },
            {
                "title": "Regen Registry Overview", 
                "text": "Regen Registry is the program through which land stewards can register their projects, report on ecological outcomes, and issue credits. It provides transparency and verification for ecological assets.",
                "category": "registry"
            },
            {
                "title": "IBC and Interchain Integration",
                "text": "Regen Network leverages the Inter-Blockchain Communication protocol to enable cross-chain trading of ecological assets, connecting with other Cosmos chains for liquidity and utility.",
                "category": "technical"
            },
            {
                "title": "Community Governance",
                "text": "REGEN token holders participate in on-chain governance to make decisions about network parameters, credit class approval, and community pool spending through proposals and voting.",
                "category": "governance"
            },
            {
                "title": "Ecological Data Module",
                "text": "The data module on Regen Ledger allows for anchoring, signing, and registering of ecological data on-chain, providing cryptographic proof of data integrity and provenance.",
                "category": "technical"
            }
        ]
        
        for content in contents:
            self.push_content(content, source_type="knowledge")
            time.sleep(2)
        
        logger.info(f"✅ Pushed {len(contents)} content items")


def test_push_sensor():
    """Test the push-only sensor pattern"""
    logger.info("="*60)
    logger.info("TESTING PUSH-ONLY SENSOR PATTERN")
    logger.info("="*60)
    
    # Test manual pusher
    pusher = ManualContentPusher()
    pusher.push_regen_content()
    
    logger.info("Test complete! Check KOI memories with:")
    logger.info("docker exec gaia-postgres-1 psql -U postgres -d eliza -c 'SELECT COUNT(*) FROM koi_memories;'")


def main():
    """Main entry point"""
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            test_push_sensor()
        elif sys.argv[1] == "web":
            sensor = WebContentSensor()
            sensor.run()
        elif sys.argv[1] == "rss":
            sensor = RSSFeedSensor()
            sensor.run()
        else:
            print("Usage: python fixed_push_sensor.py [test|web|rss]")
    else:
        # Default: run test
        test_push_sensor()


if __name__ == "__main__":
    main()