#!/usr/bin/env python3
"""
Test podcast collection from SoundCloud.
Collects metadata and optionally transcribes audio.
"""

import sys
import asyncio
from pathlib import Path
import yaml
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from indexing.collectors.soundcloud_collector import SoundCloudCollector
from indexing.processors.audio_transcriber import get_transcriber


async def test_podcast_collection(transcribe: bool = False, limit: int = 2):
    """
    Test podcast collection and optional transcription.
    
    Args:
        transcribe: Whether to transcribe audio (requires Whisper)
        limit: Number of episodes to collect
    """
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
        
    # Get podcast configuration
    podcast_sources = config['sources'].get('podcast', [])
    
    if not podcast_sources:
        logger.error("No podcast sources configured")
        return
        
    # Use first podcast source
    podcast_config = podcast_sources[0]
    podcast_config['test_limit'] = limit  # Override limit
    
    logger.info(f"Testing podcast collection from: {podcast_config['url']}")
    logger.info(f"Collection limit: {limit} episodes")
    logger.info(f"Transcription enabled: {transcribe}")
    
    # Initialize collector
    cache_dir = Path(__file__).parent.parent / "cache"
    cache_dir.mkdir(exist_ok=True)
    
    collector = SoundCloudCollector(podcast_config, cache_dir)
    
    # Collect episodes
    logger.info("Starting collection...")
    documents = await collector.collect()
    
    logger.info(f"Collected {len(documents)} episodes")
    
    # Display episode information
    for i, doc in enumerate(documents, 1):
        logger.info(f"\nEpisode {i}:")
        logger.info(f"  Title: {doc.title}")
        logger.info(f"  URL: {doc.url}")
        logger.info(f"  Duration: {doc.metadata.get('duration_ms', 0) // 60000} minutes")
        logger.info(f"  Published: {doc.metadata.get('created_at', 'Unknown')}")
        
        # Show first 200 chars of description
        content_preview = doc.content[:200].replace('\n', ' ')
        logger.info(f"  Preview: {content_preview}...")
        
    # Optionally transcribe audio
    if transcribe and documents:
        logger.info("\n" + "="*50)
        logger.info("Starting audio transcription...")
        logger.info("Note: This requires ffmpeg and may take several minutes per episode")
        
        # Initialize transcriber
        transcriber = get_transcriber(model_name="base")
        
        # Process first document as example
        doc = documents[0]
        logger.info(f"Transcribing: {doc.title}")
        
        # Convert to dict for processing
        doc_dict = {
            'id': doc.id,
            'content': doc.content,
            'metadata': doc.metadata
        }
        
        # Transcribe
        updated_doc = await transcriber.process_soundcloud_document(doc_dict)
        
        if updated_doc['metadata'].get('has_transcription'):
            logger.success(f"Transcription successful!")
            logger.info(f"Transcript length: {updated_doc['metadata'].get('transcript_length')} chars")
            
            # Show preview of transcript
            if 'Full Transcript' in updated_doc['content']:
                transcript_start = updated_doc['content'].find('Full Transcript')
                transcript_preview = updated_doc['content'][transcript_start:transcript_start + 500]
                logger.info(f"\nTranscript preview:\n{transcript_preview}...")
        else:
            logger.warning("Transcription failed or not available")
            
    # Save to storage (simplified version)
    storage_dir = Path(__file__).parent.parent / "storage" / "documents"
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    saved_count = 0
    for doc in documents:
        # Save as JSON
        doc_path = storage_dir / f"{doc.id}.json"
        try:
            import json
            doc_dict = {
                'id': doc.id,
                'source': doc.source,
                'source_type': doc.source_type,
                'url': doc.url,
                'title': doc.title,
                'content': doc.content,
                'metadata': doc.metadata
            }
            with open(doc_path, 'w') as f:
                json.dump(doc_dict, f, indent=2)
            saved_count += 1
            logger.info(f"Saved: {doc_path.name}")
        except Exception as e:
            logger.error(f"Failed to save {doc.id}: {e}")
            
    logger.info(f"\nSaved {saved_count} documents to storage")
    
    return documents


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test podcast collection")
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Enable audio transcription (requires Whisper and ffmpeg)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Number of episodes to collect (default: 2)"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    
    try:
        await test_podcast_collection(
            transcribe=args.transcribe,
            limit=args.limit
        )
        logger.success("Podcast collection test completed!")
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())