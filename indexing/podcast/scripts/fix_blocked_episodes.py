#!/usr/bin/env python3
"""
Fix episodes that have Cloudflare blocks instead of real transcripts
"""

import httpx
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

async def fix_blocked_episodes():
    """Re-fetch episodes that have Cloudflare blocks"""
    
    # Episodes to fix
    episodes_to_fix = [
        {"episode_num": 46, "url": "https://regennetwork.notion.site/046-Genevieve-Guenther-Climate-Communication-in-Dark-Times-11e29f3e8b204bb883d0b49e39e95f67?pvs=25"},
        {"episode_num": 67, "url": "https://regennetwork.notion.site/067-Josiah-Hunt-Pacific-Biochar-040b675477fa4f03974fb5699f91a8d0?pvs=25"},
        {"episode_num": 70, "url": "https://regennetwork.notion.site/070-Bayo-Akomolafe-Rituals-of-Incompleteness-in-the-Age-of-AI-1e425b77eda1809cbd4ad388931662d9?pvs=25"}
    ]
    
    api_endpoint = "https://www.notion.so/api/v3/loadPageChunk"
    storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    
    async with httpx.AsyncClient() as client:
        for episode in episodes_to_fix:
            logger.info(f"Fixing episode {episode['episode_num']}...")
            
            # Extract page ID
            match = re.search(r'-([a-f0-9]{32})', episode['url'])
            if not match:
                logger.error(f"Could not extract page ID from {episode['url']}")
                continue
            
            page_id = match.group(1)
            formatted_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
            
            # Fetch with API v3
            payload = {
                "pageId": formatted_id,
                "limit": 100,
                "cursor": {"stack": []},
                "chunkNumber": 0,
                "verticalColumns": False
            }
            
            try:
                response = await client.post(
                    api_endpoint,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Extract text content (simplified)
                    text_parts = []
                    if 'recordMap' in data and 'block' in data['recordMap']:
                        for block_id, block_data in data['recordMap']['block'].items():
                            if 'value' in block_data and 'properties' in block_data['value']:
                                props = block_data['value']['properties']
                                for field in ['title', 'text', 'caption']:
                                    if field in props:
                                        for text_item in props[field]:
                                            if isinstance(text_item, list) and len(text_item) > 0:
                                                text_parts.append(str(text_item[0]))
                    
                    content = '\n'.join(text_parts)
                    
                    if len(content) > 1000:
                        # Save fixed transcript
                        filename = storage_path / f"episode_{episode['episode_num']:03d}_complete.json"
                        
                        # Load existing file to preserve metadata
                        with open(filename, 'r') as f:
                            doc = json.load(f)
                        
                        # Update content and transcript
                        doc['content'] = content
                        doc['transcript'] = content
                        doc['metadata']['transcript_source'] = 'notion_api_v3_fixed'
                        doc['metadata']['fixed_at'] = datetime.now().isoformat()
                        
                        with open(filename, 'w') as f:
                            json.dump(doc, f, indent=2)
                        
                        logger.success(f"Fixed episode {episode['episode_num']}: {len(content)} chars")
                    else:
                        logger.warning(f"Episode {episode['episode_num']}: Content still too short")
                else:
                    logger.error(f"Episode {episode['episode_num']}: Status {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error fixing episode {episode['episode_num']}: {e}")
            
            # Rate limiting
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(fix_blocked_episodes())