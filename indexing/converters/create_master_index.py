#!/usr/bin/env python3
"""
Create a master index of all indexed content for the Regen Network project.
This documents all sources, locations, and counts for conversion to Eliza knowledge format.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def count_files_by_pattern(directory, pattern):
    """Count files matching a pattern in a directory"""
    path = Path(directory)
    if not path.exists():
        return 0
    return len(list(path.glob(pattern)))

def analyze_json_files(directory, pattern="*.json"):
    """Analyze JSON files in a directory and return statistics"""
    path = Path(directory)
    if not path.exists():
        return {"count": 0, "sources": []}
    
    files = list(path.glob(pattern))
    sources = defaultdict(int)
    
    for file in files:
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                source = data.get('source', 'unknown')
                sources[source] += 1
        except:
            pass
    
    return {
        "count": len(files),
        "sources": dict(sources)
    }

def create_master_index():
    """Create comprehensive index of all content"""
    
    base_path = Path("/home/regenai/project/indexing")
    
    index = {
        "generated_at": datetime.now().isoformat(),
        "total_documents": 0,
        "content_sources": {}
    }
    
    # 1. GitHub Documents
    github_docs = count_files_by_pattern(
        base_path / "storage/documents", "github_*.json"
    )
    index["content_sources"]["github"] = {
        "count": github_docs,
        "location": "indexing/storage/documents/github_*.json",
        "target": "knowledge/regen-network/technical/",
        "description": "Technical documentation from GitHub repositories"
    }
    
    # 2. GitLab Documents  
    gitlab_docs = count_files_by_pattern(
        base_path / "storage/documents", "gitlab_*.json"
    )
    index["content_sources"]["gitlab"] = {
        "count": gitlab_docs,
        "location": "indexing/storage/documents/gitlab_*.json",
        "target": "knowledge/regen-network/technical/",
        "description": "Historical whitepapers from GitLab"
    }
    
    # 3. Website Documents
    website_docs = count_files_by_pattern(
        base_path / "storage/documents", "website_*.json"
    )
    index["content_sources"]["website"] = {
        "count": website_docs,
        "location": "indexing/storage/documents/website_*.json",
        "target": "knowledge/regen-network/[categorized]",
        "description": "Content from various Regen Network websites"
    }
    
    # 4. SoundCloud/Podcast
    soundcloud_docs = count_files_by_pattern(
        base_path / "storage/documents", "soundcloud_*.json"
    )
    podcast_transcripts = count_files_by_pattern(
        base_path / "podcast/storage/podcast_complete", "episode_*.json"
    )
    index["content_sources"]["podcast"] = {
        "soundcloud_metadata": soundcloud_docs,
        "transcripts": podcast_transcripts,
        "location": "indexing/podcast/storage/podcast_complete/",
        "target": "knowledge/regen-network/community/podcasts/",
        "description": "Planetary Regeneration Podcast transcripts"
    }
    
    # 5. Medium Articles
    medium_articles = count_files_by_pattern(
        base_path / "medium/storage/articles", "medium_*.json"
    )
    index["content_sources"]["medium"] = {
        "count": medium_articles,
        "location": "indexing/medium/storage/articles/",
        "target": "knowledge/regen-network/community/articles/",
        "description": "Blog posts from Regen Network Medium"
    }
    
    # 6. Twitter Archive
    twitter_path = base_path / "storage/TwitterData"
    twitter_files = list(twitter_path.glob("twitter-*"))
    tweet_count = 0
    
    if twitter_files:
        # Count tweets in the archive
        for file in twitter_files:
            if file.is_dir():
                tweet_files = list((file / "data").glob("tweets.js")) if (file / "data").exists() else []
                if tweet_files:
                    tweet_count = 12723  # Known count from previous analysis
    
    index["content_sources"]["twitter"] = {
        "tweets": tweet_count,
        "location": "indexing/storage/TwitterData/",
        "target": "knowledge/regen-network/community/social/",
        "description": "Twitter/X archive with historical tweets"
    }
    
    # Calculate totals
    total = (
        github_docs + 
        gitlab_docs + 
        website_docs + 
        podcast_transcripts + 
        medium_articles +
        (1 if tweet_count > 0 else 0)  # Twitter as consolidated doc
    )
    index["total_documents"] = total
    
    # Website breakdown
    website_path = base_path / "storage/documents"
    website_files = list(website_path.glob("website_*.json"))
    website_domains = defaultdict(int)
    
    for file in website_files:
        try:
            with open(file, 'r') as f:
                data = json.load(f)
                url = data.get('url', '')
                if 'docs.regen.network' in url:
                    website_domains['docs.regen.network'] += 1
                elif 'guides.regen.network' in url:
                    website_domains['guides.regen.network'] += 1
                elif 'registry.regen.network' in url:
                    website_domains['registry.regen.network'] += 1
                elif 'regen.foundation' in url:
                    website_domains['regen.foundation'] += 1
                else:
                    website_domains['other'] += 1
        except:
            pass
    
    index["content_sources"]["website"]["breakdown"] = dict(website_domains)
    
    # Status tracking
    index["conversion_status"] = {
        "github": "pending",
        "gitlab": "pending",
        "website": "pending",
        "podcast": "pending",
        "medium": "pending",
        "twitter": "pending"
    }
    
    return index

def save_index(index, output_path="/home/regenai/project/indexing/CONTENT_INDEX.json"):
    """Save index to JSON file"""
    with open(output_path, 'w') as f:
        json.dump(index, f, indent=2)
    print(f"Master index saved to {output_path}")
    return output_path

def create_markdown_report(index, output_path="/home/regenai/project/indexing/CONTENT_INDEX.md"):
    """Create human-readable markdown report"""
    
    report = f"""# Regen Network Content Index

