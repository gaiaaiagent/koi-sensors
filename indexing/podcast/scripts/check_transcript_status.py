#!/usr/bin/env python3
"""
Check the status of all podcast episode transcripts
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger
import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

def analyze_transcripts():
    """Analyze all transcript files and generate status report"""
    storage_path = Path(__file__).parent.parent / "storage" / "podcast_complete"
    
    # Categories
    categories = {
        'notion': [],
        'notion_api_v3': [],
        'whisper': [],
        'stub': [],
        'missing': []
    }
    
    total_words = 0
    total_chars = 0
    episodes_with_guests = {}
    
    # Check all episodes 1-70
    for episode_num in range(1, 71):
        filename = storage_path / f"episode_{episode_num:03d}_complete.json"
        
        if filename.exists():
            with open(filename, 'r') as f:
                data = json.load(f)
            
            content = data.get('transcript', data.get('content', ''))
            metadata = data.get('metadata', {})
            
            # Determine category
            if len(content) < 1000:
                categories['stub'].append(episode_num)
            else:
                source = metadata.get('transcript_source', 'unknown')
                if 'notion_api_v3' in source:
                    categories['notion_api_v3'].append(episode_num)
                elif 'whisper' in source:
                    categories['whisper'].append(episode_num)
                elif 'notion' in source:
                    categories['notion'].append(episode_num)
                else:
                    categories['notion'].append(episode_num)  # Default old ones
                
                # Count words
                word_count = len(content.split())
                char_count = len(content)
                total_words += word_count
                total_chars += char_count
                
                # Track guest names
                guest = metadata.get('guest_name', 'Unknown')
                episodes_with_guests[episode_num] = {
                    'guest': guest,
                    'words': word_count,
                    'source': metadata.get('transcript_source', 'unknown')
                }
        else:
            categories['missing'].append(episode_num)
    
    # Generate report
    print("\n" + "="*60)
    print("PODCAST TRANSCRIPT STATUS REPORT")
    print("="*60)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Summary
    total_episodes = 70
    indexed_episodes = total_episodes - len(categories['missing']) - len(categories['stub'])
    
    print("SUMMARY")
    print("-"*40)
    print(f"Total Episodes:     {total_episodes}")
    print(f"Indexed Episodes:   {indexed_episodes}")
    print(f"Missing Episodes:   {len(categories['missing'])}")
    print(f"Stub Episodes:      {len(categories['stub'])}")
    print(f"Completion:         {indexed_episodes/total_episodes*100:.1f}%")
    print()
    
    # Content Statistics
    print("CONTENT STATISTICS")
    print("-"*40)
    print(f"Total Words:        {total_words:,}")
    print(f"Total Characters:   {total_chars:,}")
    print(f"Estimated Pages:    {total_words/250:.0f}")
    print(f"Avg Words/Episode:  {total_words/max(indexed_episodes, 1):.0f}")
    print()
    
    # Source Breakdown
    print("TRANSCRIPT SOURCES")
    print("-"*40)
    print(f"Notion API v3:      {len(categories['notion_api_v3'])} episodes")
    print(f"Notion (legacy):    {len(categories['notion'])} episodes")
    print(f"Whisper AI:         {len(categories['whisper'])} episodes")
    print(f"Stub/Incomplete:    {len(categories['stub'])} episodes")
    print(f"Missing:            {len(categories['missing'])} episodes")
    print()
    
    # Detailed Lists
    if categories['missing']:
        print("MISSING EPISODES")
        print("-"*40)
        print(f"Episodes: {categories['missing']}")
        print()
    
    if categories['stub']:
        print("STUB EPISODES (need transcription)")
        print("-"*40)
        print(f"Episodes: {categories['stub']}")
        print()
    
    if categories['whisper']:
        print("WHISPER TRANSCRIBED")
        print("-"*40)
        print(f"Episodes: {categories['whisper']}")
        print()
    
    # Top Episodes by Word Count
    if episodes_with_guests:
        print("TOP 10 EPISODES BY WORD COUNT")
        print("-"*40)
        sorted_episodes = sorted(episodes_with_guests.items(), 
                                key=lambda x: x[1]['words'], 
                                reverse=True)[:10]
        
        for ep_num, info in sorted_episodes:
            print(f"Episode {ep_num:3d}: {info['words']:6,} words - {info['guest'][:30]}")
        print()
    
    # Action Items
    action_needed = len(categories['missing']) + len(categories['stub'])
    if action_needed > 0:
        print("ACTION ITEMS")
        print("-"*40)
        print(f"• {action_needed} episodes need transcription")
        
        if categories['stub']:
            print(f"  - Fix stub episodes: {categories['stub'][:5]}{'...' if len(categories['stub']) > 5 else ''}")
        
        if categories['missing']:
            print(f"  - Transcribe missing: {categories['missing'][:5]}{'...' if len(categories['missing']) > 5 else ''}")
        
        print("\nRun: python transcribe_direct.py")
    else:
        print("✅ ALL EPISODES SUCCESSFULLY INDEXED!")
    
    print("\n" + "="*60)
    
    # Return data for programmatic use
    return {
        'total_episodes': total_episodes,
        'indexed_episodes': indexed_episodes,
        'total_words': total_words,
        'total_chars': total_chars,
        'categories': categories,
        'episodes_with_guests': episodes_with_guests
    }

def main():
    """Main entry point"""
    logger.info("Analyzing podcast transcript status...")
    stats = analyze_transcripts()
    
    # Save to JSON for other scripts
    output_file = Path(__file__).parent.parent / "storage" / "transcript_status.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(stats, f, indent=2)
    
    logger.info(f"Status saved to: {output_file}")

if __name__ == "__main__":
    main()