# Medium Blog Sensor for KOI Network

This sensor monitors the Regen Network Medium blog (https://regen-network.medium.com) for new articles and updates, extracting content and metadata for the KOI knowledge pipeline.

## Features

- **RSS Feed Collection**: Primary method using Medium's RSS feed
- **Web Scraping Fallback**: Archive and page scraping when RSS is unavailable
- **Historical Article Support**: Can collect 100+ historical articles
- **Clean Text Extraction**: Converts Medium's complex HTML to clean text
- **Automatic Tagging**: Generates tags based on article content
- **KOI Integration**: Full Event Bridge support with RID generation
- **No API Key Required**: Uses public RSS and web scraping

## Quick Start

### Standalone Mode (No Dependencies)

Run the standalone sensor for immediate testing:

```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors/sensors/medium
python medium_sensor_standalone.py
```

This will:
- Auto-install required packages if missing
- Collect 5 recent articles
- Save results to `medium_articles_test.json`
- Display summary statistics

### Full KOI Integration

Run with KOI infrastructure:

```bash
# Ensure KOI coordinator is running
cd /Users/darrenzal/projects/RegenAI/koi-sensors

# Run the Medium sensor
python sensors/medium/medium_sensor.py
```

## Installation

### Required Packages

```bash
pip install aiohttp beautifulsoup4 html2text feedparser
```

Or add to requirements.txt:
```
aiohttp>=3.9.0
beautifulsoup4>=4.12.0
html2text>=2020.1.16
feedparser>=6.0.0
```

### Optional (for advanced scraping)
```bash
pip install playwright
playwright install chromium
```

## Testing

Run the comprehensive test suite:

```bash
python test_medium_sensor.py
```

Tests include:
1. Standalone sensor functionality
2. RSS feed collection
3. Article content extraction
4. KOI Event Bridge integration
5. Web scraping fallback

## Configuration

The sensor can be configured in `medium_sensor.py`:

```python
medium_sources = [
    {
        "name": "regen-network-medium",
        "url": "https://regen-network.medium.com",
        "rss_url": "https://medium.com/feed/@regen-network",
        "check_interval": 21600,  # 6 hours
        "importance": "high"
    }
]
```

### Configuration Options

- `check_interval`: How often to check for new articles (seconds)
- `max_articles_per_check`: Limit articles per check cycle
- `use_rss`: Enable RSS collection (recommended)
- `use_scraping`: Enable web scraping fallback
- `historical_years`: Years to check for historical articles
- `min_content_length`: Minimum article length to process

## Collection Strategies

### 1. RSS Feed (Primary)
- URL: `https://medium.com/feed/@regen-network`
- Returns most recent articles (typically 10-20)
- Includes metadata: title, author, date, link
- Most reliable method

### 2. Archive Scraping (Historical)
- Pattern: `https://regen-network.medium.com/archive/{year}/{month}`
- Checks years 2018-2025
- Good for collecting historical articles

### 3. Main Page Scraping (Fallback)
- URLs: `/archive`, `/latest`, main page
- Extracts article links from HTML
- Parses JavaScript for post IDs

## Output Format

### KOI Document Structure

```json
{
  "id": "medium_a1b2c3d4e5f6",
  "source": "medium:regen-network-medium",
  "source_type": "blog",
  "url": "https://medium.com/@regen-network/...",
  "title": "Article Title",
  "content": "Full article text content...",
  "metadata": {
    "author": "Author Name",
    "published_date": "2024-01-15T10:00:00Z",
    "read_time": "5 min read",
    "tags": ["governance", "ecocredits", "climate"],
    "word_count": 1234,
    "collection_method": "medium_sensor"
  },
  "collected_at": "2025-09-10T12:00:00Z",
  "rid": "orn:medium.article.a1b2c3d4e5f6"
}
```

### RID Format

Medium articles use the RID pattern:
```
orn:medium.article.{article_id}
```

Where `article_id` is either:
- The Medium article ID extracted from URL (e.g., `a1b2c3d4e5f6`)
- A hash of the URL if no ID is found

## Auto-Tagging

The sensor automatically generates tags based on content:

- **governance**: Governance, proposals, voting, DAO
- **ecocredits**: Ecocredit, carbon, biodiversity, nature-based
- **marketplace**: Marketplace, trading, registry
- **methodology**: Methodology, protocol, verification
- **development**: Technical, blockchain, Cosmos SDK
- **community**: Community, regenerative, ecosystem
- **climate**: Climate change, emissions, sustainability
- **agriculture**: Farming, soil, regenerative agriculture
- **finance**: ReFi, investment, funding, tokenomics

## Troubleshooting

### RSS Feed Not Working
- Check if feed URL is accessible: `curl https://medium.com/feed/@regen-network`
- Verify network connectivity
- Fallback to web scraping will activate automatically

### No Articles Found via Scraping
- Medium may have changed their HTML structure
- Try using Playwright for browser-based scraping
- Check if the publication URL is correct

### KOI Integration Issues
- Ensure KOI coordinator is running on port 8000
- Check that KOI protocol modules are installed
- Verify network connectivity to coordinator

### Rate Limiting
- Default delay: 1 second between requests
- Increase `request_delay` if experiencing blocks
- Consider using rotating user agents

## Performance

- **Initial Collection**: ~100 articles in 5-10 minutes
- **Regular Checks**: Every 6 hours for new articles
- **Memory Usage**: ~50MB for 100 articles
- **Network Usage**: ~1-2MB per article (HTML)

## Integration with Information Pipeline

This sensor is part of Session 6 in the Information Pipelines v0 implementation:

1. **Data Collection**: Gathers Medium blog posts
2. **KOI Processing**: Sends to Event Bridge for embedding generation
3. **Storage**: Articles stored in PostgreSQL with vectors
4. **Daily Bot**: Uses articles for daily X thread generation
5. **Weekly Digest**: Includes blog highlights in weekly summary

## Development Notes

### Why Separate from Website Sensor?

- **Specialized Scraping**: Medium has unique archive patterns and RSS feeds
- **Different Metadata**: Blog posts have authors, tags, read time
- **Update Frequency**: Blogs update less frequently than websites
- **Content Structure**: Articles have different extraction requirements

### Future Enhancements

- [ ] Add engagement metrics (claps, responses)
- [ ] Extract embedded tweets and quotes
- [ ] Support for series/collections
- [ ] Author profile extraction
- [ ] Related articles mapping
- [ ] Comment extraction (if available)

## Files

- `medium_sensor.py` - Main KOI-integrated sensor
- `medium_sensor_standalone.py` - Standalone version for testing
- `test_medium_sensor.py` - Comprehensive test suite
- `README.md` - This documentation

## Reference

Based on patterns from:
- `/server-project/indexing/medium/collectors/medium_collector.py`
- KOI sensor architecture from other sensors (Twitter, Discourse, Websites)

## Support

For issues or questions:
- Check test output: `python test_medium_sensor.py`
- Review logs in sensor output
- Verify RSS feed availability
- Ensure all dependencies are installed