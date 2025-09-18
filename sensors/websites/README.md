# KOI Website Sensor

Website monitoring sensor for the KOI (Knowledge Organization Infrastructure) protocol. Monitors Regen Network websites for content changes and emits KOI-compliant events.

## Features

- **KOI Protocol Compliance**: Full compatibility with KOI-net specification
- **Content Change Detection**: Hash-based monitoring for efficient updates
- **Publication Date Extraction**: Site-specific patterns for extracting dates with confidence scoring
- **Comprehensive Crawling**: Automatic link discovery with configurable max_pages limit (no depth restrictions)
- **Video Transcription**: Automatic detection and transcription of embedded videos using Whisper AI
- **Modern Content Extraction**: Enhanced support for div-based sites and JavaScript-rendered content
- **Proven Scraping Methods**: Based on successful server patterns (86.4% success rate)
- **Configurable Monitoring**: YAML-based configuration for flexible website monitoring
- **Docker Ready**: Complete containerization with health checks and logging

## Monitored Websites

Current configuration includes:

- **regen.network** - Main Regen Network website
- **docs.regen.network** - Technical documentation
- **guides.regen.network** - User guides and tutorials
- **registry.regen.network** - Credit classes, methodologies, projects
- **regen.foundation** - Foundation updates and publications
- **forum.regen.network** - Community governance discussions
- **regentokenomics.org** - Tokenomics research and documentation
- **researchretreat.org** - Academic research papers
- **desci.com** - Decentralized science platform

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Configure websites in config.yaml
# Run the sensor
python run_website_sensor.py
```

### Docker Deployment

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f website-sensor

# Stop
docker-compose down
```

## Configuration

### Website Selection & RID Generation

Each monitored website gets unique Resource Identifiers (RIDs):

```yaml
websites:
  - name: docs-regen-network          # Config identifier
    url: https://docs.regen.network   # Base URL
    check_interval: 3600              # Check every hour
    max_pages: 1000                  # Maximum pages to crawl (no depth limit)
    priority: high                    # Processing priority
```

**RID Generation Process:**
```
URL: https://docs.regen.network/getting-started
↓
Domain: docs.regen.network
Path Hash: sha256("https://docs.regen.network/getting-started")[:16]
↓ 
RID: orn:web.page:docs.regen.network/11d55c36d6225d12
```

### Current Website Status

Based on server indexing at `202.61.196.119:/home/regenai/project`:

| Website | Current Docs | Status | Priority |
|---------|--------------|--------|----------|
| docs.regen.network | 3 | 🔴 Needs deep crawl | High |
| guides.regen.network | 25 | ✅ Complete | Medium |
| registry.regen.network | 20 | 🔴 Needs expansion | High |
| regen.foundation | 7 | ⚠️ Partial | Medium |

**Registry Priority**: The registry contains ALL credit classes, methodologies, and projects - critical for agent accuracy. Currently only 20 docs indexed vs. hundreds of credit classes available.

## Architecture Integration

This website sensor is part of the KOI sensor network:

```
Websites → Website Sensor → KOI Coordinator → Processor → PostgreSQL
```

- **Emits**: KOI Events (NEW/UPDATE/FORGET)
- **RID Format**: `orn:web.page:domain/url_hash`
- **Bundle Format**: KOI-compliant with manifest and content
- **Coordinator**: Connects to KOI Coordinator at port 8005
- **Date Extraction**: Site-specific patterns for accurate publication dates

### Publication Date Extraction (Enhanced)

The sensor uses site-specific patterns to extract publication dates with improved accuracy:

| Website | Pattern | Confidence | Status |
|---------|---------|------------|--------|
| regentokenomics.org | "Month DD, YYYY" in content | 0.8 | ✅ Enhanced |
| regen.foundation/publications | "Published Month DD, YYYY" | 0.9 | ✅ Working |
| forum.regen.network | Discourse date elements | 0.9 | ✅ Working |
| docs/guides.regen.network | Relative dates | 0.3 | Working |
| Generic fallback | ISO dates, meta tags | 0.6-0.8 | Working |

**Recent Improvements**:
- Enhanced regentokenomics.org date extraction with multiple pattern matching
- Improved content parsing for date detection in article body text
- Added fallback patterns for various date formats found on research pages

## Status

✅ **Phase 1 Complete** - Sensor implementation with KOI protocol compliance
🔄 **Phase 2 Pending** - Coordinator-Processor bridge integration
⏳ **Phase 3 Pending** - Apache Jena triplestore integration

## Monitoring

The sensor provides:

- Health checks via HTTP endpoint
- Structured logging with configurable levels
- Content change detection metrics
- KOI event emission tracking

## Development Notes

Built using proven patterns from the production server with 86.4% success rate processing 12,967+ documents. Maintains full compatibility with existing data collection methods while adding KOI protocol compliance.