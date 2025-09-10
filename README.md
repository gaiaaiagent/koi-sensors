# KOI Sensor Network

Real-time knowledge monitoring infrastructure for the Regen Network AI Agent System. This system provides continuous, event-driven data collection using the KOI (Knowledge Organization Infrastructure) protocol, complementing the existing batch-processing system with live monitoring capabilities.

## 📊 Current Status

**PRODUCTION READY** ✅ - Complete KOI Sensor-to-Agent Pipeline Operational

**Full Pipeline Integration Complete**: Real-time content flows from sensors through KOI Event Bridge to Eliza agents
- ✅ **KOI Event Bridge Integration**: Coordinator forwards events to processor (port 8100)
- ✅ **BGE Embedding Generation**: 1024-dimensional vectors for semantic search
- ✅ **PostgreSQL Storage**: Direct integration with agent database using pgvector
- ✅ **Agent RAG Access**: Content immediately available for queries (<3-5 seconds)
- ✅ **CAT Receipts**: Full provenance tracking through transformation pipeline
- ✅ **Production Tested**: End-to-end pipeline verified with real content

**Website Sensor Results**: 9/9 websites tested successfully (100% success rate)
- ✅ Core Regen websites: docs, guides, registry, foundation (4/4)
- ✅ Community forums: forum.regen.network, regencommons (2/2)  
- ✅ Research sites: researchretreat.org/papers, desci.com, regentokenomics.org (3/3)
- ✅ **37,394 characters extracted**, 233+ links discovered for expansion
- ✅ RID generation working: `orn:web.page:domain/hash`
- ✅ Content change detection operational
- ✅ Docker deployment ready

## 🔄 Event Bridge v2 Integration

**NEW**: The KOI sensor network now integrates with Event Bridge v2, providing:
- **RID-based Deduplication**: Automatically prevents duplicate content ingestion using Resource Identifiers
- **Version Control**: UPDATE events create new versions with complete audit trail
- **Isolated Tables**: Clean separation between sensor data and other content sources
- **Production Tested**: Deduplication verified working on live Regen Network infrastructure

See [koi-processor v2.0.0](https://github.com/gaiaaiagent/koi-processor) for implementation details.

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

## 🌟 Features

### **KOI Protocol Compliance**
- **Resource Identifiers (RIDs)**: Unique identifiers using ORN format (`orn:web.page:domain/hash`)
- **Bundle System**: Manifest-based content packaging with SHA-256 integrity
- **Event System**: NEW/UPDATE/FORGET events for real-time knowledge updates
- **Full/Partial Nodes**: Complete KOI-net architecture implementation

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

### Installation
```bash
git clone https://github.com/gaiaaiagent/koi-sensors.git
cd koi-sensors/sensors/websites
pip install -r requirements.txt
```

### Running Modes

#### **Standalone Mode** (Testing/Development)
```bash
# Test all configured websites
python test_all_websites.py

# Show extracted data
python show_extracted_data.py

# Run website sensor independently
python run_website_sensor.py
```

#### **Networked Mode** (Production)
```bash
# Terminal 1: Start KOI Coordinator
python ../../koi_protocol/coordinator/run_coordinator.py

# Terminal 2: Start Website Sensor
python run_website_sensor.py

# Terminal 3: Monitor events
curl http://localhost:8000/events/poll
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
│   └── podcast/                 # Podcast monitoring sensor ✅ COMPLETE
│       ├── podcast_sensor.py    # SoundCloud podcast monitoring
│       ├── config.yaml          # Planetary Regeneration Podcast
│       ├── test_podcast_sensor.py # Standalone testing
│       └── Dockerfile           # Docker deployment
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

### 🎧 **Podcast Sensor** ✅ COMPLETE
- **Coverage**: Planetary Regeneration Podcast (67/70 episodes detected, 95.7% rate)
- **Platform**: SoundCloud with proven server collection methods
- **Real-time Detection**: All recent/accessible episodes monitored for changes
- **Historical Episodes**: Older episodes (like 2020's Episode 22) not in current feeds - normal behavior
- **Integration**: Aligned with existing 52 transcripts (428,113+ words)  
- **Monitoring**: 24-hour intervals for new episodes and transcript updates
- **Status**: Ready for coordinator integration

### 🐦 **Additional Sensors** 📋 PLANNED
- **Twitter Sensor**: Real-time tweet monitoring
- **Discord Sensor**: Message monitoring with bot permissions  
- **Notion Sensor**: Database content monitoring

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

## 🎯 Roadmap

### **Phase 1** ✅ COMPLETE
- [x] KOI protocol core implementation (100% compliant)
- [x] Website sensor with comprehensive testing (9/9 websites, 100% success)
- [x] Podcast sensor with SoundCloud integration (67/70 episodes, 95.7% success)
- [x] Docker deployment ready for both sensors
- [x] Server integration alignment (proven collection methods preserved)

### **Phase 2** 🔄 READY FOR INTEGRATION
- [ ] Coordinator-Processor bridge (`/process-koi-event` endpoint)
- [ ] Apache Jena integration (replace Neo4j references)
- [ ] Production deployment testing
- [ ] Deep crawling implementation (233+ URLs → hundreds of documents)

### **Phase 3** 🎯 PLANNED
- [ ] Twitter sensor implementation
- [ ] Discord sensor with bot permissions
- [ ] Notion sensor with API integration
- [ ] Full multi-sensor orchestration

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

### **Integration Checklist**
- [ ] Deploy Apache Jena Fuseki triplestore
- [ ] Add KOI event processing endpoint
- [ ] Connect coordinator to processor pipeline
- [ ] Test full flow: Sensors → Coordinator → Processor → Apache Jena

## 📄 License

Part of the Joint Development Agreement between Regen Network and partner organizations.

---

**Built with 🌱 for the Regen Network ecosystem**

*The KOI Sensor Network: Real-time knowledge monitoring for a regenerative future.*