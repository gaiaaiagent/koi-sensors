#!/usr/bin/env python3
"""
Convert Medium article JSON documents to Eliza-compatible markdown format.
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
    clean_html_content,
    categorize_by_content,
    generate_description
)

def extract_author_from_medium(doc: Dict[str, Any]) -> str:
    """
    Extract author information from Medium article.
    """
    # Check various possible author fields
    if 'author' in doc:
        return doc['author']
    
    if 'metadata' in doc and 'author' in doc['metadata']:
        return doc['metadata']['author']
    
    # Check creator field
    if 'creator' in doc:
        return doc['creator']
    
    # Default to Regen Network
    return "Regen Network"

def extract_publish_date(doc: Dict[str, Any]) -> str:
    """
    Extract and format publish date from Medium article.
    """
    # Check various date fields
    for field in ['published_at', 'publishedAt', 'date', 'created_at', 'pubDate']:
        if field in doc:
            date_str = doc[field]
            # Try to parse and reformat if needed
            try:
                if isinstance(date_str, str) and 'T' in date_str:
                    return date_str.split('T')[0]  # Get just the date part
                return str(date_str)
            except:
                pass
    
    # Check in metadata
    if 'metadata' in doc:
        for field in ['published_at', 'date', 'pubDate']:
            if field in doc['metadata']:
                return str(doc['metadata'][field])
    
    # Default to current date
    return datetime.now().strftime('%Y-%m-%d')

def categorize_medium_article(title: str, content: str) -> str:
    """
    Categorize Medium article based on content.
    
    Categories:
    - governance: Governance, proposals, foundation updates
    - ecological: Environmental topics, credits, methodologies
    - technical: Development updates, technical explanations
    - community: General updates, events, partnerships
    """
    text = (title + " " + content).lower()
    
    # Check for specific patterns
    if any(word in text for word in ['governance', 'proposal', 'vote', 'validator', 'delegation']):
        return 'governance'
    elif any(word in text for word in ['carbon', 'credit', 'methodology', 'biodiversity', 'conservation', 'restoration']):
        return 'ecological'
    elif any(word in text for word in ['upgrade', 'mainnet', 'testnet', 'api', 'sdk', 'technical', 'development']):
        return 'technical'
    else:
        return 'community'

def clean_medium_content(content: str) -> str:
    """
    Clean Medium-specific formatting from content.
    """
    # Remove Medium clap indicators
    content = re.sub(r'👏+', '', content)
    
    # Remove "Follow us" type CTAs
    content = re.sub(r'Follow .* on (Twitter|Medium|LinkedIn).*', '', content, flags=re.IGNORECASE)
    
    # Clean up excessive newlines
    content = re.sub(r'\n{4,}', '\n\n\n', content)
    
    # Clean HTML if present
    content = clean_html_content(content)
    
    # Remove Medium's "Continue reading" markers
    content = re.sub(r'Continue reading.*', '', content, flags=re.IGNORECASE)
    
    return content.strip()

def convert_medium_document(doc_path: Path, base_output_dir: Path) -> Optional[Path]:
    """
    Convert a single Medium article to markdown.
    
    Args:
        doc_path: Path to the JSON document
        base_output_dir: Base directory for knowledge structure
    
    Returns:
        Path to the created markdown file, or None if failed
    """
    # Load document
    doc = load_json_document(doc_path)
    if not doc:
        return None
    
    # Extract fields
    title = doc.get('title', 'Untitled Article')
    content = doc.get('content', '')
    url = doc.get('url', doc.get('link', ''))
    
    # Skip if no content
    if not content or len(content.strip()) < 100:
        print(f"  Skipping {doc_path.name} - insufficient content")
        return None
    
    # Clean content
    content = clean_medium_content(content)
    
    # Extract metadata
    author = extract_author_from_medium(doc)
    publish_date = extract_publish_date(doc)
    
    # Determine category
    category = categorize_medium_article(title, content)
    
    # Generate enhanced tags
    tags = extract_tags_from_content(content, title)
    
    # Add Medium-specific tags
    medium_tags = ['medium-article', 'blog-post']
    
    # Add category-specific tags
    if category == 'governance':
        medium_tags.extend(['governance-update', 'regen-governance'])
    elif category == 'ecological':
        medium_tags.extend(['ecological-impact', 'regenerative-practice'])
    elif category == 'technical':
        medium_tags.extend(['technical-update', 'development-update'])
    else:
        medium_tags.append('community-update')
    
    for tag in medium_tags:
        if tag not in tags:
            tags.append(tag)
    
    tags = list(set(tags))[:15]  # Remove duplicates and limit
    
    # Extract reading time if available
    reading_time = None
    if 'reading_time' in doc:
        reading_time = doc['reading_time']
    elif 'metadata' in doc and 'reading_time' in doc['metadata']:
        reading_time = doc['metadata']['reading_time']
    
    # Generate or extract description
    if 'description' in doc and doc['description']:
        description = doc['description'][:200]
    elif 'subtitle' in doc and doc['subtitle']:
        description = doc['subtitle'][:200]
    else:
        description = generate_description(content, title)
    
    # Create frontmatter metadata optimized for Eliza
    frontmatter_data = {
        'title': title,
        'description': description,
        'source': 'medium:regen-network',
        'source_type': 'article',
        'author': author,
        'published_date': publish_date,
        'url': url,
        'tags': tags,
        'category': category,
        'subcategory': 'articles',
        'date': publish_date,
        'document_id': doc.get('id', generate_content_id(content, 'medium')),
        'koi_rid': doc.get('koi_rid', None)
    }
    
    # Add reading time if available
    if reading_time:
        frontmatter_data['reading_time'] = reading_time
    
    # Remove None values
    frontmatter_data = {k: v for k, v in frontmatter_data.items() if v is not None}
    
    # Create markdown document
    markdown = create_markdown_document(
        title=title,
        content=content,
        metadata=frontmatter_data,
        source_url=url
    )
    
    # Generate filename - use date if available for chronological sorting
    try:
        date_prefix = publish_date.replace('-', '')[:8]  # YYYYMMDD
        filename = f"medium_{date_prefix}_{sanitize_filename(title)}"
    except:
        filename = f"medium_{sanitize_filename(title)}"
    
    # Determine output directory based on category
    output_dir = base_output_dir / category / 'articles'
    
    # Save file
    saved_path = save_markdown_file(
        content=markdown,
        filename=filename,
        output_dir=output_dir,
        overwrite=False
    )
    
    return saved_path

def convert_all_medium_documents(
    source_dir: Path,
    base_output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convert all Medium articles to markdown.
    
    Args:
        source_dir: Directory containing JSON documents
        base_output_dir: Base directory for knowledge structure
        limit: Optional limit on number of files to process
    
    Returns:
        Dictionary with conversion statistics
    """
    source_dir = Path(source_dir)
    base_output_dir = Path(base_output_dir)
    
    # Find all Medium documents
    medium_files = list(source_dir.glob("medium_*.json"))
    
    if limit:
        medium_files = medium_files[:limit]
    
    print(f"Found {len(medium_files)} Medium articles")
    if limit:
        print(f"Processing first {limit} files...")
    
    # Track statistics by category
    stats_by_category = {
        'governance': 0,
        'ecological': 0,
        'technical': 0,
        'community': 0
    }
    
    # Process each file
    successful = []
    failed = []
    skipped = []
    
    for i, file_path in enumerate(medium_files, 1):
        try:
            result = convert_medium_document(file_path, base_output_dir)
            if result:
                successful.append(result)
                
                # Update category stats
                doc = load_json_document(file_path)
                if doc:
                    category = categorize_medium_article(
                        doc.get('title', ''),
                        doc.get('content', '')
                    )
                    stats_by_category[category] = stats_by_category.get(category, 0) + 1
                
                print(f"✓ [{i}/{len(medium_files)}] Converted: {file_path.name}")
            else:
                skipped.append(file_path)
                print(f"○ [{i}/{len(medium_files)}] Skipped: {file_path.name}")
        except Exception as e:
            failed.append(file_path)
            print(f"✗ [{i}/{len(medium_files)}] Error converting {file_path.name}: {e}")
        
        # Progress indicator
        if i % 10 == 0:
            print(f"Progress: {i}/{len(medium_files)} files processed...")
    
    # Summary statistics
    stats = {
        'total_files': len(medium_files),
        'successful': len(successful),
        'failed': len(failed),
        'skipped': len(skipped),
        'by_category': stats_by_category,
        'output_directory': str(base_output_dir),
        'failed_files': [str(f) for f in failed],
        'skipped_files': [str(f) for f in skipped]
    }
    
    return stats

