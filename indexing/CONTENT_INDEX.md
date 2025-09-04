# Regen Network Content Index

Generated: 2025-08-20T06:00:00.000000

## Summary
**Total Documents Indexed**: 12,967

## Content Sources

### 1. GitHub Documentation
- **Count**: 66 documents
- **Location**: `indexing/storage/documents/github_*.json`
- **Target**: `knowledge/regen-network/technical/`
- **Description**: Technical documentation from GitHub repositories

### 2. GitLab Historical Documents
- **Count**: 3 documents
- **Location**: `indexing/storage/documents/gitlab_*.json`
- **Target**: `knowledge/regen-network/technical/`
- **Description**: Historical whitepapers from GitLab

### 3. Website Content
- **Count**: 64 documents
- **Location**: `indexing/storage/documents/website_*.json`
- **Target**: Various categories based on domain
- **Description**: Content from various Regen Network websites

**Website Breakdown**:
- other: 10 documents
- registry.regen.network: 20 documents
- regen.foundation: 6 documents
- guides.regen.network: 25 documents
- docs.regen.network: 3 documents

### 4. Podcast Transcripts
- **Transcripts**: 70 episodes
- **Metadata**: 50 files
- **Location**: `indexing/podcast/storage/podcast_complete/`
- **Target**: `knowledge/regen-network/community/podcasts/`
- **Description**: Planetary Regeneration Podcast transcripts

### 5. Medium Articles
- **Count**: 160 articles
- **Location**: `indexing/medium/storage/articles/`
- **Target**: `knowledge/regen-network/community/articles/`
- **Description**: Blog posts from Regen Network Medium

### 6. Twitter Archive
- **Tweets**: 11,483 tweets (fully processed)
- **Location**: `/opt/projects/GAIA/knowledge/regen-network/social/twitter/`
- **Target**: `knowledge/regen-network/community/social/`
- **Description**: Twitter/X archive fully converted to markdown

### 7. Notion Workspace
- **Count**: 1,120 items (585 pages + 535 database entries)
- **Location**: `/home/regenai/project/indexing/notion/`
- **Target**: `knowledge/regen-network/internal/`
- **Description**: Complete Notion workspace including KOI database

## Conversion Status
- github: ✅ complete (66 documents)
- gitlab: ✅ complete (3 documents)
- website: ✅ complete (64 documents)
- podcast: ✅ complete (120 files)
- medium: ✅ complete (160 articles)
- twitter: ✅ complete (11,483 tweets)
- notion: ✅ complete (1,120 items)

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
