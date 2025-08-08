#!/usr/bin/env python3
"""
Try accessing Notion content through their API endpoints
"""

import httpx
import json
import asyncio
from pathlib import Path
from loguru import logger
import re

async def try_notion_api():
    """Try different Notion API approaches"""
    
    # Test URLs
    test_urls = [
        "https://regennetwork.notion.site/06-Delton-Chen-c2986ce13b7e4cad9ecb2fe7628a9d2c",
        "https://regennetwork.notion.site/067-Josiah-Hunt-Pacific-Biochar-040b675477fa4f03974fb5699f91a8d0"
    ]
    
    # Extract page IDs
    for url in test_urls:
        # Extract the ID from the URL (last part after the dash)
        match = re.search(r'-([a-f0-9]{32})', url)
        if match:
            page_id = match.group(1)
            logger.info(f"Extracted page ID: {page_id}")
            
            # Format for Notion API
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            logger.info(f"Formatted ID: {formatted_id}")
            
            async with httpx.AsyncClient() as client:
                # Try different endpoints
                endpoints = [
                    f"https://www.notion.so/api/v3/loadPageChunk",
                    f"https://www.notion.so/api/v3/getRecordValues",
                    f"https://api.notion.com/v1/pages/{formatted_id}",
                    f"https://api.notion.com/v1/blocks/{formatted_id}/children",
                ]
                
                for endpoint in endpoints:
                    logger.info(f"Trying endpoint: {endpoint}")
                    
                    try:
                        if "api/v3" in endpoint:
                            # Old API format
                            payload = {
                                "pageId": formatted_id,
                                "limit": 100,
                                "cursor": {"stack": []},
                                "chunkNumber": 0,
                                "verticalColumns": False
                            }
                            response = await client.post(
                                endpoint,
                                json=payload,
                                headers={
                                    "Content-Type": "application/json",
                                    "User-Agent": "Mozilla/5.0"
                                }
                            )
                        else:
                            # New API format (requires auth usually)
                            response = await client.get(
                                endpoint,
                                headers={
                                    "Notion-Version": "2022-06-28",
                                    "User-Agent": "Mozilla/5.0"
                                }
                            )
                        
                        logger.info(f"Status: {response.status_code}")
                        if response.status_code == 200:
                            content = response.text
                            logger.success(f"Got response: {len(content)} bytes")
                            
                            # Save for analysis
                            Path("notion_api_response.json").write_text(content[:5000])
                            
                            # Check if it has actual content
                            if "transcript" in content.lower() or len(content) > 10000:
                                logger.success("Found substantial content!")
                                return content
                        
                    except Exception as e:
                        logger.error(f"Error: {e}")
                
                await asyncio.sleep(2)  # Rate limiting

if __name__ == "__main__":
    asyncio.run(try_notion_api())