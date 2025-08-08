# Twitter/X Scraping for Regen Network

This module provides Twitter/X scraping functionality to index tweets from Regen Network accounts into the knowledge base system.

## 📋 Quick Summary

**Two approaches available:**
1. **🎯 Twitter Archive Export (RECOMMENDED)** - Ask Regen Network to export their data
2. **🔧 Web Scraping (IMPLEMENTED)** - Use cookies to scrape, but has rate limits

**Current recommendation**: Have Regen Network export their Twitter archive for complete history without rate limits.

## 🎯 RECOMMENDED: Use Twitter Archive Export

**The best approach is to have Regen Network export their Twitter archive.** This provides complete history with zero risk of rate limiting or account suspension.

### How to Get Twitter Archive

1. **Regen Network should**:
   - Go to Settings → Your account → Download an archive of your data
   - Verify identity with email/phone
   - Wait 24-48 hours for preparation
   - Download the .zip file

2. **Process the archive**:
```bash
# Process the entire archive
python indexing/twitter/scripts/process_twitter_archive.py twitter-archive.zip

# Or process extracted directory
python indexing/twitter/scripts/process_twitter_archive.py twitter-2024-08-07/

# Limit processing for testing
python indexing/twitter/scripts/process_twitter_archive.py twitter-archive.zip --limit 100
```

### Archive Advantages

- ✅ **Complete history** - Every tweet since account creation
- ✅ **No rate limits** - Process thousands of tweets instantly  
- ✅ **Zero risk** - No authentication needed, no suspension risk
- ✅ **Rich metadata** - Includes impressions, engagements, media
- ✅ **Deleted tweets** - Includes tweets no longer public

## Overview

The Twitter collector uses `twscrape` as the primary scraping library with `ntscraper` as a fallback. It supports cookie-based authentication for reliable access and implements rate limiting to avoid detection.

## Features

- 🐦 Scrape tweets from @regen_network and other configured accounts
- 🔐 Secure authentication with encrypted credential storage
- 📊 Full metadata extraction (likes, retweets, replies, media)
- 🔄 Incremental updates (only new tweets)
- 💾 Integration with main indexing pipeline
- 🚦 Rate limiting and retry logic
- 📈 Fallback scraper support

## Quick Start

### 1. Install Dependencies

```bash
# From project root
cd /home/regenai/project
source venv/bin/activate
pip install -r indexing/requirements.txt
```

### 2. Set Up Authentication (for scraping approach)

⚠️ **Note**: Authentication is only needed if not using the archive export method.

Run the interactive setup script:

```bash
python indexing/twitter/scripts/setup_twitter_auth.py
```

Choose one of these authentication methods:
- **Cookie-based** (Recommended): Export cookies from browser
- **Auth token**: Just the auth_token from cookies
- **Username/Password**: Less reliable, may trigger security
- **Environment variables**: Use .env file

#### Getting Cookies (Recommended Method)

1. Log into twitter.com in your browser
2. Open Developer Tools (F12)
3. Go to Application > Cookies > https://twitter.com
4. Find and copy these values:
   - `auth_token` (40-character string) - REQUIRED
   - `ct0` (CSRF token) - REQUIRED
5. Paste when prompted by setup script

### 3. Test the Setup

Verify everything is working:

```bash
python indexing/twitter/scripts/test_twitter_scrape.py
```

This will:
- Check authentication
- Collect a few test tweets
- Verify storage
- Test rate limiting

### 4. Run Full Collection

#### Option A: Twitter Only

```bash
# Test mode (50 tweets)
python indexing/twitter/scripts/index_twitter.py --test

# Full collection
python indexing/twitter/scripts/index_twitter.py

# Specific limit
python indexing/twitter/scripts/index_twitter.py --limit 1000

# Specific account
python indexing/twitter/scripts/index_twitter.py --username RegenFoundation
```

#### Option B: Integrated with Main Pipeline

The Twitter collector is integrated into the main indexing system:

```bash
# From project root
python indexing/scripts/run_collection_only.py
```

## Configuration

### Main Configuration

Edit `indexing/twitter/config/twitter_sources.yaml`:

```yaml
twitter:
  accounts:
    - username: regen_network
      include_replies: true
      include_retweets: true
      date_range:
        start: 2020-01-01
        end: null  # Current date
      max_tweets: 5000
    
  rate_limits:
    requests_per_hour: 300
    retry_attempts: 3
    cooldown_seconds: 60
    
  cache:
    enabled: true
    ttl_hours: 6
    incremental: true
```

### Environment Variables

Create `.env` file in project root:

```bash
# Twitter Authentication (optional if using setup script)
TWITTER_AUTH_TOKEN=your_40_char_auth_token
TWITTER_COOKIES='auth_token=xxx; ct0=yyy'
TWITTER_USERNAME=your_username
```

## Available Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `process_twitter_archive.py` | **Process Twitter archive export** | `python script.py archive.zip` |
| `setup_twitter_auth.py` | Set up authentication for scraping | Interactive setup |
| `test_twitter_scrape.py` | Test scraping functionality | Verify setup |
| `index_twitter.py` | Full scraping pipeline | `--limit 100 --username regen_network` |
| `quick_auth_setup.py` | Quick auth with hardcoded cookies | For testing |
| `test_twscrape.py` | Direct twscrape testing | Debug authentication |

## Directory Structure

