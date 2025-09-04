#!/usr/bin/env python3
"""
Convert GitHub and GitLab JSON documents to Eliza-compatible markdown format.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent))
from conversion_utils import (
    sanitize_filename,
    format_frontmatter,
    create_markdown_document,
    save_markdown_file,
    load_json_document,
    preserve_code_blocks,
    extract_tags_from_content,
    generate_content_id,
    generate_description
)

def convert_github_document(doc_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Convert a single GitHub/GitLab document to markdown.
    
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
    
    # Extract fields
    title = doc.get('title', 'Untitled Document')
    content = doc.get('content', '')
    url = doc.get('url', '')
    source = doc.get('source', 'github')
    source_type = doc.get('source_type', 'github')
    
    # Extract metadata
    metadata = doc.get('metadata', {})
    repository = metadata.get('repository', '')
    file_path = metadata.get('file_path', '')
    branch = metadata.get('branch', 'main')
    
    # Generate tags with enhanced extraction
    tags = extract_tags_from_content(content, title)
    if not tags and doc.get('tags'):
        tags = doc.get('tags', [])
    
    # Generate description for better search
    description = generate_description(content, title)
    
    # Determine subcategory based on repository
    subcategory = ''
    if 'regen-ledger' in repository.lower():
        subcategory = 'regen-ledger'
    elif 'regen-web' in repository.lower():
        subcategory = 'regen-web'
    elif 'regen-js' in repository.lower():
        subcategory = 'regen-js'
    elif source_type == 'gitlab':
        subcategory = 'historical'
    else:
        subcategory = 'other'
    
    # Create frontmatter metadata optimized for Eliza
    frontmatter_data = {
        'title': title,
        'description': description,
        'source': source,
        'source_type': source_type,
        'repository': repository,
        'file_path': file_path,
        'branch': branch,
        'url': url,
        'tags': tags,
        'category': 'technical',
        'subcategory': subcategory,
        'date': doc.get('last_modified', datetime.now().isoformat()),
        'document_id': doc.get('id', generate_content_id(content, source)),
        'koi_rid': doc.get('koi_rid', None)
    }
    
    # Remove None values
    frontmatter_data = {k: v for k, v in frontmatter_data.items() if v is not None}
    
    # Create markdown document
    markdown = create_markdown_document(
        title=title,
        content=content,
        metadata=frontmatter_data,
        source_url=url
    )
    
    # Generate filename
    filename = f"{source_type}_{subcategory}_{sanitize_filename(title)}"
    
    # Save to appropriate subdirectory
    if subcategory:
        final_output_dir = output_dir / subcategory
    else:
        final_output_dir = output_dir
    
    # Save file
    saved_path = save_markdown_file(
        content=markdown,
        filename=filename,
        output_dir=final_output_dir,
        overwrite=False
    )
    
    return saved_path

def convert_all_github_documents(
    source_dir: Path,
    output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convert all GitHub and GitLab documents to markdown.
    
    Args:
        source_dir: Directory containing JSON documents
        output_dir: Directory to save markdown files
        limit: Optional limit on number of files to process
    
    Returns:
        Dictionary with conversion statistics
    """
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    
    # Find all GitHub and GitLab documents
    github_files = list(source_dir.glob("github_*.json"))
    gitlab_files = list(source_dir.glob("gitlab_*.json"))
    all_files = github_files + gitlab_files
    
    if limit:
        all_files = all_files[:limit]
    
    print(f"Found {len(github_files)} GitHub and {len(gitlab_files)} GitLab documents")
    if limit:
        print(f"Processing first {limit} files...")
    
    # Process each file
    successful = []
    failed = []
    
    for i, file_path in enumerate(all_files, 1):
        try:
            result = convert_github_document(file_path, output_dir)
            if result:
                successful.append(result)
                print(f"✓ [{i}/{len(all_files)}] Converted: {file_path.name}")
            else:
                failed.append(file_path)
                print(f"✗ [{i}/{len(all_files)}] Failed: {file_path.name}")
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
        'github_count': len([f for f in successful if 'github' in str(f)]),
        'gitlab_count': len([f for f in successful if 'gitlab' in str(f)]),
        'output_directory': str(output_dir),
        'failed_files': [str(f) for f in failed]
    }
    
    return stats

def main():
    """Main execution"""
    print("GitHub/GitLab Document Converter")
    print("=" * 50)
    
    # Set up paths
    source_dir = Path("/home/regenai/project/indexing/storage/documents")
    output_dir = Path("/opt/projects/GAIA/knowledge/regen-network/technical")
    
    # Check if running in test mode
    import sys
    test_mode = '--test' in sys.argv
    limit = 5 if test_mode else None
    
    if test_mode:
        print("Running in TEST MODE - converting only 5 documents")
        output_dir = Path("/home/regenai/project/indexing/test_output/technical")
    
    # Run conversion
    stats = convert_all_github_documents(source_dir, output_dir, limit)
    
    # Print summary
    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files processed: {stats['total_files']}")
    print(f"Successfully converted: {stats['successful']}")
    print(f"  - GitHub: {stats['github_count']}")
    print(f"  - GitLab: {stats['gitlab_count']}")
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
    stats_file = Path(output_dir) / "_conversion_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"Stats saved to: {stats_file}")

if __name__ == "__main__":
    main()