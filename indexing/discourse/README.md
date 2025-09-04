# Discourse Forum Indexing Module

This module handles crawling and indexing of Discourse forums, specifically forum.regen.network and forum.regencommons.com.

## Overview

The Discourse module uses the public JSON API endpoints to crawl forum content without requiring authentication. It can fetch topics, posts, categories, and metadata.

## Structure

```
discourse/
├── collectors/
│   └── discourse_collector.py    # Main Discourse collector class
├── scripts/
│   ├── crawl_forum_json.py      # JSON API crawler (no auth required)
│   ├── collect_forum_full.py    # Full forum collection script
│   └── test_forum_crawler.py    # Testing script
├── storage/                     # Crawled forum data storage
└── docs/                        # Documentation

```

## Usage

### Quick Test (20 topics)
```bash
cd /home/regenai/project
source venv/bin/activate
python indexing/discourse/scripts/crawl_forum_json.py
```

### Full Collection
```bash
python indexing/discourse/scripts/collect_forum_full.py
# Choose: 20, 50, 100, or 'all' topics
```

### Integrated Collection
```bash
# Use main indexing pipeline
python indexing/scripts/run_collection.py
```

## Key Features

- **No Authentication Required**: Uses public JSON API endpoints
- **Comprehensive Coverage**: Fetches all public topics and posts
- **Smart Caching**: Avoids re-fetching already indexed content
- **Category Support**: Can target specific categories (governance, tokenomics, etc.)
- **Rate Limiting**: Includes delays to respect server limits

## Forums Indexed

### forum.regen.network ✅
- Main community forum
- Categories: Governance, $REGEN Coin, Registry, Foundation, Validators
- **77 topics indexed** (all available)
- 428 posts, 832 views total
- 450KB of content

### regencommons.discourse.group ✅
- Commons community forum (was incorrectly listed as forum.regencommons.com)
- Focused on community initiatives and governance
- **6 topics indexed** (all available)
- 15 posts, 665 views total
- 33KB of content

### Combined Statistics
- **83 total topics** across both forums
- **443 total posts**
- **483KB total content**
- All data stored with manifest tracking

## Data Format

Collected documents include:
- **Title**: Topic title
- **Content**: Combined post content (up to 20 posts per topic)
- **Metadata**: Views, post count, category, timestamps
- **Author**: Original poster username
- **Tags**: Extracted from topic and content

## Important Topics

The crawler prioritizes:
- Governance proposals
- Tokenomics discussions ($REGEN)
- Registry updates
- Technical proposals
- Community calls

## API Endpoints Used

- `/categories.json` - List all categories
- `/latest.json` - Latest topics
- `/c/{category}.json` - Topics in category
- `/t/{topic_id}.json` - Full topic with posts

## Storage

Data is saved to `discourse/storage/` as JSON files with timestamp:
- `forum_crawl_YYYYMMDD_HHMMSS.json`

## Integration

The Discourse collector integrates with the main indexing pipeline:
1. Collection phase - Fetches and caches forum content
2. Processing phase - Generates embeddings
3. Knowledge graph - Extracts entities and relationships