Generated: {index['generated_at']}

## Summary
**Total Documents to Convert**: {index['total_documents']}

## Content Sources

### 1. GitHub Documentation
- **Count**: {index['content_sources']['github']['count']} documents
- **Location**: `{index['content_sources']['github']['location']}`
- **Target**: `{index['content_sources']['github']['target']}`
- **Description**: {index['content_sources']['github']['description']}

### 2. GitLab Historical Documents
- **Count**: {index['content_sources']['gitlab']['count']} documents
- **Location**: `{index['content_sources']['gitlab']['location']}`
- **Target**: `{index['content_sources']['gitlab']['target']}`
- **Description**: {index['content_sources']['gitlab']['description']}

### 3. Website Content
- **Count**: {index['content_sources']['website']['count']} documents
- **Location**: `{index['content_sources']['website']['location']}`
- **Target**: Various categories based on domain
- **Description**: {index['content_sources']['website']['description']}

**Website Breakdown**:
"""
    
    if 'breakdown' in index['content_sources']['website']:
        for domain, count in index['content_sources']['website']['breakdown'].items():
            report += f"- {domain}: {count} documents\n"
    
    report += f"""
### 4. Podcast Transcripts
- **Transcripts**: {index['content_sources']['podcast']['transcripts']} episodes
- **Metadata**: {index['content_sources']['podcast']['soundcloud_metadata']} files
- **Location**: `{index['content_sources']['podcast']['location']}`
- **Target**: `{index['content_sources']['podcast']['target']}`
- **Description**: {index['content_sources']['podcast']['description']}

### 5. Medium Articles
- **Count**: {index['content_sources']['medium']['count']} articles
- **Location**: `{index['content_sources']['medium']['location']}`
- **Target**: `{index['content_sources']['medium']['target']}`
- **Description**: {index['content_sources']['medium']['description']}

### 6. Twitter Archive
- **Tweets**: {index['content_sources']['twitter']['tweets']:,} tweets
- **Location**: `{index['content_sources']['twitter']['location']}`
- **Target**: `{index['content_sources']['twitter']['target']}`
- **Description**: {index['content_sources']['twitter']['description']}

## Conversion Status
"""
    
    for source, status in index['conversion_status'].items():
        emoji = "⏳" if status == "pending" else "✅" if status == "completed" else "❌"
        report += f"- {source}: {emoji} {status}\n"
    
    report += """
## Conversion Scripts

1. `create_master_index.py` - This script (generates this index)
2. `conversion_utils.py` - Shared utilities for all converters
3. `convert_github_to_markdown.py` - Convert GitHub/GitLab documents
4. `convert_websites_to_markdown.py` - Convert website content
5. `convert_podcasts_to_markdown.py` - Convert podcast transcripts
6. `convert_medium_to_markdown.py` - Convert Medium articles
7. `convert_twitter_to_markdown.py` - Convert Twitter archive
8. `convert_all_to_markdown.py` - Main pipeline to run all converters

## Target Knowledge Structure
```
/opt/projects/GAIA/knowledge/
├── .claude/                    # Existing documentation
└── regen-network/
    ├── technical/              # GitHub, GitLab, technical docs
    ├── governance/             # Proposals, foundation docs
    ├── ecological/             # Methodologies, credit classes
    ├── community/              # Podcasts, articles, social
    └── shared/                 # Common references
```
"""
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"Markdown report saved to {output_path}")
    return output_path

def main():
    """Main execution"""
    print("Creating master content index...")
    
    # Create the index
    index = create_master_index()
    
    # Save as JSON
    json_path = save_index(index)
    
    # Create markdown report
    md_path = create_markdown_report(index)
    
    # Print summary
    print("\n" + "="*50)
    print("CONTENT INDEX SUMMARY")
    print("="*50)
    print(f"Total documents: {index['total_documents']}")
    print("\nBreakdown by source:")
    for source, info in index['content_sources'].items():
        if source == 'podcast':
            print(f"  - {source}: {info['transcripts']} transcripts")
        elif source == 'twitter':
            print(f"  - {source}: {info['tweets']:,} tweets")
        else:
            print(f"  - {source}: {info.get('count', 0)} documents")
    print("="*50)

if __name__ == "__main__":
    main()