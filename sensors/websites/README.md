# KOI Website Sensor

Website monitoring sensor for the KOI (Knowledge Organization Infrastructure) protocol. Monitors Regen Network websites for content changes and emits KOI-compliant events.

## Features

- **KOI Protocol Compliance**: Full compatibility with KOI-net specification
- **Content Change Detection**: Hash-based monitoring for efficient updates
- **Proven Scraping Methods**: Based on successful server patterns (86.4% success rate)
- **Configurable Monitoring**: YAML-based configuration for flexible website monitoring
- **Docker Ready**: Complete containerization with health checks and logging

## Monitored Websites

Based on server configuration at `202.61.196.119:/home/regenai/project`:

- **docs.regen.network** - Technical documentation
- **guides.regen.network** - User guides and tutorials  
- **registry.regen.network** - Credit classes, methodologies, projects
- **regen.foundation** - Foundation updates and publications

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
    max_depth: 3                      # Crawl depth
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
Websites → Website Sensor → KOI Coordinator → Processor → Apache Jena
```

- **Emits**: KOI Events (NEW/UPDATE/FORGET)
- **RID Format**: `orn:web.page:domain/url_hash`
- **Bundle Format**: KOI-compliant with manifest and content
- **Coordinator**: Connects to KOI Coordinator at port 8000

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