#!/usr/bin/env python3
"""
Enhance podcast metadata by extracting speakers, guests, and hashtags from SoundCloud
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from loguru import logger

def extract_guest_from_title(title):
    """Extract guest name from episode title"""
    # Common patterns for guest names in titles
    patterns = [
        r'\|\s*([^|]+)$',  # After last pipe
        r':\s*([^:|]+)$',  # After last colon
        r'with\s+([^|:]+)',  # After "with"
        r'feat\.?\s*([^|:]+)',  # After "feat" or "feat."
        r'guest\s*:?\s*([^|:]+)',  # After "guest"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            guest = match.group(1).strip()
            # Clean up common suffixes
            guest = re.sub(r'\s*\([^)]+\)$', '', guest)  # Remove parenthetical
            guest = re.sub(r'\s*-\s*\w+$', '', guest)  # Remove trailing dash words
            return guest
    
    return None

def fetch_soundcloud_metadata(url):
    """Fetch detailed metadata from SoundCloud including hashtags"""
    try:
        cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--dump-json',
            '--no-check-certificate',
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            
            # Extract hashtags from description
            description = data.get('description', '')
            hashtags = re.findall(r'#\w+', description)
            
            # Extract additional metadata
            metadata = {
                'title': data.get('title', ''),
                'description': description,
                'hashtags': hashtags,
                'duration': data.get('duration', 0),
                'upload_date': data.get('upload_date', ''),
                'view_count': data.get('view_count', 0),
                'like_count': data.get('like_count', 0),
                'comment_count': data.get('comment_count', 0),
                'uploader': data.get('uploader', 'Planetary Regeneration'),
            }
            
            return metadata
    except Exception as e:
        logger.warning(f"Could not fetch metadata for {url}: {e}")
    
    return None

def enhance_episode_metadata():
    """Enhance metadata for all episodes"""
    storage_path = Path(__file__).parent.parent / "storage"
    complete_path = storage_path / "podcast_complete"
    
    # Load SoundCloud episodes mapping
    sc_file = storage_path / "soundcloud_episodes.json"
    with open(sc_file) as f:
        sc_episodes = json.load(f)
    
    # Create URL to episode mapping
    url_map = {}
    for ep in sc_episodes:
        url_map[ep['url']] = ep
    
    # Also handle episode 22 special case
    url_map["https://soundcloud.com/planetaryregeneration/planetary-regeneration-podcast-current-events-special-with-rhamis-kent"] = {
        'title': 'Planetary Regeneration Podcast | Current Events Special with Rhamis Kent',
        'description': 'Sense making in times of upheaval such as the social unrest and BlackLivesMatter protests',
        'url': 'https://soundcloud.com/planetaryregeneration/planetary-regeneration-podcast-current-events-special-with-rhamis-kent'
    }
    
    enhanced_count = 0
    
    for i in range(1, 71):
        filename = complete_path / f"episode_{i:03d}_complete.json"
        
        if not filename.exists():
            continue
            
        with open(filename) as f:
            data = json.load(f)
        
        # Skip placeholders
        if data.get('metadata', {}).get('status') == 'not_published':
            continue
        
        # Get URL and title
        url = data.get('url')
        title = data.get('title', '')
        
        # Extract guest from title
        guest = extract_guest_from_title(title)
        
        # Get existing metadata
        metadata = data.get('metadata', {})
        
        # Try to fetch fresh metadata from SoundCloud
        if url:
            logger.info(f"Enhancing episode {i}: {title[:50]}...")
            
            fresh_metadata = fetch_soundcloud_metadata(url)
            if fresh_metadata:
                metadata.update(fresh_metadata)
            
            # Also get info from our stored data
            if url in url_map:
                sc_data = url_map[url]
                if 'description' in sc_data:
                    # Extract hashtags from our stored description too
                    hashtags = list(set(re.findall(r'#\w+', sc_data['description'])))
                    if hashtags and 'hashtags' in metadata:
                        metadata['hashtags'] = list(set(metadata['hashtags'] + hashtags))
                    elif hashtags:
                        metadata['hashtags'] = hashtags
        
        # Add guest info
        if guest:
            metadata['guest'] = guest
            metadata['speakers'] = ['Gregory Landua', guest]
        else:
            metadata['speakers'] = ['Gregory Landua']
        
        # Update the file
        data['metadata'] = metadata
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        enhanced_count += 1
        
        # Log a sample of what we found
        if metadata.get('hashtags') or metadata.get('guest'):
            logger.success(f"  Episode {i}: Guest={metadata.get('guest')}, Hashtags={metadata.get('hashtags', [])[:3]}")
    
    logger.success(f"\nEnhanced metadata for {enhanced_count} episodes!")
    
    # Create a summary report
    create_metadata_report()

def create_metadata_report():
    """Create a summary report of all episodes with metadata"""
    storage_path = Path(__file__).parent.parent / "storage"
    complete_path = storage_path / "podcast_complete"
    
    episodes_data = []
    
    for i in range(1, 71):
        filename = complete_path / f"episode_{i:03d}_complete.json"
        
        if not filename.exists():
            continue
            
        with open(filename) as f:
            data = json.load(f)
        
        metadata = data.get('metadata', {})
        
        episode_info = {
            'number': i,
            'title': data.get('title', ''),
            'url': data.get('url', ''),
            'guest': metadata.get('guest', ''),
            'speakers': metadata.get('speakers', []),
            'hashtags': metadata.get('hashtags', []),
            'status': metadata.get('status', 'transcribed'),
            'duration': metadata.get('duration', 0),
            'upload_date': metadata.get('upload_date', '')
        }
        
        episodes_data.append(episode_info)
    
    # Save the report
    report_file = storage_path / "podcast_metadata_report.json"
    with open(report_file, 'w') as f:
        json.dump(episodes_data, f, indent=2)
    
    logger.info(f"Metadata report saved to {report_file}")
    
    # Print summary statistics
    total = len(episodes_data)
    with_guests = sum(1 for e in episodes_data if e['guest'])
    with_hashtags = sum(1 for e in episodes_data if e['hashtags'])
    not_published = sum(1 for e in episodes_data if e['status'] == 'not_published')
    
    print("\n" + "="*60)
    print("PODCAST METADATA SUMMARY")
    print("="*60)
    print(f"Total episodes: {total}")
    print(f"Episodes with transcripts: {total - not_published}")
    print(f"Episodes not published: {not_published} (numbers 34 and 43)")
    print(f"Episodes with identified guests: {with_guests}")
    print(f"Episodes with hashtags: {with_hashtags}")
    print("="*60)

if __name__ == "__main__":
    enhance_episode_metadata()