#!/usr/bin/env python3
"""
Convert podcast transcript JSON documents to Eliza-compatible markdown format.
Handles both SoundCloud metadata and full transcriptions.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import re

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent))
from conversion_utils import (
    sanitize_filename,
    format_frontmatter,
    create_markdown_document,
    save_markdown_file,
    load_json_document,
    extract_tags_from_content,
    generate_content_id,
    split_large_content,
    generate_description
)

def extract_episode_number(filename: str, title: str = "") -> Optional[int]:
    """
    Extract episode number from filename or title.
    """
    # Try filename first (e.g., episode_01.json)
    match = re.search(r'episode[_-]?(\d+)', filename.lower())
    if match:
        return int(match.group(1))
    
    # Try title (e.g., "Episode 23: Title")
    match = re.search(r'episode\s*(\d+)', title.lower())
    if match:
        return int(match.group(1))
    
    # Try just numbers in filename
    match = re.search(r'(\d+)', filename)
    if match:
        return int(match.group(1))
    
    return None

def format_transcript_content(transcript_data: Any) -> str:
    """
    Format transcript data into readable markdown.
    
    Handles different transcript formats:
    - String content
    - Whisper format with segments
    - Simple text format
    """
    if isinstance(transcript_data, str):
        # Simple string transcript
        return transcript_data
    
    if isinstance(transcript_data, dict):
        # Check for Whisper format
        if 'segments' in transcript_data:
            segments = transcript_data['segments']
            formatted_lines = []
            
            for segment in segments:
                if isinstance(segment, dict):
                    text = segment.get('text', '').strip()
                    if text:
                        # Optionally include timestamps
                        start = segment.get('start')
                        if start is not None:
                            mins = int(start // 60)
                            secs = int(start % 60)
                            formatted_lines.append(f"[{mins:02d}:{secs:02d}] {text}")
                        else:
                            formatted_lines.append(text)
            
            return '\n\n'.join(formatted_lines)
        
        # Check for text field
        if 'text' in transcript_data:
            return transcript_data['text']
        
        # Check for content field
        if 'content' in transcript_data:
            return transcript_data['content']
    
    # Fallback: convert to string
    return str(transcript_data)

def extract_podcast_metadata(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and normalize podcast metadata.
    """
    metadata = {}
    
    # Standard fields
    if 'title' in doc:
        metadata['episode_title'] = doc['title']
    
    if 'description' in doc:
        metadata['description'] = doc['description'][:500]  # Truncate long descriptions
    
    if 'duration' in doc:
        duration = doc['duration']
        if isinstance(duration, (int, float)):
            # Convert seconds to human-readable format
            hours = int(duration // 3600)
            mins = int((duration % 3600) // 60)
            if hours > 0:
                metadata['duration'] = f"{hours}h {mins}m"
            else:
                metadata['duration'] = f"{mins}m"
        else:
            metadata['duration'] = str(duration)
    
    if 'date' in doc or 'created_at' in doc or 'published_at' in doc:
        date = doc.get('date') or doc.get('created_at') or doc.get('published_at')
        metadata['published_date'] = date
    
    if 'url' in doc:
        metadata['source_url'] = doc['url']
    
    if 'speakers' in doc:
        metadata['speakers'] = doc['speakers']
    elif 'guests' in doc:
        metadata['speakers'] = doc['guests']
    
    return metadata

def convert_podcast_document(doc_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Convert a single podcast transcript to markdown.
    
    Args:
        doc_path: Path to the JSON document
        output_dir: Directory to save markdown file
    
    Returns:
        Path to the created markdown file, or None if failed
    """
    # Load document
    doc = load_json_document(doc_path)
    if not doc:
        return None
    
    # Extract title and episode number
    title = doc.get('title', 'Untitled Episode')
    episode_num = extract_episode_number(doc_path.name, title)
    
    # Format title with episode number if available
    if episode_num and f"Episode {episode_num}" not in title:
        formatted_title = f"Episode {episode_num}: {title}"
    else:
        formatted_title = title
    
    # Extract transcript content
    transcript = doc.get('transcript') or doc.get('transcription') or doc.get('content', '')
    
    # Handle different transcript formats
    if isinstance(transcript, dict) or isinstance(transcript, list):
        content = format_transcript_content(transcript)
    else:
        content = str(transcript)
    
    # Skip if no real content
    if not content or content.strip() == '' or 'not published' in content.lower():
        print(f"  Skipping {doc_path.name} - no transcript content")
        return None
    
    # Extract metadata
    metadata = extract_podcast_metadata(doc)
    
    # Generate enhanced tags
    tags = extract_tags_from_content(content, title)
    
    # Add podcast-specific tags
    podcast_tags = ['podcast', 'planetary-regeneration', 'audio-transcript', 'interview']
    for tag in podcast_tags:
        if tag not in tags:
            tags.append(tag)
    
    tags = list(set(tags))[:15]  # Remove duplicates, limit to 15
    
    # Generate description
    if 'description' in doc and doc['description']:
        description = doc['description'][:200]
    else:
        description = generate_description(content, formatted_title)
    
    # Create frontmatter metadata optimized for Eliza
    frontmatter_data = {
        'title': formatted_title,
        'description': description,
        'source': 'podcast:soundcloud',
        'source_type': 'podcast',
        'episode_number': episode_num,
        'tags': tags,
        'category': 'community',
        'subcategory': 'podcasts',
        'date': metadata.get('published_date', datetime.now().isoformat()),
        'document_id': doc.get('id', generate_content_id(content, 'podcast')),
        'koi_rid': doc.get('koi_rid', None)
    }
    
    # Add additional metadata
    frontmatter_data.update(metadata)
    
    # Remove None values
    frontmatter_data = {k: v for k, v in frontmatter_data.items() if v is not None}
    
    # Split large transcripts if needed
    content_parts = split_large_content(content, max_size=100000)
    
    if len(content_parts) > 1:
        # Multiple parts needed
        saved_paths = []
        for part_num, part_content in enumerate(content_parts, 1):
            part_metadata = frontmatter_data.copy()
            part_metadata['part'] = f"{part_num}/{len(content_parts)}"
            
            # Create markdown document for this part
            markdown = create_markdown_document(
                title=f"{formatted_title} (Part {part_num})",
                content=part_content,
                metadata=part_metadata,
                source_url=metadata.get('source_url')
            )
            
            # Generate filename with part number
            if episode_num:
                filename = f"podcast_episode_{episode_num:02d}_part{part_num}"
            else:
                filename = f"podcast_{sanitize_filename(title)}_part{part_num}"
            
            # Save file
            saved_path = save_markdown_file(
                content=markdown,
                filename=filename,
                output_dir=output_dir,
                overwrite=False
            )
            saved_paths.append(saved_path)
        
        return saved_paths[0] if saved_paths else None
    else:
        # Single document
        markdown = create_markdown_document(
            title=formatted_title,
            content=content,
            metadata=frontmatter_data,
            source_url=metadata.get('source_url')
        )
        
        # Generate filename
        if episode_num:
            filename = f"podcast_episode_{episode_num:02d}"
        else:
            filename = f"podcast_{sanitize_filename(title)}"
        
        # Save file
        saved_path = save_markdown_file(
            content=markdown,
            filename=filename,
            output_dir=output_dir,
            overwrite=False
        )
        
        return saved_path

def convert_all_podcast_documents(
    source_dirs: List[Path],
    output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convert all podcast documents to markdown.
    
    Args:
        source_dirs: List of directories containing podcast JSON documents
        output_dir: Directory to save markdown files
        limit: Optional limit on number of files to process
    
    Returns:
        Dictionary with conversion statistics
    """
    output_dir = Path(output_dir)
    
    # Find all podcast documents from multiple sources
    all_files = []
    
    for source_dir in source_dirs:
        source_dir = Path(source_dir)
        if source_dir.exists():
            # Look for episode files
            episode_files = list(source_dir.glob("episode_*.json"))
            all_files.extend(episode_files)
            
            # Also look for soundcloud files
            soundcloud_files = list(source_dir.glob("soundcloud_*.json"))
            all_files.extend(soundcloud_files)
            
            # Look for any podcast files
            podcast_files = list(source_dir.glob("podcast_*.json"))
            all_files.extend(podcast_files)
    
    # Remove duplicates based on filename
    seen_names = set()
    unique_files = []
    for f in all_files:
        if f.name not in seen_names:
            unique_files.append(f)
            seen_names.add(f.name)
    
    all_files = unique_files
    
    if limit:
        all_files = all_files[:limit]
    
    print(f"Found {len(all_files)} podcast documents")
    if limit:
        print(f"Processing first {limit} files...")
    
    # Process each file
    successful = []
    failed = []
    skipped = []
    
    for i, file_path in enumerate(all_files, 1):
        try:
            result = convert_podcast_document(file_path, output_dir)
            if result:
                successful.append(result)
                print(f"✓ [{i}/{len(all_files)}] Converted: {file_path.name}")
            else:
                skipped.append(file_path)
                print(f"○ [{i}/{len(all_files)}] Skipped: {file_path.name} (no content)")
        except Exception as e:
            failed.append(file_path)
            print(f"✗ [{i}/{len(all_files)}] Error converting {file_path.name}: {e}")
        
        # Progress indicator
        if i % 10 == 0:
            print(f"Progress: {i}/{len(all_files)} files processed...")
    
    # Summary statistics
    stats = {
        'total_files': len(all_files),
        'successful': len(successful),
        'failed': len(failed),
        'skipped': len(skipped),
        'output_directory': str(output_dir),
        'failed_files': [str(f) for f in failed],
        'skipped_files': [str(f) for f in skipped]
    }
    
    return stats

def main():
    """Main execution"""
    print("Podcast Transcript Converter")
    print("=" * 50)
    
    # Set up paths - check multiple locations for podcast data
    source_dirs = [
        Path("/home/regenai/project/indexing/podcast/storage/podcast_complete"),
        Path("/home/regenai/project/indexing/storage/documents"),  # Some soundcloud files here
        Path("/home/regenai/project/indexing/podcast/storage")
    ]
    
    output_dir = Path("/opt/projects/GAIA/knowledge/regen-network/community/podcasts")
    
    # Check if running in test mode
    import sys
    test_mode = '--test' in sys.argv
    limit = 5 if test_mode else None
    
    if test_mode:
        print("Running in TEST MODE - converting only 5 documents")
        output_dir = Path("/home/regenai/project/indexing/test_output/podcasts")
    
    # Run conversion
    stats = convert_all_podcast_documents(source_dirs, output_dir, limit)
    
    # Print summary
    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files processed: {stats['total_files']}")
    print(f"Successfully converted: {stats['successful']}")
    print(f"Skipped (no content): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    
    if stats['failed'] > 0:
        print("\nFailed files:")
        for failed_file in stats['failed_files'][:5]:  # Show first 5
            print(f"  - {Path(failed_file).name}")
        if len(stats['failed_files']) > 5:
            print(f"  ... and {len(stats['failed_files']) - 5} more")
    
    print(f"\nOutput directory: {stats['output_directory']}")
    print("=" * 50)
    
    # Save stats to file
    stats_file = Path(output_dir) / "_podcast_conversion_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"Stats saved to: {stats_file}")

if __name__ == "__main__":
    main()