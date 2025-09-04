# Medium Blog Indexing Module

This module handles collection and processing of articles from Regen Network's Medium blog.

## Overview

Successfully collected **160 unique articles** from Regen Network's Medium publication:
- 130 articles from user's manual count (100% coverage)
- 30 additional archived/hidden articles discovered via automation
- Articles span from 2018-2024

## Structure

```
medium/
├── collectors/           # Medium-specific collectors
│   └── medium_collector.py
├── scripts/             # Collection and processing scripts
│   ├── collect_medium_*.py
│   ├── check_medium_*.py
│   └── consolidate_medium_articles.py
├── storage/
│   ├── articles/        # 160 collected articles (JSON format)
│   └── metadata/        # URL lists and collection metadata
└── docs/               # Documentation

```

## Key Features

- **Dual URL Support**: Handles both old (`medium.com/regen-network`) and new (`regen-network.medium.com`) URL formats
- **Deduplication**: Articles with multiple URLs are consolidated with alternate URLs in metadata
- **Cloudflare Bypass**: Successfully navigates Medium's bot protection
- **Complete Coverage**: All manually identified articles plus additional archived content

## Article Topics

- **Urban Forestry Series** (Parts 1-5)
- **Planetary Regeneration Podcast** (19 episodes)
- **Biodiversity Credits** and market development
- **Carbon Markets** and regenerative finance
- **Technology Updates** (Regen Ledger, Cosmos SDK)
- **Partnership Announcements** (Solana, Mercedes F1, ecoToken)
- **Community Governance** and token economics
- **Development Updates** and team announcements
- **Telegram AMAs** (3 sessions)
- **Validator Resources** and staking guides

## Collection Statistics

- Total files: 160
- Date range: 2018-2024
- URL formats: 2 (old and new Medium URLs)
- Average article size: ~5-10 KB
- Total storage: ~1.2 MB

## Usage

### Collect New Articles
```python
from indexing.medium.collectors import MediumCollector

collector = MediumCollector(config)
articles = await collector.collect()
```

### Access Stored Articles
```python
import json
from pathlib import Path

articles_dir = Path("indexing/medium/storage/articles")
for article_path in articles_dir.glob("*.json"):
    with open(article_path) as f:
        article = json.load(f)
        print(f"Title: {article['title']}")
        print(f"URL: {article['url']}")
        print(f"Alternate URLs: {article.get('alternate_urls', [])}")
```

## Notes

- Medium changed their URL structure over time, causing some articles to have multiple valid URLs
- All articles are deduplicated by content, with alternate URLs stored in metadata
- The blog contains more articles than are visible through normal browsing (pagination limits)
- Cloudflare protection requires special handling for automated collection