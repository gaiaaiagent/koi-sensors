#!/usr/bin/env python3
"""
Index Regen Network podcast episodes from SoundCloud.
Collects metadata and optionally transcribes audio content.
"""

import sys
import asyncio
import json
from pathlib import Path
from datetime import datetime
import yaml
from loguru import logger
from tqdm import tqdm

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.soundcloud_collector import SoundCloudCollector
from indexing.processors.audio_transcriber import get_transcriber


async def index_podcast(
    limit: int = None,
    transcribe: bool = False,
    generate_embeddings: bool = True,
    incremental: bool = True
):
    """
    Index podcast episodes with full processing pipeline.
    
    Args:
        limit: Maximum number of episodes to process (None for all)
        transcribe: Whether to transcribe audio content
        generate_embeddings: Whether to generate vector embeddings
        incremental: Only process new episodes not already indexed
    """
    logger.info("="*60)
    logger.info("🎙️  Regen Network Podcast Indexing")
    logger.info("="*60)
    
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
        
    # Get podcast configuration
    podcast_sources = config['sources'].get('podcast', [])
    if not podcast_sources:
        logger.error("No podcast sources configured")
        return
        
    podcast_config = podcast_sources[0]
    
    # Configure options
    if limit:
        podcast_config['test_limit'] = limit
    podcast_config['fetch_audio_urls'] = transcribe  # Only fetch if transcribing
    
    logger.info(f"📍 Source: {podcast_config['url']}")
    logger.info(f"🔢 Limit: {limit or 'All episodes'}")
    logger.info(f"🎤 Transcription: {'Enabled' if transcribe else 'Disabled'}")
    logger.info(f"🔮 Embeddings: {'Enabled' if generate_embeddings else 'Disabled'}")
    logger.info(f"♻️  Mode: {'Incremental' if incremental else 'Full'}")
    logger.info("")
    
    # Initialize storage
    storage_dir = Path(__file__).parent.parent / "storage"
    doc_dir = storage_dir / "documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    
    # Check existing documents if incremental
    existing_ids = set()
    if incremental:
        for doc_file in doc_dir.glob("soundcloud_*.json"):
            existing_ids.add(doc_file.stem)
        if existing_ids:
            logger.info(f"Found {len(existing_ids)} existing episodes")
    
    # Initialize collector
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    
    collector = SoundCloudCollector(podcast_config, cache_dir)
    
    # Collect episodes
    logger.info("📥 Collecting episode metadata...")
    documents = await collector.collect()
    logger.info(f"Found {len(documents)} total episodes")
    
    # Filter for new episodes if incremental
    if incremental and existing_ids:
        new_documents = [doc for doc in documents if doc.id not in existing_ids]
        logger.info(f"Processing {len(new_documents)} new episodes")
        documents = new_documents
        
        if not documents:
            logger.success("✅ All episodes already indexed!")
            return
    
    # Initialize processors
    transcriber = None
    if transcribe:
        logger.info("🎧 Initializing audio transcriber...")
        transcriber = get_transcriber(model_name="base")
        
    # Skip embeddings for now (modules not yet implemented)
    if generate_embeddings:
        logger.warning("Embedding generation not yet implemented, skipping...")
        generate_embeddings = False
    
    # Process documents
    processed_count = 0
    transcribed_count = 0
    embedded_count = 0
    
    logger.info("")
    logger.info("🔄 Processing episodes...")
    
    with tqdm(total=len(documents), desc="Processing") as pbar:
        for doc in documents:
            try:
                # Save original metadata
                doc_dict = {
                    'id': doc.id,
                    'source': doc.source,
                    'source_type': doc.source_type,
                    'url': doc.url,
                    'title': doc.title,
                    'content': doc.content,
                    'metadata': doc.metadata
                }
                
                # Transcribe if enabled
                if transcribe and transcriber:
                    pbar.set_description(f"Transcribing: {doc.title[:30]}...")
                    
                    # Download and transcribe audio
                    audio_path = cache_dir / f"{doc.id}.mp3"
                    if not audio_path.exists() and doc.url:
                        success = await collector.download_audio(doc.url, audio_path)
                        if success:
                            logger.debug(f"Downloaded audio: {audio_path.name}")
                    
                    if audio_path.exists():
                        result = transcriber.transcribe_file(audio_path)
                        if result:
                            transcript = transcriber.format_transcript(result)
                            doc_dict['content'] = doc_dict['content'].replace(
                                "*Note: Audio transcription not yet implemented. This document contains metadata only.*",
                                transcript
                            )
                            doc_dict['metadata']['has_transcription'] = True
                            doc_dict['metadata']['transcript_length'] = len(result['text'])
                            transcribed_count += 1
                            logger.debug(f"Transcribed: {doc.title}")
                
                # Skip embeddings for now
                
                # Save document
                doc_path = doc_dir / f"{doc_dict['id']}.json"
                with open(doc_path, 'w') as f:
                    json.dump(doc_dict, f, indent=2)
                
                processed_count += 1
                pbar.update(1)
                
            except Exception as e:
                logger.error(f"Failed to process {doc.title}: {e}")
                pbar.update(1)
                continue
    
    # Summary
    logger.info("")
    logger.info("="*60)
    logger.success("✅ Podcast Indexing Complete!")
    logger.info(f"📊 Processed: {processed_count} episodes")
    if transcribe:
        logger.info(f"🎤 Transcribed: {transcribed_count} episodes")
    if generate_embeddings:
        logger.info(f"🧠 Generated: {embedded_count} embeddings")
    logger.info(f"💾 Documents saved to: {doc_dir}")
    logger.info("="*60)
    
    return processed_count


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Index Regen Network podcast episodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Index all episodes with transcription
  python index_podcast.py --transcribe
  
  # Index first 10 episodes without transcription
  python index_podcast.py --limit 10
  
  # Full re-index (not incremental)
  python index_podcast.py --full
  
  # Index without generating embeddings (metadata only)
  python index_podcast.py --no-embeddings
"""
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of episodes to process"
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Enable audio transcription (requires Whisper and ffmpeg)"
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding generation (metadata and transcripts only)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full re-index (process all episodes, not just new ones)"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>"
    )
    
    try:
        await index_podcast(
            limit=args.limit,
            transcribe=args.transcribe,
            generate_embeddings=not args.no_embeddings,
            incremental=not args.full
        )
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())