def main():
    """Main execution"""
    print("Medium Articles Converter")
    print("=" * 50)
    
    # Set up paths
    source_dir = Path("/home/regenai/project/indexing/medium/storage/articles")
    base_output_dir = Path("/opt/projects/GAIA/knowledge/regen-network")
    
    # Check if running in test mode
    import sys
    test_mode = '--test' in sys.argv
    limit = 5 if test_mode else None
    
    if test_mode:
        print("Running in TEST MODE - converting only 5 documents")
        base_output_dir = Path("/home/regenai/project/indexing/test_output")
    
    # Run conversion
    stats = convert_all_medium_documents(source_dir, base_output_dir, limit)
    
    # Print summary
    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files processed: {stats['total_files']}")
    print(f"Successfully converted: {stats['successful']}")
    print(f"Skipped (no/short content): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    
    print("\nBy Category:")
    for category, count in stats['by_category'].items():
        if count > 0:
            print(f"  - {category}: {count} articles")
    
    if stats['failed'] > 0:
        print("\nFailed files:")
        for failed_file in stats['failed_files'][:5]:  # Show first 5
            print(f"  - {Path(failed_file).name}")
        if len(stats['failed_files']) > 5:
            print(f"  ... and {len(stats['failed_files']) - 5} more")
    
    print(f"\nOutput directory: {stats['output_directory']}")
    print("=" * 50)
    
    # Save stats to file
    stats_file = Path(base_output_dir) / "_medium_conversion_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"Stats saved to: {stats_file}")

if __name__ == "__main__":
    main()