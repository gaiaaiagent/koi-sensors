#!/usr/bin/env python3
"""
Complete podcast indexing workflow - combines all working approaches
This script documents the full process for indexing the Planetary Regeneration Podcast
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

async def main():
    """
    Main workflow for complete podcast indexing
    """
    logger.info("="*60)
    logger.info("COMPLETE PODCAST INDEXING WORKFLOW")
    logger.info("="*60)
    
    # Step 1: Check current status
    logger.info("\n1. CHECKING CURRENT STATUS")
    logger.info("-"*40)
    
    from check_transcript_status import analyze_transcripts
    stats = analyze_transcripts()
    
    indexed = stats['indexed_episodes']
    total = stats['total_episodes']
    missing = stats['categories']['missing']
    stub = stats['categories']['stub']
    
    logger.info(f"Episodes indexed: {indexed}/{total} ({indexed/total*100:.1f}%)")
    logger.info(f"Missing episodes: {missing}")
    logger.info(f"Stub episodes: {stub}")
    
    # Step 2: Fetch from Notion API v3 (if not already done)
    if indexed < 44:  # We know Notion has ~44 good transcripts
        logger.info("\n2. FETCHING FROM NOTION API V3")
        logger.info("-"*40)
        logger.info("Run: python fetch_via_notion_api.py")
        logger.info("This will fetch ~44 episodes with inline transcripts")
    else:
        logger.info("\n2. NOTION FETCH COMPLETE ✅")
        logger.info("44 episodes already fetched from Notion")
    
    # Step 3: Transcribe remaining episodes
    need_transcription = len(missing) + len(stub)
    if need_transcription > 0:
        logger.info("\n3. AUDIO TRANSCRIPTION NEEDED")
        logger.info("-"*40)
        logger.info(f"Episodes needing transcription: {need_transcription}")
        logger.info("\nRun the following command:")
        logger.info("python transcribe_direct.py")
        logger.info("\nOr for specific episodes:")
        logger.info(f"python transcribe_direct.py --episodes {' '.join(map(str, (missing + stub)[:5]))}")
        
        logger.info("\nTips for successful transcription:")
        logger.info("• Ensure yt-dlp is updated: pip install -U yt-dlp")
        logger.info("• Install Whisper: pip install openai-whisper")
        logger.info("• Use --base-model for better quality")
        logger.info("• The script will retry with different methods if download fails")
    else:
        logger.info("\n3. TRANSCRIPTION COMPLETE ✅")
        logger.info("All episodes have transcripts!")
    
    # Step 4: Validate and report
    logger.info("\n4. VALIDATION")
    logger.info("-"*40)
    
    if indexed == total:
        logger.success("✅ ALL EPISODES SUCCESSFULLY INDEXED!")
        logger.info(f"Total words: {stats['total_words']:,}")
        logger.info(f"Estimated pages: {stats['total_words']/250:.0f}")
    else:
        logger.warning(f"⚠️ {total - indexed} episodes still need processing")
    
    # Step 5: Integration with main pipeline
    logger.info("\n5. INTEGRATION WITH MAIN INDEXING")
    logger.info("-"*40)
    logger.info("To integrate podcast data into main indexing:")
    logger.info("1. Convert to standard document format")
    logger.info("2. Generate embeddings")
    logger.info("3. Add to ChromaDB")
    logger.info("4. Update manifest")
    
    # Step 6: Summary
    logger.info("\n" + "="*60)
    logger.info("SUMMARY OF WORKING APPROACHES")
    logger.info("="*60)
    
    logger.info("\n✅ WHAT WORKS:")
    logger.info("• Notion API v3 loadPageChunk endpoint (bypasses Cloudflare)")
    logger.info("• Audio transcription with Whisper AI")
    logger.info("• yt-dlp with --force-ipv4 and retry logic")
    logger.info("• Tracking transcript source in metadata")
    
    logger.info("\n❌ WHAT DOESN'T WORK:")
    logger.info("• Direct web scraping (Cloudflare blocks)")
    logger.info("• Playwright automation (still detected)")
    logger.info("• Notion getSignedFileUrls API (returns None)")
    
    logger.info("\n📁 OUTPUT LOCATIONS:")
    logger.info("• Transcripts: podcast/storage/podcast_complete/")
    logger.info("• Audio cache: podcast/storage/audio_cache/")
    logger.info("• Status: podcast/storage/transcript_status.json")
    logger.info("• Documentation: podcast/docs/PODCAST_INDEXING_GUIDE.md")
    
    logger.info("\n" + "="*60)

if __name__ == "__main__":
    asyncio.run(main())