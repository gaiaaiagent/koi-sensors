#!/usr/bin/env python3
"""
Process all fetched podcast transcripts and prepare for indexing
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger
from typing import Dict, List

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

def process_transcripts():
    """Process all podcast transcripts and prepare for indexing"""
    
    # Paths
    complete_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    final_path = Path(__file__).parent.parent / "storage" / "podcast_final"
    final_path.mkdir(parents=True, exist_ok=True)
    
    # Get all complete transcripts
    complete_files = sorted(complete_path.glob("episode_*_complete.json"))
    logger.info(f"Found {len(complete_files)} complete transcripts")
    
    processed = []
    total_words = 0
    total_chars = 0
    
    for file_path in complete_files:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Extract episode number from filename
        episode_num = int(file_path.stem.split('_')[1])
        
        # Get transcript content
        content = data.get('transcript', data.get('content', ''))
        
        # Calculate statistics
        words = len(content.split())
        chars = len(content)
        
        # Estimate pages (250 words per page)
        pages = words / 250
        
        # Create enhanced document
        doc = {
            "id": f"podcast_episode_{episode_num:03d}",
            "source": "podcast:planetary_regeneration",
            "source_type": "podcast_transcript",
            "url": data.get('url', ''),
            "title": data.get('title', f"Planetary Regeneration Podcast Episode {episode_num}"),
            "content": content,
            "metadata": {
                "episode_number": episode_num,
                "guest_name": data.get('metadata', {}).get('guest_name', ''),
                "word_count": words,
                "char_count": chars,
                "estimated_pages": round(pages, 1),
                "has_transcript": True,
                "transcript_source": "notion",
                "processed_at": datetime.now().isoformat()
            }
        }
        
        # Save processed version
        output_file = final_path / f"episode_{episode_num:03d}_final.json"
        with open(output_file, 'w') as f:
            json.dump(doc, f, indent=2)
        
        processed.append({
            "episode": episode_num,
            "words": words,
            "pages": round(pages, 1)
        })
        
        total_words += words
        total_chars += chars
        
        logger.info(f"Episode {episode_num}: {words:,} words (~{pages:.1f} pages)")
    
    # Calculate totals
    total_pages = total_words / 250
    avg_words = total_words / len(processed) if processed else 0
    
    # Summary statistics
    logger.info(f"\n{'='*60}")
    logger.info("PODCAST INDEXING SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total episodes processed: {len(processed)}")
    logger.info(f"Total words: {total_words:,}")
    logger.info(f"Total characters: {total_chars:,}")
    logger.info(f"Estimated total pages: {total_pages:.1f}")
    logger.info(f"Average words per episode: {avg_words:.1f}")
    
    # Document count for indexing
    # Using granular counting: each page = 1 document
    document_count = round(total_pages)
    logger.info(f"\n📊 For indexing statistics:")
    logger.info(f"Total documents (pages): {document_count:,}")
    
    # Missing episodes
    all_episodes = set(range(1, 71))  # Episodes 1-70
    fetched_episodes = {p['episode'] for p in processed}
    missing = sorted(all_episodes - fetched_episodes)
    
    if missing:
        logger.warning(f"\n⚠️ Missing episodes: {missing}")
        logger.info(f"Missing count: {len(missing)} episodes")
        estimated_missing_docs = len(missing) * (avg_words / 250)
        logger.info(f"Estimated missing documents: {estimated_missing_docs:.0f}")
    
    # Save summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_episodes": len(processed),
        "total_words": total_words,
        "total_characters": total_chars,
        "total_pages": round(total_pages, 1),
        "document_count": document_count,
        "average_words_per_episode": round(avg_words, 1),
        "episodes_processed": sorted(fetched_episodes),
        "missing_episodes": missing,
        "estimated_missing_documents": len(missing) * round(avg_words / 250, 1),
        "episode_details": processed
    }
    
    summary_file = Path(__file__).parent.parent / "storage" / "podcast_indexing_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.success(f"\n✅ Processing complete!")
    logger.info(f"Summary saved to: {summary_file}")
    logger.info(f"Processed files in: {final_path}")
    
    return summary

def main():
    """Main entry point"""
    logger.info("Processing all podcast transcripts for indexing...")
    summary = process_transcripts()
    
    # Update parent indexing status
    logger.info("\n📈 Updating overall indexing status...")
    
    # Previous counts (from INDEXING_STATUS.md)
    previous_docs = 715  # Current total
    podcast_docs = summary['document_count']
    
    new_total = previous_docs + podcast_docs - 5  # Subtract the 5 we already counted
    
    logger.info(f"Previous total: {previous_docs:,} documents")
    logger.info(f"Podcast documents: {podcast_docs:,} pages")
    logger.info(f"New total: {new_total:,} documents")
    
    progress_pct = (new_total / 15000) * 100
    logger.info(f"Progress: {progress_pct:.1f}% of 15,000 target")
    
    # Visual progress bar
    filled = int(progress_pct / 2.5)  # 40 char bar
    bar = '█' * filled + '░' * (40 - filled)
    logger.info(f"\n[{bar}] {new_total:,}/15,000")

if __name__ == "__main__":
    main()