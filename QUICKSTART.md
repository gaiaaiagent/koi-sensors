# Quick Start Guide - KOI Sensor Network

## 🚀 Production Pipeline Setup

### 1. Prerequisites
```bash
python3 --version  # Need 3.11+
pip install -r requirements.txt

# Create .env file for API keys (optional)
cat > .env << EOF
# KOI Coordinator
KOI_COORDINATOR_URL=http://localhost:8005
KOI_COORDINATOR_PORT=8005

# Notion Integration (optional)
NOTION_API_KEY=your_notion_integration_secret

# Twitter API (optional)
TWITTER_BEARER_TOKEN=your_twitter_bearer_token
EOF
```

### 2. Start the Complete KOI Pipeline

#### Terminal 1: KOI Coordinator
```bash
cd koi-sensors
source venv/bin/activate
KOI_COORDINATOR_PORT=8005 python koi_protocol/coordinator/run_coordinator.py
# Runs on port 8005
```

#### Terminal 2: KOI Event Bridge (in koi-processor repo)
```bash
cd ../koi-processor
python koi_event_bridge.py
# Runs on port 8100
```

#### Terminal 3: BGE Embedding Server (in koi-processor repo)
```bash
cd ../koi-processor
python bge_server.py
# Runs on port 8888
```

#### Terminal 4: Start All Sensors
```bash
# Option A: Use the unified startup script
./start_all.sh

# Option A.1: Include personal sensors (email + Claude sessions)
ENABLE_PERSONAL_SENSORS=true ./start_all.sh

# Option B: Start individually with setup
cd sensors/discord && ./setup.sh && ./start.sh -b
cd sensors/twitter && ./setup.sh && ./start.sh -b
cd sensors/notion && ./setup.sh && ./start.sh -b
cd sensors/discourse && ./setup.sh && ./start.sh -b
cd sensors/telegram && ./setup.sh && ./start.sh -b
cd sensors/websites && ./setup.sh && ./start.sh -b
cd sensors/github && ./setup.sh && ./start.sh -b
cd sensors/gitlab && ./setup.sh && ./start.sh -b
cd sensors/medium && ./setup.sh && ./start.sh -b
cd sensors/podcast && ./setup.sh && ./start.sh -b
cd sensors/ledger && ./setup.sh && ./start.sh -b
```

#### Optional Terminal 5: Personal Sensors Only
```bash
cd sensors/email && ./setup.sh && ./start.sh --background
cd sensors/claude_sessions && ./setup.sh && ./start.sh --background
```

### 3. Verify Pipeline Operation
```bash
# Check coordinator status
curl http://localhost:8005/sensors

# Check dashboard
open https://regen.gaiaai.xyz/koi

# Test content injection
python test_website_sensor.py
```

## 📊 Content Processing Flow

### How Content Flows Through the Pipeline
1. **Sensor Detection**: Website/podcast sensors detect new or changed content
2. **KOI Event Generation**: Content packaged with RID and CID identifiers
3. **Coordinator Routing**: Events forwarded to processor bridge
4. **BGE Processing**: Text chunked and embeddings generated (1024-dim)
5. **PostgreSQL Storage**: Embeddings stored with pgvector extension
6. **Agent Access**: Content immediately available for RAG queries (<3-5s)

### Monitor Processing
```bash
# Watch events being processed (POST polling per KOI-net protocol)
curl -X POST http://localhost:8000/events/poll \
  -H "Content-Type: application/json" \
  -d '{"type":"poll_events","node_id":"monitor","limit":10}'

# Check database for new content
psql -U postgres -d eliza_db -c "SELECT COUNT(*) FROM memories WHERE type='koi_document';"

# Query embeddings
psql -U postgres -d eliza_db -c "SELECT COUNT(*) FROM embeddings WHERE dim_1024 IS NOT NULL;"
```

## ✅ Pipeline Health Check

```bash
# Check all components are running
ps aux | grep -E "koi_coordinator|koi_event_bridge|bge_server|website_sensor"

# Test end-to-end flow
python test_pipeline_flow.py

# Expected output:
# ✅ Coordinator: Running on port 8000
# ✅ Event Bridge: Running on port 8100
# ✅ BGE Server: Running on port 8888
# ✅ Website Sensor: Active monitoring
# ✅ Database: Content stored and queryable
```

## 🆘 Troubleshooting

### Issue: "No module named 'sentence_transformers'"
```bash
source venv/bin/activate  # Activate virtual environment first
pip install -r indexing/requirements.txt
```

### Issue: MCP server build fails
```bash
cd mcp-server
npm install -D typescript  # Install missing TypeScript
npm run build
```

### Issue: Discourse collector gets no documents
- This is normal without API keys
- The system continues with other sources
- Add API keys to .env for full access

## 📚 More Information

- Full documentation: [README.md](README.md)
- Implementation details: [IMPLEMENTATION.md](IMPLEMENTATION.md)
- AI assistant guide: [CLAUDE.md](CLAUDE.md)
- Credential setup: [CREDENTIAL_SETUP.md](CREDENTIAL_SETUP.md)
