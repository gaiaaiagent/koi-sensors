# KOI Sensor Network

Real-time knowledge monitoring infrastructure for the Regen Network AI Agent System. This system provides continuous, event-driven data collection using the KOI (Knowledge Organization Infrastructure) protocol, complementing the existing batch-processing system with live monitoring capabilities.

## 📊 Current Status

**PRODUCTION READY** ✅ - Complete KOI Pipeline with Clean Text Extraction

**Critical Text Extraction Fix Deployed (Sept 14, 2025)**:
- ✅ **Text Corruption Fixed**: Replaced html2text with BeautifulSoup - 0% word-breaking
- ✅ **Database Cleaned**: 2,569 corrupted records removed, 481+ clean records re-ingested
- ✅ **Daily Curator Working**: Can now generate coherent daily threads and weekly digests
- ✅ **All Sensors Updated**: Producing clean, deduplicated text content

**Full Pipeline Integration Complete**: Real-time clean content flows from sensors to agents
- ✅ **KOI Event Bridge Integration**: Coordinator forwards events to processor (port 8100)
- ✅ **BGE Embedding Generation**: 1024-dimensional vectors for semantic search
- ✅ **PostgreSQL Storage**: Clean data in agent database using pgvector
- ✅ **Agent RAG Access**: Content immediately available for queries (<3-5 seconds)
- ✅ **CAT Receipts**: Full provenance tracking through transformation pipeline
- ✅ **Production Tested**: End-to-end pipeline verified with clean content

**Active Sensors in Production** (as of September 28, 2025):
- ✅ **Website Sensor**: Continuous monitoring with configurable polling intervals
- ✅ **GitHub Sensor**: Repository monitoring with heartbeat support
- ✅ **GitHub Activity Sensor**: Comprehensive activity tracking (commits, issues, PRs) for daily/weekly curation
- ✅ **GitLab Sensor**: Documentation monitoring with heartbeat support
- ✅ **Medium Sensor**: RSS feed monitoring with heartbeat support
- ✅ **Discourse Sensor**: Forum monitoring with heartbeat support
- ✅ **Telegram Sensor**: Real-time channel monitoring with heartbeat support (see [setup guide](docs/TELEGRAM_SENSOR_SETUP.md))
- ✅ **Twitter Sensor v2**: API-based monitoring with heartbeat support (requires TWITTER_BEARER_TOKEN)
- ✅ **Discord Sensor**: Real-time message monitoring with heartbeat support (bot token required)
- ✅ **Podcast Sensor**: RSS feed monitoring with heartbeat support
- ✅ **Notion Sensor**: Database monitoring with heartbeat support
- ✅ **Ledger Sensor**: Blockchain monitoring with heartbeat support
- ✅ **KOI Coordinator**: Event routing with Smart Hybrid health monitoring at http://localhost:8005
- ✅ **Dashboard**: Live monitoring with real-time status updates at https://regen.gaiaai.xyz/koi

## 🔄 Event Bridge v2 Integration

**NEW**: The KOI sensor network now integrates with Event Bridge v2, providing:
- **RID-based Deduplication**: Automatically prevents duplicate content ingestion using Resource Identifiers
- **Version Control**: UPDATE events create new versions with complete audit trail
- **Isolated Tables**: Clean separation between sensor data and other content sources
- **Production Tested**: Deduplication verified working on live Regen Network infrastructure
- **Publication Date Tracking**: All sensors now extract and pass publication dates for content curation

### 📅 Publication Date Intelligence (Sessions 7-8 Complete)
All sensors have been enhanced to extract publication dates for digest generation:
- **Discourse**: API provides exact timestamps (100% coverage, 95% confidence)
- **Medium**: Fallback date extraction from content (97.9% coverage, 90% confidence)
- **GitHub/GitLab**: Git commit dates with author and message context (95% confidence)
- **Websites**: Site-specific patterns for each domain (variable coverage, 30-90% confidence)
- **Twitter/X**: Uses `created_at` timestamp (95% confidence)
- **Podcasts**: Uses RSS pubDate fields (95% confidence)
- **Bundle System**: Fixed to properly pass publication metadata through pipeline
- **Overall Coverage**: 386+ memories with dates (20.9% of total, growing)
- **Notion**: Uses API `created_time` (85% confidence)
- **Ledger**: Blockchain timestamps are immutable (100% confidence)

This enables the Daily Content Curator to select genuinely recent content for social media posts.

