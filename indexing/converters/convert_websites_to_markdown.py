#!/usr/bin/env python3
"""
Convert website JSON documents to Eliza-compatible markdown format.
Categorizes content by domain into appropriate knowledge folders.
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
    extract_domain_from_url,
    categorize_by_url,
    categorize_by_content,
    extract_tags_from_content,
    generate_content_id,
    clean_html_content,
    generate_description
)

def determine_website_category(url: str, content: str, title: str) -> str:
    """
    Determine the appropriate category for website content.
    
    Categories:
    - technical: docs.regen.network, guides.regen.network
    - governance: regen.foundation (governance pages)
    - ecological: registry.regen.network
    - community: forums, blogs
    """
    domain = extract_domain_from_url(url)
    
    # Domain-based categorization
    if 'docs.regen.network' in domain or 'guides.regen.network' in domain:
        return 'technical'
    elif 'registry.regen.network' in domain:
        return 'ecological'
    elif 'regen.foundation' in domain:
        # Check if it's governance-related
        if any(x in url.lower() for x in ['governance', 'proposal', 'vote']):
            return 'governance'
        else:
            return 'governance'  # Most foundation content is governance
    elif 'forum' in domain:
        return 'community'
    
    # Content-based categorization as fallback
    return categorize_by_content(content, title)

def determine_subcategory(url: str, category: str) -> str:
    """
    Determine subcategory based on URL and main category.
    """
    url_lower = url.lower()
    
    if category == 'technical':
        if 'guides' in url_lower:
            return 'guides'
        elif 'api' in url_lower:
            return 'api'
        elif 'tutorial' in url_lower:
            return 'tutorials'
        else:
            return 'docs'
    
    elif category == 'ecological':
        if 'methodology' in url_lower or 'methodologies' in url_lower:
            return 'methodologies'
        elif 'project' in url_lower:
            return 'projects'
        elif 'credit' in url_lower:
            return 'credits'
        else:
            return 'registry'
    
    elif category == 'governance':
        if 'proposal' in url_lower:
            return 'proposals'
        elif 'vote' in url_lower or 'voting' in url_lower:
            return 'voting'
        else:
            return 'foundation'
    
    elif category == 'community':
        if 'forum' in url_lower:
            return 'forums'
        elif 'blog' in url_lower:
            return 'blogs'
        else:
            return 'general'
    
    return ''

def convert_website_document(doc_path: Path, base_output_dir: Path) -> Optional[Path]:
    """
    Convert a single website document to markdown.
    
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
    title = doc.get('title', 'Untitled Document')
    content = doc.get('content', '')
    url = doc.get('url', '')
    source = doc.get('source', 'website')
    source_type = doc.get('source_type', 'website')
    
    # Extract metadata
    metadata = doc.get('metadata', {})
    domain = extract_domain_from_url(url)
    
    # Determine category and subcategory
    category = determine_website_category(url, content, title)
    subcategory = determine_subcategory(url, category)
    
    # Generate enhanced tags
    tags = extract_tags_from_content(content, title)
    
    # Add domain as tag if not already present
    domain_tag = domain.replace('.', '_')
    if domain and domain_tag not in tags:
        tags.append(domain_tag)
    
    # Generate description for better search
    description = generate_description(content, title)
    
    # Create frontmatter metadata optimized for Eliza
    frontmatter_data = {
        'title': title,
        'description': description,
        'source': f"website:{domain}",
        'source_type': source_type,
        'domain': domain,
        'url': url,
        'tags': tags,
        'category': category,
        'subcategory': subcategory,
        'date': doc.get('last_modified', datetime.now().isoformat()),
        'document_id': doc.get('id', generate_content_id(content, source)),
        'koi_rid': doc.get('koi_rid', None)
    }
    
    # Add specific metadata based on domain
    if 'registry.regen.network' in domain:
        # Check for credit class or project info
        if 'C0' in content or 'class' in title.lower():
            frontmatter_data['content_type'] = 'credit_class'
        elif 'P0' in content or 'project' in title.lower():
            frontmatter_data['content_type'] = 'project'
        elif 'methodology' in title.lower() or 'methodology' in url.lower():
            frontmatter_data['content_type'] = 'methodology'
    
    # Remove None values
    frontmatter_data = {k: v for k, v in frontmatter_data.items() if v is not None}
    
    # Clean content (remove excessive HTML artifacts)
    content = clean_html_content(content)
    
    # Create markdown document
    markdown = create_markdown_document(
        title=title,
        content=content,
        metadata=frontmatter_data,
        source_url=url
    )
    
    # Generate filename
    filename = f"website_{domain.replace('.', '_')}_{sanitize_filename(title)}"
    
    # Determine output directory based on category
    output_dir = base_output_dir / category
    if subcategory:
        output_dir = output_dir / subcategory
    
    # Save file
    saved_path = save_markdown_file(
        content=markdown,
        filename=filename,
        output_dir=output_dir,
        overwrite=False
    )
    
    return saved_path