```
indexing/twitter/
├── README.md                      # This file
├── collectors/
│   └── twitter_collector.py       # Main TwitterCollector class
├── scripts/
│   ├── process_twitter_archive.py # Archive processor (RECOMMENDED)
│   ├── setup_twitter_auth.py      # Interactive auth setup
│   ├── test_twitter_scrape.py     # Test functionality
│   ├── index_twitter.py           # Full indexing script
│   └── [other test scripts]       # Various testing utilities
├── storage/
│   ├── tweets/                    # Raw tweet JSON files
│   ├── media/                     # Downloaded images (optional)
│   └── cache/                     # Auth and rate limit cache
├── config/
│   └── twitter_sources.yaml       # Configuration
└── utils/
    ├── auth_manager.py            # Credential management
    └── rate_limiter.py            # Rate limiting (future)
```

## Data Flow

1. **Collection**: TwitterCollector fetches tweets using twscrape
2. **Storage**: Raw tweets saved to `storage/tweets/`
3. **Processing**: Documents converted to standard format
4. **Integration**: Saved to main `storage/documents/` as `twitter_*.json`
5. **Chunking**: DocumentProcessor creates searchable chunks
6. **Embeddings**: Embedder generates vector embeddings
7. **Index**: Added to ChromaDB for similarity search

## Output Format

Tweets are converted to the standard Document format:

```json
{
  "id": "twitter_1234567890",
  "source": "twitter:regen_network",
  "source_type": "twitter",
  "url": "https://twitter.com/regen_network/status/1234567890",
  "title": "Tweet by @regen_network - ...",
  "content": "Full tweet text here...",
  "metadata": {
    "tweet_id": "1234567890",
    "username": "regen_network",
    "likes": 42,
    "retweets": 10,
    "replies": 5,
    "hashtags": ["ReFi", "carbon"],
    "mentions": ["@user1"],
    "urls": ["https://..."],
    "media": ["https://pbs.twimg.com/..."]
  },
  "collected_at": "2024-01-20T10:30:00",
  "last_modified": "2024-01-19T15:45:00",
  "author": "@regen_network",
  "tags": ["twitter", "social_media", "regen_network"]
}
```

## Monitoring

Check logs for collection progress:

```bash
# View latest log
tail -f indexing/logs/twitter_index_*.log

# Check stored tweets
ls -la indexing/twitter/storage/tweets/

# Count indexed documents
ls indexing/storage/documents/twitter_*.json | wc -l
```

## Current Status (Updated: Aug 8, 2024)

### ✅ What's Working
- Twitter archive processor fully implemented and tested
- Authentication system working with cookies
- Successfully connected to Twitter API
- Retrieved tweets from @regen_network (20,441 followers)

### ⚠️ Known Limitations
- **Rate Limiting**: Twitter aggressively rate limits (15-minute cooldowns)
- **Nitter instances**: All public Nitter instances are blocked by Twitter
- **API Changes**: Twitter frequently changes their internal API

### 📊 Results So Far
- Successfully authenticated with @ReFiChat account
- Connected to @regen_network profile
- Retrieved 25+ recent tweets before rate limit
- Rate limited until specific time (shown in logs)

## Troubleshooting

### Authentication Issues

1. **"No authentication configured"**
   - Run `setup_twitter_auth.py` first
   - Check `.env` file exists with credentials

2. **"Invalid auth_token"**
   - Auth token should be exactly 40 characters
   - Make sure you're copying the VALUE, not the name
   - Token may have expired - get a fresh one

3. **"Rate limited"**
   - Wait 15-60 minutes before retrying
   - Consider using multiple accounts
   - Reduce requests_per_hour in config

### Collection Issues

1. **No tweets collected**
   - Verify account exists and has tweets
   - Check if account is private
   - Try with --test flag first
   - Review logs for specific errors

2. **Partial collection**
   - Rate limits may have been hit
   - Check cooldown_seconds in config
   - Use --incremental for updates

3. **Import errors**
   - Install dependencies: `pip install twscrape ntscraper`
   - Activate virtual environment first

### Storage Issues

1. **Permission denied**
   - Check directory permissions
   - Run from project root
   - Use proper Python path

2. **Disk space**
   - Check available space
   - Clean old cache files
   - Disable media download if needed

## Best Practices

1. **Authentication**
   - Use cookie-based auth for reliability
   - Rotate accounts to avoid rate limits
   - Never commit credentials to git

2. **Collection**
   - Start with test mode (--test)
   - Use incremental updates for efficiency
   - Monitor rate limits in logs

3. **Storage**
   - Regular backups of tweet data
   - Clean cache periodically
   - Archive old tweets separately

## Future Enhancements

- [ ] Real-time streaming support
- [ ] Multi-account rotation
- [ ] Media download and indexing
- [ ] Thread reconstruction
- [ ] Sentiment analysis
- [ ] Export to various formats
- [ ] Twitter Lists support
- [ ] Advanced search queries

## Security Notes

- Credentials are encrypted using Fernet symmetric encryption
- Auth files have restricted permissions (0600)
- Never share `.auth_key` or `twitter_auth.json`
- Use dedicated scraping accounts if possible
- Respect Twitter's Terms of Service

## Support

For issues or questions:
1. Check this README first
2. Review logs in `indexing/logs/`
3. Run test script for diagnostics
4. Check GitHub issues for similar problems

## License

Part of the Regen Network Indexing System - see main project license.