#!/usr/bin/env python3
"""
Collect the final 19 missing articles from user's list
"""

import asyncio
import json
import sys
from pathlib import Path
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")

sys.path.append(str(Path(__file__).parent.parent.parent))
from indexing.collectors.medium_collector import MediumCollector


async def main():
    """Collect final missing articles"""
    
    # The 19 missing URLs
    missing_urls = [
        "https://regen-network.medium.com/tech-round-up-lets-explore-cosmos-sdk-and-regen-ledger-projects-448e654052de",
        "https://regen-network.medium.com/telegram-ama-1-eecc6cdbd507",
        "https://regen-network.medium.com/telegram-ama-2-token-sale-658b1419366c",
        "https://regen-network.medium.com/telegram-ama-3-project-update-64ef1450f96a",
        "https://regen-network.medium.com/terrasos-and-regen-network-pioneering-transparent-scalable-markets-for-biodiversity-credits-7fb23b38979a",
        "https://regen-network.medium.com/the-alternative-that-the-voluntary-carbon-market-needs-at-this-juncture-27e46934fc23",
        "https://regen-network.medium.com/the-day-after-covid-19-53cc64692820",
        "https://regen-network.medium.com/the-evolution-of-regen-network-ae74febe1edf",
        "https://regen-network.medium.com/the-permissionless-future-of-credit-class-creation-on-regen-network-138e5136eda3",
        "https://regen-network.medium.com/unlock-regenerative-finance-with-regen-marketplace-43745369315b",
        "https://regen-network.medium.com/urban-forestry-part-2-protecting-infrastructure-and-water-quality-16b3139c8712",
        "https://regen-network.medium.com/urban-forestry-part-3-protecting-mature-forests-and-migratory-pathways-94293e7c7d48",
        "https://regen-network.medium.com/urban-forestry-part-4-empowering-at-risk-youth-a29ecf9f25eb",
        "https://regen-network.medium.com/urban-forestry-part-5-preserving-urban-forests-amid-residential-development-threat-f7a08f7f79c",
        "https://regen-network.medium.com/urban-forestry-part-i-protecting-mature-forests-and-migratory-pathways-ecd504246fb6",
        "https://regen-network.medium.com/validator-resources-e7be93779db3",
        "https://regen-network.medium.com/welcome-to-regen-network-a7364717926d",
        "https://regen-network.medium.com/what-is-the-difference-between-net-zero-and-ecological-regeneration-9f14035d77d1",
        "https://regen-network.medium.com/white-buffalo-land-trust-regen-network-a7a1f5bfe734"
    ]
    
    logger.info(f"Collecting final {len(missing_urls)} missing articles")
    
    # Initialize collector
    config = {
        'medium': [{
            'name': 'regen-network-medium',
            'url': 'https://regen-network.medium.com',
            'strategy': 'scrape'
        }]
    }
    
    collector = MediumCollector(config)
    
    # Collect articles
    collected = []
    failed = []
    
    for i, url in enumerate(missing_urls, 1):
        try:
            logger.info(f"[{i}/{len(missing_urls)}] Collecting: {url}")
            article = await collector.collect_article(url, 'regen-network-medium')
            
            if article:
                collected.append(article)
                # Save every 5 articles
                if len(collected) % 5 == 0:
                    collector.save_documents(collected[-5:])
                    logger.success(f"  Saved batch of 5 articles")
            else:
                logger.warning(f"  Failed to collect article")
                failed.append(url)
                
            # Small delay
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"  Error: {e}")
            failed.append(url)
    
    # Save remaining
    if collected and len(collected) % 5 != 0:
        remaining = len(collected) % 5
        collector.save_documents(collected[-remaining:])
        logger.success(f"Saved final batch of {remaining} articles")
    
    # Report
    logger.info(f"\n{'='*60}")
    logger.success(f"Collected {len(collected)}/{len(missing_urls)} missing articles")
    
    if failed:
        logger.warning(f"Failed to collect {len(failed)} articles:")
        for url in failed:
            logger.warning(f"  - {url}")
    
    # Final count
    final_docs = list(Path("indexing/storage/documents").glob("medium_*.json"))
    logger.info(f"\nFINAL TOTAL: {len(final_docs)} Medium article files")


if __name__ == "__main__":
    asyncio.run(main())