def convert_all_website_documents(
    source_dir: Path,
    base_output_dir: Path,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Convert all website documents to markdown.
    
    Args:
        source_dir: Directory containing JSON documents
        base_output_dir: Base directory for knowledge structure
        limit: Optional limit on number of files to process
    
    Returns:
        Dictionary with conversion statistics
    """
    source_dir = Path(source_dir)
    base_output_dir = Path(base_output_dir)
    
    # Find all website documents
    website_files = list(source_dir.glob("website_*.json"))
    
    if limit:
        website_files = website_files[:limit]
    
    print(f"Found {len(website_files)} website documents")
    if limit:
        print(f"Processing first {limit} files...")
    
    # Track statistics by category and domain
    stats_by_category = {
        'technical': 0,
        'governance': 0,
        'ecological': 0,
        'community': 0,
        'shared': 0
    }
    stats_by_domain = {}
    
    # Process each file
    successful = []
    failed = []
    
    for i, file_path in enumerate(website_files, 1):
        try:
            # Load to get URL for domain tracking
            doc = load_json_document(file_path)
            if doc:
                url = doc.get('url', '')
                domain = extract_domain_from_url(url)
                
                # Convert document
                result = convert_website_document(file_path, base_output_dir)
                
                if result:
                    successful.append(result)
                    
                    # Update statistics
                    category = determine_website_category(url, doc.get('content', ''), doc.get('title', ''))
                    stats_by_category[category] = stats_by_category.get(category, 0) + 1
                    stats_by_domain[domain] = stats_by_domain.get(domain, 0) + 1
                    
                    print(f"✓ [{i}/{len(website_files)}] Converted: {file_path.name} → {category}")
                else:
                    failed.append(file_path)
                    print(f"✗ [{i}/{len(website_files)}] Failed: {file_path.name}")
            else:
                failed.append(file_path)
                print(f"✗ [{i}/{len(website_files)}] Could not load: {file_path.name}")
                
        except Exception as e:
            failed.append(file_path)
            print(f"✗ [{i}/{len(website_files)}] Error converting {file_path.name}: {e}")
        
        # Progress indicator
        if i % 10 == 0:
            print(f"Progress: {i}/{len(website_files)} files processed...")
    
    # Summary statistics
    stats = {
        'total_files': len(website_files),
        'successful': len(successful),
        'failed': len(failed),
        'by_category': stats_by_category,
        'by_domain': stats_by_domain,
        'output_directory': str(base_output_dir),
        'failed_files': [str(f) for f in failed]
    }
    
    return stats

def main():
    """Main execution"""
    print("Website Document Converter")
    print("=" * 50)
    
    # Set up paths
    source_dir = Path("/home/regenai/project/indexing/storage/documents")
    base_output_dir = Path("/opt/projects/GAIA/knowledge/regen-network")
    
    # Check if running in test mode
    import sys
    test_mode = '--test' in sys.argv
    limit = 5 if test_mode else None
    
    if test_mode:
        print("Running in TEST MODE - converting only 5 documents")
        base_output_dir = Path("/home/regenai/project/indexing/test_output")
    
    # Run conversion
    stats = convert_all_website_documents(source_dir, base_output_dir, limit)
    
    # Print summary
    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files processed: {stats['total_files']}")
    print(f"Successfully converted: {stats['successful']}")
    print(f"Failed: {stats['failed']}")
    
    print("\nBy Category:")
    for category, count in stats['by_category'].items():
        if count > 0:
            print(f"  - {category}: {count} documents")
    
    print("\nBy Domain:")
    for domain, count in sorted(stats['by_domain'].items(), key=lambda x: x[1], reverse=True):
        print(f"  - {domain}: {count} documents")
    
    if stats['failed'] > 0:
        print("\nFailed files:")
        for failed_file in stats['failed_files'][:5]:  # Show first 5
            print(f"  - {Path(failed_file).name}")
        if len(stats['failed_files']) > 5:
            print(f"  ... and {len(stats['failed_files']) - 5} more")
    
    print(f"\nOutput directory: {stats['output_directory']}")
    print("=" * 50)
    
    # Save stats to file
    stats_file = Path(base_output_dir) / "_website_conversion_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"Stats saved to: {stats_file}")

if __name__ == "__main__":
    main()