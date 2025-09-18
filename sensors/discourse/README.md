# Discourse Forum Sensor

## Overview
The Discourse Forum Sensor collects discussions, proposals, and community content from Regen Network's Discourse forums. It monitors both the main governance forum and the commons forum for important discussions.

## Features
- 🌐 Collects from multiple Discourse forums
- 📊 Extracts topics with full post content
- 🏷️ Automatic tagging (governance, ecocredits, marketplace, etc.)
- 🔄 KOI Event Bridge integration
- 📝 No API key required (uses public endpoints)
- ✅ Fixed: Sensor no longer hangs on startup (resolved KOI node polling loop issue)

## Forums Monitored
1. **forum.regen.network** - Main governance and discussion forum
2. **regencommons.discourse.group** - Commons community forum

## Installation

```bash
# Install required packages
pip install httpx

# Or use the requirements file
pip install -r requirements.txt
```

## Usage

### Basic Usage
```python
import asyncio
from discourse_sensor import DiscourseSensor

async def main():
    async with DiscourseSensor() as sensor:
        await sensor.run(limit_per_forum=20)

asyncio.run(main())
```

### Run Standalone
```bash
python discourse_sensor.py
```

### Run Tests
```bash
python test_discourse_sensor.py
```

## Data Collection

### Topics Collected
- Governance proposals and discussions
- Token economics discussions
- Ecocredit marketplace topics
- Validator discussions
- Community announcements
- Technical discussions

### Document Structure
Each forum post is stored as an individual KOI document with:
- **RID**: Unique identifier (deterministic: `forum:topic:post:author:created`)
- **Title**: Topic title (or "Re: {title}" for replies)
- **Content**: Individual post content
- **Author**: Post author username
- **Tags**: Auto-extracted based on content
- **Metadata**: Post number, published date, likes, reply info, etc.

### Example Output
```json
{
  "rid": "a1b2c3d4e5f6g7h8",
  "source": "discourse:forum.regen.network",
  "source_type": "forum",
  "url": "https://forum.regen.network/t/example-topic/123",
  "title": "Governance Proposal: Example",
  "content": "# Governance Proposal: Example\n\n## Post by user1...",
  "author": "user1",
  "tags": ["governance", "proposal"],
  "metadata": {
    "forum": "forum.regen.network",
    "topic_id": 123,
    "posts_count": 15,
    "views": 245,
    "like_count": 12,
    "reply_count": 14
  }
}
```

## Features

### Individual Post Storage (Enhanced)
- **Post-level documents**: Each forum post becomes a separate KOI document
- **Pagination support**: Fetches all posts in a topic using Discourse API pagination
- **Granular tracking**: Individual post updates can be tracked and versioned
- **Enhanced metadata**: Post number, author, likes, reply relationships preserved

### Deduplication
- **In-memory cache**: Tracks processed posts within a session (clears on restart)
- **Database-level**: Uses RID-based `ON CONFLICT` to prevent duplicates in database
- **RID generation**: Deterministic based on `forum:topic:post:author:created`

### Automatic Tagging
The sensor automatically tags content based on keywords:
- **governance**: Proposals, voting, DAO discussions
- **ecocredit**: Carbon credits, batches, retirement
- **marketplace**: Trading, buying, selling
- **validator**: Staking, delegation, commission
- **tokenomics**: Token discussions, REGEN token
- **community**: Community events, announcements

### Rate Limiting
- No API key required
- Uses public endpoints
- Respects rate limits automatically
- Implements pagination for large results

### Content Processing
- Converts HTML to plain text
- Preserves post structure
- **Stores each post as individual document** (NEW: post-level granularity)
- Implements pagination to fetch all posts in a topic
- Generates unique RID for each post: `forum:topic:post:author:created`

## Output

### File Output
Documents are saved to `output/discourse_YYYYMMDD_HHMMSS.json`

### KOI Integration
Documents are automatically sent to KOI Event Bridge with:
- Event type: `discourse_topic`
- Full document data
- Proper RID generation

## Configuration

### Forum Configuration
Forums are configured in the sensor initialization:
```python
self.forums = [
    {
        'name': 'forum.regen.network',
        'url': 'https://forum.regen.network',
        'categories': ['all']  # or specific category slugs
    }
]
```

### Collection Limits
- Default: 20 topics per forum
- Configurable via `limit_per_forum` parameter
- Processes first 3 pages per category
- Limits to 30 posts per topic

## Testing

### Test Categories
```bash
# Test fetching forum categories
python -c "import asyncio; from test_discourse_sensor import test_categories; asyncio.run(test_categories())"
```

### Test Topics
```bash
# Test fetching topics
python -c "import asyncio; from test_discourse_sensor import test_topics; asyncio.run(test_topics())"
```

### Full Test Suite
```bash
python test_discourse_sensor.py
```

## Error Handling
- Graceful handling of network errors
- Continues collection if one forum fails
- Logs all errors with context
- Avoids duplicate processing

## Performance
- Async/await for concurrent requests
- Efficient pagination for complete topic coverage
- Caches processed posts for deduplication
- Enhanced throughput: Individual post processing with full topic pagination
- Typical collection: ~50 topics with all posts in 2-3 minutes

## Limitations
- No authentication (public data only)
- Rate limited by Discourse defaults
- Maximum 30 posts per topic
- No real-time updates (polling based)

## Future Enhancements
- [ ] Add webhook support for real-time updates
- [ ] Implement incremental updates
- [ ] Add user activity tracking
- [ ] Support private categories with API key
- [ ] Add sentiment analysis for discussions
- [ ] Track voting patterns on proposals

## Integration with KOI
The sensor integrates with the KOI system by:
1. Generating unique RIDs for each topic
2. Sending events to KOI Event Bridge
3. Structuring data for BGE embeddings
4. Preserving metadata for knowledge graph

## Troubleshooting

### No Topics Found
- Check forum URLs are accessible
- Verify no firewall blocking
- Try with browser first

### Rate Limiting
- Reduce `limit_per_forum`
- Add delays between requests
- Use API key if available

### Content Extraction Issues
- Check HTML structure hasn't changed
- Verify post format compatibility
- Review extraction regex patterns