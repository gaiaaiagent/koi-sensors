#!/usr/bin/env python3
"""
Clean up empty transcripts and provide accurate count of real transcripts
"""

import json
import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

def analyze_transcripts():
    """Analyze all transcripts to identify real vs empty ones"""
    
    complete_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    
    real_transcripts = []
    empty_transcripts = []
    
    for file_path in sorted(complete_path.glob("episode_*_complete.json")):
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        episode_num = int(file_path.stem.split('_')[1])
        content = data.get('transcript', data.get('content', ''))
        words = len(content.split())
        
        if words > 100:  # Real transcript should have > 100 words
            real_transcripts.append({
                'episode': episode_num,
                'words': words,
                'pages': words / 250
            })
            logger.success(f"Episode {episode_num}: ✅ Real transcript ({words:,} words)")
        else:
            empty_transcripts.append(episode_num)
            logger.warning(f"Episode {episode_num}: ❌ Empty/blocked ({words} words)")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("ACTUAL PODCAST TRANSCRIPT STATUS")
    logger.info(f"{'='*60}")
    logger.info(f"Real transcripts: {len(real_transcripts)} episodes")
    logger.info(f"Empty/blocked: {len(empty_transcripts)} episodes")
    
    if real_transcripts:
        total_words = sum(t['words'] for t in real_transcripts)
        total_pages = total_words / 250
        
        logger.info(f"\nReal transcripts: {[t['episode'] for t in real_transcripts]}")
        logger.info(f"Total words: {total_words:,}")
        logger.info(f"Total pages/documents: {total_pages:.0f}")
        
        logger.info(f"\nEmpty/blocked: {empty_transcripts}")
    
    # Missing episodes (not fetched at all)
    all_episodes = set(range(1, 71))
    fetched = set([t['episode'] for t in real_transcripts]) | set(empty_transcripts)
    missing = sorted(all_episodes - fetched)
    
    if missing:
        logger.info(f"\nNot fetched at all: {missing} ({len(missing)} episodes)")
    
    # Total episodes needing transcription
    need_transcription = sorted(set(empty_transcripts) | set(missing))
    logger.warning(f"\n⚠️ Episodes needing audio transcription: {len(need_transcription)}")
    logger.info(f"Episodes: {need_transcription}")
    
    # Estimated documents if we transcribe all
    avg_pages = (sum(t['pages'] for t in real_transcripts) / len(real_transcripts)) if real_transcripts else 50
    estimated_additional = len(need_transcription) * avg_pages
    
    logger.info(f"\n📊 INDEXING IMPACT:")
    logger.info(f"Current real transcripts: {len(real_transcripts)} episodes = {total_pages:.0f} documents")
    logger.info(f"If we transcribe remaining {len(need_transcription)} episodes:")
    logger.info(f"  Estimated: +{estimated_additional:.0f} documents")
    logger.info(f"  Total: ~{(total_pages + estimated_additional):.0f} documents from podcasts")
    
    return {
        'real_transcripts': real_transcripts,
        'empty_transcripts': empty_transcripts,
        'missing': missing,
        'need_transcription': need_transcription,
        'total_pages': total_pages if real_transcripts else 0
    }

if __name__ == "__main__":
    logger.info("Analyzing podcast transcripts...")
    results = analyze_transcripts()