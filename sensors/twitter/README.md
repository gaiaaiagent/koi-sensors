# Twitter Sensor for KOI Network

A browser-based Twitter scraper that collects tweets, replies, and mentions without requiring API keys or authentication.

## Features

- ✅ **No Authentication Required** - Uses browser automation to scrape public Twitter data
- ✅ **Multiple Collection Modes**:
  - User timeline tweets
  - User replies
  - Mentions of users
- ✅ **Built-in Caching** - Reduces requests and improves performance
- ✅ **Rate Limiting** - Automatic delays to avoid detection
- ✅ **Stealth Mode** - Uses playwright-stealth to avoid bot detection
- ✅ **Fallback Support** - Multiple scraping strategies

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Operating System: Linux, macOS, or Windows
- ~500MB disk space for Chromium browser

## Installation

### Option 1: Automated Setup (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/RegenAI.git
cd RegenAI/koi-sensors/sensors/twitter

# Run the setup script
chmod +x setup.sh
./setup.sh
```

The setup script will:
- Check Python version
- Create a virtual environment
- Install all Python dependencies
- Install Playwright browsers
- Create necessary directories
- Generate a default .env configuration

### Option 2: Manual Setup

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
playwright install-deps  # Install system dependencies (may require sudo)

# Create directories
mkdir -p cache output logs
```

### Troubleshooting Installation

If you encounter issues with Playwright:

```bash
# On Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libgtk-3-0 libasound2

# On macOS
brew install --cask chromium

# Alternative: Use Firefox instead
playwright install firefox
```

## Configuration

Create a `.env` file in the twitter sensor directory:

```bash
# Twitter Sensor Configuration
HEADLESS=true              # Run browser in headless mode (no UI)
CACHE_DIR=./cache          # Directory for caching scraped data
OUTPUT_DIR=./output        # Directory for output files
LOG_LEVEL=INFO            # Logging level (DEBUG, INFO, WARNING, ERROR)
MAX_TWEETS=100            # Maximum tweets to collect per request
RATE_LIMIT_DELAY=3        # Seconds to wait between requests
```

## Usage

### Command Line Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Run the scraper for @regen_network
python twitter_scraper_playwright.py
```

### Python API Usage

```python
from twitter_scraper_playwright import TwitterPlaywrightScraper
import asyncio

async def scrape_regen_network():
    # Initialize scraper
    scraper = TwitterPlaywrightScraper(headless=True)
    
    try:
        # Initialize browser
        await scraper.initialize()
        
        # Scrape user timeline (tweets only, no replies)
        tweets = await scraper.scrape_user_timeline(
            username="regen_network",
            max_tweets=50,
            include_replies=False
        )
        
        # Scrape user replies
        replies = await scraper.scrape_user_replies(
            username="regen_network",
            max_replies=30
        )
        
        # Search for mentions
        mentions = await scraper.search_mentions(
            username="regen_network",
            max_tweets=20
        )
        
        return {
            'tweets': tweets,
            'replies': replies,
            'mentions': mentions
        }
        
    finally:
        await scraper.close()

# Run the scraper
results = asyncio.run(scrape_regen_network())
print(f"Collected {len(results['tweets'])} tweets")
```

### Integration with KOI Sensor Network

```python
from sensors.twitter.twitter_scraper_playwright import TwitterPlaywrightScraper
from shared.handlers.base_sensor import BaseSensor

class TwitterKOISensor(BaseSensor):
    def __init__(self, config):
        super().__init__(config)
        self.scraper = TwitterPlaywrightScraper()
    
    async def collect_data(self):
        await self.scraper.initialize()
        
        # Collect tweets for configured accounts
        for account in self.config.accounts:
            tweets = await self.scraper.scrape_user_timeline(
                username=account['username'],
                max_tweets=account.get('max_tweets', 100)
            )
            
            # Process tweets through KOI pipeline
            for tweet in tweets:
                self.emit_koi_event(tweet)
```

## Output Format

The scraper returns tweets in the following format:

```json
{
  "id": "1234567890",
  "text": "Tweet content here...",
  "author_name": "Regen Network",
  "author_username": "regen_network",
  "created_at": "2024-01-15T12:00:00Z",
  "url": "https://twitter.com/regen_network/status/1234567890",
  "metrics": {
    "likes": 42,
    "retweets": 10,
    "replies": 5
  },
  "is_reply": false,
  "source": "user_timeline"
}
```

## Performance Considerations

- **Rate Limiting**: The scraper automatically delays between requests to avoid detection
- **Caching**: Results are cached for 1 hour by default to reduce repeated requests
- **Batch Processing**: Process tweets in batches to optimize memory usage
- **Headless Mode**: Run in headless mode for better performance in production

## Limitations

- Can only access public tweets (no private accounts)
- Twitter may change their HTML structure, requiring updates
- Rate limits apply (recommended: max 100 tweets per minute)
- Some advanced features (like tweet threads) may require additional parsing

## Alternative Scrapers

If Playwright doesn't work in your environment, you can use alternative scrapers:

### ntscraper (No Authentication)
```python
from ntscraper import Nitter

scraper = Nitter()
tweets = scraper.get_tweets("regen_network", mode='user', number=50)
```

### snscrape
```python
import snscrape.modules.twitter as sntwitter

tweets = []
for i, tweet in enumerate(sntwitter.TwitterUserScraper('regen_network').get_items()):
    if i >= 50:
        break
    tweets.append(tweet)
```

## Development

### Running Tests

```bash
# Run unit tests
pytest tests/

# Run with coverage
pytest --cov=twitter_scraper_playwright tests/
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## Security Considerations

- Never commit credentials or cookies to version control
- Use environment variables for sensitive configuration
- Respect Twitter's robots.txt and terms of service
- Implement appropriate rate limiting
- Don't use for malicious purposes

## License

This project is part of the RegenAI KOI Sensor Network.

## Support

For issues or questions:
- Open an issue on GitHub
- Check the troubleshooting section
- Review the logs in `./logs/` directory