# Discourse Module Integration Guide

## Overview

The Discourse module provides forum data to the main indexing pipeline through a standardized interface.

## Data Storage Structure

```
discourse/storage/
├── manifest.json                     # Data registry and metadata
├── forum_crawl_YYYYMMDD_HHMMSS.json # Crawled data files
└── indexing_summary.json            # Statistics
```

## Manifest System

The `manifest.json` file tracks:
- **Data files**: All crawled data with timestamps and metadata
- **Latest run**: Points to the most recent full crawl
- **Schema**: Documents the structure of stored data
- **Statistics**: Topic counts, categories, etc.

## Integration Points

### 1. For Embedding Generation

```python
from indexing.collectors.discourse_integration import load_discourse_documents

# Get all discourse documents
documents = load_discourse_documents()
# Returns: List of document dictionaries with id, content, metadata
```

### 2. For Knowledge Graph

```python
from indexing.discourse.discourse_loader import DiscourseDataLoader

loader = DiscourseDataLoader()
documents = loader.get_documents_for_knowledge_graph()
# Returns: Documents with entity extraction hints
```

### 3. Direct Access

```python
from indexing.discourse.discourse_loader import DiscourseDataLoader

loader = DiscourseDataLoader()

# Get latest data file
latest_file = loader.get_latest_data_file()

# Load specific file
docs = loader.load_documents(filename="forum_crawl_20250808_050246.json")

# Get statistics
stats = loader.get_statistics()
```

## Document Schema

Each document contains:
```json
{
  "id": "forum-regen-123",
  "source": "forum.regen.network",
  "source_type": "forum",
  "url": "https://forum.regen.network/t/...",
  "title": "Topic Title",
  "content": "Combined post content...",
  "metadata": {
    "forum": "regen-forum",
    "topic_id": 123,
    "category_id": 6,
    "posts_count": 5,
    "views": 100,
    "crawled_at": "2025-08-08T05:02:46"
  },
  "author": "username",
  "tags": ["governance", "proposal"]
}
```

## How It Works

1. **Crawling**: Scripts in `discourse/scripts/` fetch forum data via JSON API
2. **Storage**: Data saved to `discourse/storage/` with manifest tracking
3. **Loading**: `DiscourseDataLoader` reads manifest to find latest data
4. **Integration**: `discourse_integration.py` provides data to main pipeline
5. **Processing**: Main pipeline uses standard interface for embeddings/knowledge graph

## Updating Data

To refresh forum data:
```bash
# Run full crawl
python indexing/discourse/scripts/index_all_forums.py

# This automatically:
# 1. Fetches all topics
# 2. Saves to storage/
# 3. Updates manifest.json
# 4. Makes data available to pipeline
```

## Main Pipeline Usage

The main indexing pipeline (`run_full_index.py`) will:
1. Check for discourse data via `discourse_integration`
2. Load documents using the manifest system
3. Process alongside other data sources
4. Generate embeddings and knowledge graph

## Benefits of This Approach

- **Decoupled**: Discourse module is self-contained
- **Versioned**: Manifest tracks all data versions
- **Discoverable**: Pipeline automatically finds latest data
- **Standardized**: Consistent document schema across sources
- **Maintainable**: Clear separation of concerns