See [koi-processor v2.0.0](https://github.com/gaiaaiagent/koi-processor) for implementation details.

## 📚 Documentation

All documentation has been organized for better navigation:
- **[Documentation Overview](docs/)** - Complete documentation guide
- **[Quick Start Guide](QUICKSTART.md)** - Get started quickly
- **[Development Docs](docs/development/)** - Development guides and next steps
- **[Status & Changelogs](docs/status/)** - Current status and recent changes
- **[Architecture Docs](docs/architecture/)** - System design and implementation details

## 🏗️ Architecture Integration

This sensor network is **Phase 1** of the complete 3-repository KOI system, fully aligned with [KOI_COMPLETE_RESEARCH.md](../koi-research/docs/KOI_COMPLETE_RESEARCH.md):

```
📡 koi-sensors (THIS REPO) ──KOI Events──► 🔄 koi-processor ──RDF/SPARQL──► 🤖 GAIA
   │                                        │                                │
   │ • Sensor Network (Partial Nodes)       │ • Processing Pipeline         │ • ElizaOS Agents
   │ • KOI Coordinator (Full Node)          │ • Apache Jena Integration     │ • Agent Coordination
   │ • Event Emission (NEW/UPDATE/FORGET)   │ • Entity Extraction           │ • Knowledge Queries
   └─ Real-time Monitoring                  └─ Unified Ontology Processing  └─ <2s Response Times
```

## 🏥 Health Monitoring System

**Smart Hybrid Architecture** (Implemented September 15, 2025):
- **Periodic Heartbeats**: All sensors send heartbeats every 30 minutes
- **On-Demand Ping**: Coordinator can ping specific sensors or all sensors
- **Smart Refresh**: Dashboard only pings sensors that haven't reported in >10 minutes
- **Real-Time Status**: Active (< 5 min), Idle (5-30 min), or Offline (> 30 min)
- **Automatic Registration**: Sensors register on startup via heartbeat event

## 🌟 Features

### **KOI Protocol Compliance**
- **Resource Identifiers (RIDs)**: Unique identifiers using ORN format (`orn:web.page:domain/hash`)
- **Bundle System**: Manifest-based content packaging with SHA-256 integrity
- **Event System**: NEW/UPDATE/FORGET events for real-time knowledge updates
- **Full/Partial Nodes**: Complete KOI-net architecture implementation
- **Continuous Polling**: All sensors follow BlockScience's continuous monitoring pattern

### **Real-Time Monitoring**
- **Continuous Website Monitoring**: Hash-based change detection
- **Event-Driven Updates**: Immediate notification of content changes
- **Multi-Platform Support**: Website, Twitter, Discord, Notion sensors
- **Scalable Architecture**: Distributed sensor nodes with coordinator

### **Integration Ready**
- **Server Compatibility**: Document format matches existing 86.4% success system
- **Proven Collection Methods**: Wraps existing Twitter, Discourse, Notion collectors
- **Apache Jena Bridge**: Ready for semantic web integration  
- **Docker Deployment**: Production-ready containerization

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose (optional)
- 2GB+ RAM for sensor operation
- Playwright (for Twitter sensor)

### Installation

#### **Unified Setup** (Recommended)
```bash
git clone https://github.com/gaiaaiagent/koi-sensors.git
cd koi-sensors

# Setup all sensors with isolated virtual environments
./setup_all.sh

# Start all configured sensors
./start_all.sh

# Check sensor status
./status.sh

# Stop all sensors
./stop_all.sh
```

#### **Individual Sensor Setup**
Each sensor has its own isolated environment:
```bash
# Setup individual sensor
cd sensors/<sensor_name>
./setup.sh

# Start individual sensor
./start.sh
# Or in background: ./start.sh --background
```

### Sensor Management Architecture

The system uses a **microservices architecture** with isolated virtual environments:

- **Individual Isolation**: Each sensor runs in its own `venv` with specific dependencies
- **Master Orchestration**: Unified scripts for system-wide operations
- **Replicable Setup**: Anyone cloning the repo can run `./setup_all.sh` to install everything

#### **Available Commands**
```bash
# System-wide operations
./setup_all.sh    # Setup all sensors (interactive: sequential/parallel)
./start_all.sh    # Start all configured sensors
./stop_all.sh     # Gracefully stop all sensors
./status.sh       # Show current status of all sensors

# Individual sensor operations (in sensors/<name>/)
./setup.sh        # Setup this sensor's environment
./start.sh        # Start this sensor
./start.sh -b     # Start in background mode
```

### Running Modes

#### **Production Mode** (All Sensors)
```bash
# One-time setup
./setup_all.sh

# Start everything
./start_all.sh

# Monitor
./status.sh
tail -f sensors/*/\*.log
```

#### **Development Mode** (Individual Sensors)
```bash
# Work on specific sensor
cd sensors/github
./setup.sh
./start.sh

# Test changes
python3 github_sensor_v2.py
```

#### **Docker Deployment**
```bash
docker-compose up -d
docker-compose logs -f website-sensor
```

## 📁 Project Structure

```
koi-sensors/
├── koi_protocol/                # Core KOI protocol implementation
│   ├── core/                    # RID system, Bundle system, Events
│   │   ├── rid_system.py        # Resource identifier generation
│   │   ├── bundle_system.py     # Content packaging system
│   │   └── node.py              # Base node functionality
│   ├── coordinator/             # KOI Coordinator (event routing)
│   └── nodes/                   # Full/Partial node implementations
├── sensors/                     # Individual sensor implementations
│   ├── websites/                # Website monitoring sensor ✅ COMPLETE
│   │   ├── website_sensor.py    # Main sensor implementation
│   │   ├── config.yaml          # 9 websites configured
│   │   ├── test_*.py            # Comprehensive test suite
│   │   ├── extracted_website_data.json # Actual scraped data
│   │   └── docker-compose.yml   # Docker deployment
│   ├── podcast/                 # Podcast monitoring sensor ✅ COMPLETE
│   │   ├── podcast_sensor.py    # SoundCloud podcast monitoring
│   │   ├── config.yaml          # Planetary Regeneration Podcast
│   │   ├── test_podcast_sensor.py # Standalone testing
│   │   └── Dockerfile           # Docker deployment
│   └── github_activity/         # GitHub Activity sensor ✅ COMPLETE
│       ├── github_activity_sensor.py # Comprehensive GitHub activity tracking
│       ├── config.yaml          # 5 Regen Network repos configured
│       ├── setup.sh             # Setup script with venv isolation
│       └── start.sh             # Start script for background operation
├── shared/                      # Shared utilities
└── docs/                        # Documentation and guides
```

## 📋 Website Monitoring Status

### 🌐 **Website Sensor** ✅ COMPLETE

**Successfully Tested 9 Websites** (100% success rate):

| Website | Priority | Content | Links | Status |
|---------|----------|---------|-------|--------|
| registry.regen.network | High | 10,760 chars | 30 | ✅ Ready for deep crawl |
| regen.foundation | Medium | 8,801 chars | 4 | ✅ Foundation content |
| researchretreat.org/papers | High | 7,334 chars | 23 | ✅ Research papers |
| desci.com | Medium | 5,415 chars | 19 | ✅ DeSci platform |
| forum.regen.network | Medium | 2,669 chars | 151 | ✅ Forum topics |
| regentokenomics.org | High | 837 chars | 19 | ✅ Tokenomics docs |
| regencommons.discourse.group | Low | 653 chars | 30 | ✅ Community |
| docs.regen.network | High | 524 chars | 2 | ✅ Tech docs |
| guides.regen.network | Medium | 401 chars | 6 | ✅ User guides |

**Total**: 37,394 characters extracted, 233+ internal links discovered

### 🎧 **Podcast Sensor** ✅ COMPLETE WITH TRANSCRIPTION
- **Coverage**: Planetary Regeneration Podcast (68/70 episodes successfully transcribed)
- **Platform**: SoundCloud with yt-dlp audio download
- **Transcription**: OpenAI Whisper AI (base model) - same as server-project
- **Content Volume**: 428,113+ words successfully extracted
- **Missing Episodes**: #34 and #43 were never published (confirmed)
- **Enhanced Version**: `enhanced_podcast_sensor.py` with full transcription pipeline
- **Proven Methods**: Uses exact approach that worked in server-project
- **Status**: Production-ready with audio download and transcription

### ✅ **Notion Sensor** COMPLETE (Session 2 Addition)
- **Coverage**: Full Notion workspace monitoring via API integration
- **Features**: Database discovery, page content extraction, property handling
- **Change Detection**: SHA-256 content hashing for NEW/UPDATE events
- **Integration**: Complete KOI Event Bridge support with RID generation
- **Status**: Ready for production with provided integration secret

### 💬 **Telegram Sensor v2** ✅ COMPLETE
- **Coverage**: Real-time Telegram channel/group monitoring
- **Features**: Message content extraction, media attachment handling, forward tracking
- **Bot Integration**: Uses Telegram Bot API with dedicated bot token
- **RID Generation**: Full support for telegram source_type with proper document fields
- **Setup Guide**: [Complete documentation](docs/TELEGRAM_SENSOR_SETUP.md)
- **Status**: Production-ready, monitoring Regen Network public channel

### 🐦 **Additional Sensors** 📋 PLANNED
- **Twitter Sensor**: Real-time tweet monitoring (files exist, needs completion)
- **Discord Sensor**: Message monitoring (waiting for bot channel approval)

## 📊 Integration with Existing System

### **Complementary Architecture**
The KOI sensor network **augments** the existing server system (86.4% success, 12,967+ documents):

| Aspect | Server System | KOI Sensor Network |
|--------|---------------|-------------------|
| **Mode** | Batch processing | Real-time monitoring |
| **Documents** | 12,967+ indexed | Live change detection |
| **Website Coverage** | ~64 documents | 300+ potential documents |
| **Update Frequency** | Manual re-runs | Continuous monitoring |
| **Architecture** | ChromaDB storage | KOI events → Apache Jena |

### **Document Format Compatibility**
```json
{
  "id": "web_1ef62e1ed208c19c",
  "source": "web:docs.regen.network",
  "content": "Full extracted content...",
  "title": "Page title", 
  "rid": "orn:web.page:docs.regen.network/1ef62e1ed208c19c"
}
```

### **Expansion Impact**
- **Current server**: ~64 website documents  
- **Sensor discovery**: 233+ URLs found from 9 landing pages
- **Deep crawl potential**: 500+ documents from registry alone
- **Contribution to 15,000 target**: Major expansion of website coverage

## 🔧 Configuration

Configure monitoring in `sensors/websites/config.yaml`:

```yaml
websites:
  - name: registry-regen-network
    url: https://registry.regen.network
    priority: high
    check_interval: 1800  # 30 minutes
    max_depth: 3
    current_status: "20 docs indexed - needs expansion for ALL credit classes"
```

## 🧪 Testing Results

### **Comprehensive Test Suite**
- ✅ **Basic functionality**: RID generation, change detection
- ✅ **Real crawling**: Live website content extraction  
- ✅ **Full configuration**: All 9 websites tested
- ✅ **Deep discovery**: 233+ URLs found for expansion
- ✅ **Docker deployment**: Production-ready containers

### **Key Findings**
- **100% website success** rate on all 9 target websites
- **95.7% podcast success** rate (67/70 episodes detected - optimal for real-time monitoring)
- **37,394 characters** extracted from website landing pages
- **465,507+ characters** total monitored content (websites + podcasts)
- **Registry goldmine**: 10,760 characters with 30+ credit class links
- **Research expansion**: Successfully added 3 new research sites
- **Podcast integration**: Aligned with existing 52 transcripts (428,113+ words)
- **Historical Episode Analysis**: Episode 22 (2020) exists but not in current feeds - expected behavior

## 🤝 Integration Requirements

### **Coordinator-Processor Bridge**
```python
# Required in koi-processor repository
@app.post("/process-koi-event")
async def process_koi_event(event: KOIEventRequest):
    document = bundle_to_document(event.bundle)
    processed_result = await process_document_with_unified_ontology(document)
    await store_in_jena_triplestore(processed_result)  # Not Neo4j
```

## 📄 License

Part of the Joint Development Agreement between Regen Network and partner organizations.

---

**Built with 🌱 for the Regen Network ecosystem**

*The KOI Sensor Network: Real-time knowledge monitoring for a regenerative future.*
## 🛡️ Production Operations & Monitoring

### Systemd Service Management (Added December 2025)

All sensors now run as **systemd services** with automatic restart and failure alerting.

#### Service Architecture
- **Template Unit**:  - single template for all sensors
- **Alert Service**:  - triggered on failures
- **Wrapper Script**:  - handles venv and environment

#### Quick Commands
```bash
# Check status of all sensors
systemctl list-units 'koi-sensor@*'

# Check specific sensor
sudo systemctl status koi-sensor@discourse

# View logs (real-time)
journalctl -u koi-sensor@discourse -f

# Restart a sensor
sudo systemctl restart koi-sensor@discourse

# Stop a sensor
sudo systemctl stop koi-sensor@discourse

# Start a new sensor
sudo systemctl enable --now koi-sensor@gitlab

# Disable a sensor from boot
sudo systemctl disable koi-sensor@discourse
```

#### Currently Enabled Sensors
- `koi-sensor@discourse` - Forum monitoring
- `koi-sensor@github` - Repository monitoring
- `koi-sensor@telegram` - Channel monitoring
- `koi-sensor@twitter` - Social media monitoring
- `koi-sensor@websites` - Website monitoring

### Email Alerting System

When a sensor fails repeatedly (5 times in 10 minutes), systemd stops retrying and sends an email alert.

#### Configuration Files
| File | Purpose |
|------|---------|
| `~/.msmtprc` | SMTP credentials (Mailjet) |
| `.alert-config` | Alert recipient email |
| `scripts/send-failure-alert.sh` | Alert email script |
| `scripts/health-check.sh` | Hourly health check |

#### Restart Behavior
- **Restart Policy**: `on-failure` with 30-second delay
- **Failure Limit**: 5 failures within 10 minutes
- **On Exceed Limit**: Stops retrying, triggers `OnFailure=` alert

### Health Check Cron

An hourly cron job detects stale sensors (no log activity in 2+ hours):
```
0 * * * * /opt/projects/koi-sensors/scripts/health-check.sh
```

### Logs

| Log Type | Location |
|----------|----------|
| Sensor logs | `sensors/<name>/<name>_sensor.log` |
| Systemd logs | `journalctl -u koi-sensor@<name>` |
| Alert log | `logs/alerts.log` |
| SMTP log | `logs/msmtp.log` |
| Health check | `logs/alerts.log` |

### Adding a New Sensor to Systemd

1. Ensure the sensor has a Python script matching the pattern in `scripts/run-sensor.sh`
2. Enable and start:
   ```bash
   sudo systemctl enable --now koi-sensor@<sensor-name>
   ```
3. Verify:
   ```bash
   sudo systemctl status koi-sensor@<sensor-name>
   ```

## 🛡️ Production Operations & Monitoring

### Systemd Service Management (Added December 2025)

All sensors now run as **systemd services** with automatic restart and failure alerting.

#### Service Architecture
- **Template Unit**: `/etc/systemd/system/koi-sensor@.service` - single template for all sensors
- **Alert Service**: `/etc/systemd/system/koi-sensor-alert@.service` - triggered on failures
- **Wrapper Script**: `/opt/projects/koi-sensors/scripts/run-sensor.sh` - handles venv and environment

#### Quick Commands
```bash
# Check status of all sensors
systemctl list-units 'koi-sensor@*'

# Check specific sensor
sudo systemctl status koi-sensor@discourse

# View logs (real-time)
journalctl -u koi-sensor@discourse -f

# Restart a sensor
sudo systemctl restart koi-sensor@discourse

# Stop a sensor
sudo systemctl stop koi-sensor@discourse

# Start a new sensor
sudo systemctl enable --now koi-sensor@gitlab

# Disable a sensor from boot
sudo systemctl disable koi-sensor@discourse
```

#### Currently Enabled Sensors
- `koi-sensor@discourse` - Forum monitoring
- `koi-sensor@github` - Repository monitoring  
- `koi-sensor@telegram` - Channel monitoring
- `koi-sensor@twitter` - Social media monitoring
- `koi-sensor@websites` - Website monitoring

### Email Alerting System

When a sensor fails repeatedly (5 times in 10 minutes), systemd stops retrying and sends an email alert.

#### Configuration Files
| File | Purpose |
|------|---------|
| `~/.msmtprc` | SMTP credentials (Mailjet) |
| `.alert-config` | Alert recipient email |
| `scripts/send-failure-alert.sh` | Alert email script |
| `scripts/health-check.sh` | Hourly health check |

#### Restart Behavior
- **Restart Policy**: `on-failure` with 30-second delay
- **Failure Limit**: 5 failures within 10 minutes
- **On Exceed Limit**: Stops retrying, triggers `OnFailure=` alert

### Health Check Cron

An hourly cron job detects stale sensors (no log activity in 2+ hours):
```
0 * * * * /opt/projects/koi-sensors/scripts/health-check.sh
```

### Logs

| Log Type | Location |
|----------|----------|
| Sensor logs | `sensors/<name>/<name>_sensor.log` |
| Systemd logs | `journalctl -u koi-sensor@<name>` |
| Alert log | `logs/alerts.log` |
| SMTP log | `logs/msmtp.log` |

### Adding a New Sensor to Systemd

1. Ensure the sensor has a Python script matching the pattern in `scripts/run-sensor.sh`
2. Enable and start:
   ```bash
   sudo systemctl enable --now koi-sensor@<sensor-name>
   ```
3. Verify:
   ```bash
   sudo systemctl status koi-sensor@<sensor-name>
   ```
