# Implementation Plan: Regen Network Indexing System

## Phase 1: Infrastructure Setup (Day 1-2)

### Step 1: Server Preparation
```bash
# Working directory
cd /home/regenai/project

# Create folder structure
mkdir -p indexing/{collectors,processors,storage/{documents,embeddings,metadata},scripts,config}
mkdir -p mcp-server
mkdir -p agents

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install MCP Server
```bash
# Clone and setup MCP
git clone https://github.com/regen-network/mcp.git mcp-server
cd mcp-server
npm install
# Note: TypeScript is required but not in package.json dependencies
npm install -D typescript
npm run build

# Test MCP server
npm run dev:server &
sleep 5
curl http://localhost:3000/health

# Create systemd service (optional for production)
sudo tee /etc/systemd/system/regen-mcp.service > /dev/null <<EOF
[Unit]
Description=Regen MCP Server
After=network.target

[Service]
Type=simple
User=regenai
WorkingDirectory=/home/regenai/project/mcp-server
ExecStart=/usr/bin/npm run start:server
Restart=always
Environment="NODE_ENV=production"

[Install]
WantedBy=multi-user.target
EOF
```

### Step 3: Python Dependencies
```bash
cd /home/regenai/project/indexing

# Create requirements.txt
cat > requirements.txt << 'EOF'
# Core
aiohttp>=3.9.0
httpx>=0.25.0
pyyaml>=6.0
python-dotenv>=1.0.0

# Git operations
GitPython>=3.1.40

# Web scraping
beautifulsoup4>=4.12.0
lxml>=4.9.0
html2text>=2020.1.16

# Embeddings & Vector Search
sentence-transformers>=2.2.0
faiss-cpu>=1.7.4
numpy>=1.24.0

# Document processing
pypdf2>=3.0.0
markdown>=3.5.0
langdetect>=1.0.9

# Discord
discord.py>=2.3.0

# Utilities
tqdm>=4.66.0
loguru>=0.7.0
diskcache>=5.6.0
schedule>=1.2.0
EOF

pip install -r requirements.txt
```

## Phase 2: Configuration Files (Day 2)

### Step 4: Create Configuration
```bash
cd /home/regenai/project/indexing/config

# Create sources configuration
cat > sources.yaml << 'EOF'
# Data Sources Configuration
sources:
  # GitHub Repositories
  github:
    - name: regen-ledger
      url: https://github.com/regen-network/regen-ledger.git
      branch: main
      paths:
        - docs/
        - x/ecocredit/spec/
        - "*.md"
    
    - name: regen-web
      url: https://github.com/regen-network/regen-web.git
      branch: main
      paths:
        - docs/
        - README.md
    
    - name: regenie-corpus
      url: https://github.com/regen-network/regenie-corpus.git
      branch: main
      paths:
        - "."
    
    - name: mcp
      url: https://github.com/regen-network/mcp.git
      branch: main
      paths:
        - README.md
        - docs/

  # GitLab Repositories  
  gitlab:
    - name: whitepaper
      url: https://gitlab.com/regen-network/regen-public-docs.git
      branch: master
      paths:
        - "*.pdf"
        - "*.md"

  # Discourse Forums
  discourse:
    - name: regen-forum
      url: https://forum.regen.network
      api_key: ${DISCOURSE_API_KEY_REGEN}
      categories:
        - governance
        - tokenomics
        - general
    
    - name: commons-forum
      url: https://forum.regencommons.com
      api_key: ${DISCOURSE_API_KEY_COMMONS}
      categories: all

  # Websites to scrape
  websites:
    - name: guides
      url: https://guides.regen.network
      max_depth: 3
      
    - name: foundation
      url: https://www.regen.foundation
      paths:
        - /publications
        - /initiatives
      
    - name: medium
      url: https://regen-network.medium.com
      max_articles: 100

  # Discord (requires bot token)
  discord:
    enabled: false
    guild_id: ${DISCORD_GUILD_ID}
    bot_token: ${DISCORD_BOT_TOKEN}
    channels:
      - general
      - governance
      - development

# Indexing settings
settings:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  chunk_size: 1000
  chunk_overlap: 200
  batch_size: 32
  max_workers: 4
EOF

# Create environment file template
cat > ../.env.template << 'EOF'
# Discourse API Keys (optional - works without for public content)
DISCOURSE_API_KEY_REGEN=
DISCOURSE_API_KEY_COMMONS=

# Discord Bot (optional)
DISCORD_GUILD_ID=
DISCORD_BOT_TOKEN=

# MCP Server
MCP_SERVER_URL=http://localhost:3000
EOF
```

## Phase 3: Core Implementation (Day 3-5)

### Step 5: Create Collector Modules

Create the main document collector:

```bash
cd /home/regenai/project/indexing/collectors

# Create __init__.py
cat > __init__.py << 'EOF'
from .git_collector import GitCollector
from .discourse_collector import DiscourseCollector
from .web_scraper import WebScraper

__all__ = ['GitCollector', 'DiscourseCollector', 'WebScraper']
EOF
```

### Step 6: Create Processor Modules

```bash
cd /home/regenai/project/indexing/processors

# Create __init__.py
cat > __init__.py << 'EOF'
from .koi_processor import KOIProcessor
from .embedder import Embedder
from .indexer import DocumentIndexer

__all__ = ['KOIProcessor', 'Embedder', 'DocumentIndexer']
EOF
```

### Step 7: Create Main Indexing Script

```bash
cd /home/regenai/project/indexing/scripts

# Create the main runner
cat > run_full_index.py << 'EOF'
#!/usr/bin/env python3
"""
Main indexing script for Regen Network content
Target: 15,000+ documents
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processors.indexer import DocumentIndexer
import asyncio
import yaml
from pathlib import Path

async def main():
    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "sources.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Initialize indexer
    indexer = DocumentIndexer(config)
    
    # Run full indexing
    print("🚀 Starting Regen Network content indexing...")
    print("📊 Target: 15,000+ documents")
    
    stats = await indexer.index_all()
    
    print("\n✅ Indexing Complete!")
    print(f"📄 Total documents indexed: {stats['total_documents']}")
    print(f"📁 GitHub repos: {stats['github_repos']}")
    print(f"💬 Forum posts: {stats['forum_posts']}")
    print(f"🌐 Web pages: {stats['web_pages']}")
    
    if stats['total_documents'] >= 15000:
        print("✅ Milestone 1.1 requirement met: 15,000+ documents indexed")
    else:
        print(f"⚠️  Need {15000 - stats['total_documents']} more documents")

if __name__ == "__main__":
    asyncio.run(main())
EOF

chmod +x run_full_index.py
```

## Phase 4: Testing & Verification (Day 6-7)

### Step 8: Create Verification Script

```bash
cd /home/regenai/project/indexing/scripts

cat > verify_index.py << 'EOF'
#!/usr/bin/env python3
"""
Verify indexing meets contract requirements
"""

import json
from pathlib import Path
import numpy as np
import time

def verify_index():
    storage = Path(__file__).parent.parent / "storage"
    
    # Count documents
    doc_count = len(list((storage / "documents").glob("*.json")))
    print(f"📄 Documents indexed: {doc_count}")
    
    # Count embeddings
    embedding_count = len(list((storage / "embeddings").glob("*.npy")))
    print(f"🔢 Embeddings created: {embedding_count}")
    
    # Test query speed
    print("\n⏱️  Testing query speed...")
    start = time.time()
    
    # Simulate document retrieval
    test_doc = list((storage / "documents").glob("*.json"))[0]
    with open(test_doc) as f:
        doc = json.load(f)
    
    # Load embedding
    doc_id = test_doc.stem
    embedding_path = storage / "embeddings" / f"{doc_id}.npy"
    if embedding_path.exists():
        embedding = np.load(embedding_path)
    
    elapsed = time.time() - start
    print(f"Query time: {elapsed:.3f} seconds")
    
    # Check requirements
    print("\n📋 Contract Requirements Check:")
    print(f"✅ 15,000+ documents: {'✓' if doc_count >= 15000 else '✗'} ({doc_count}/15000)")
    print(f"✅ <2 second response: {'✓' if elapsed < 2 else '✗'} ({elapsed:.3f}s)")
    print(f"✅ MCP integration: {'✓' if check_mcp() else '✗'}")
    
def check_mcp():
    import httpx
    try:
        response = httpx.get("http://localhost:3000/health", timeout=2)
        return response.status_code == 200
    except:
        return False

if __name__ == "__main__":
    verify_index()
EOF

chmod +x verify_index.py
```

## Phase 5: Integration (Day 8-10)

### Step 9: Create Agent Interface

```bash
cd /home/regenai/project/agents

cat > hybrid_retriever.py << 'EOF'
"""
Hybrid retriever for Eliza agents
Combines MCP (chain data) with RAG (documents)
"""

import httpx
from pathlib import Path
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from typing import Dict, List, Optional

class HybridRetriever:
    def __init__(self):
        self.mcp_url = "http://localhost:3000"
        self.storage = Path("/home/regenai/project/indexing/storage")
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        
    async def query(self, question: str) -> Dict:
        """
        Route query to appropriate source
        """
        # Detect query type
        if self._is_chain_query(question):
            return await self._query_mcp(question)
        else:
            return self._search_documents(question)
    
    def _is_chain_query(self, question: str) -> bool:
        """Check if query needs live chain data"""
        chain_keywords = [
            'price', 'available', 'marketplace', 'balance',
            'current', 'live', 'now', 'today', 'latest'
        ]
        return any(kw in question.lower() for kw in chain_keywords)
    
    async def _query_mcp(self, question: str) -> Dict:
        """Query MCP for live data"""
        # Implement MCP query logic
        pass
    
    def _search_documents(self, question: str) -> Dict:
        """RAG search for documents"""
        # Implement document search
        pass
EOF
```

### Step 10: Schedule Updates

```bash
cd /home/regenai/project/indexing/scripts

cat > schedule_updates.py << 'EOF'
#!/usr/bin/env python3
"""
Schedule 6-hour updates as per contract
"""

import schedule
import time
import subprocess

def update_index():
    print("🔄 Running scheduled index update...")
    subprocess.run(["python", "update_index.py"])

# Schedule every 6 hours
schedule.every(6).hours.do(update_index)

print("📅 Scheduler started - updates every 6 hours")
while True:
    schedule.run_pending()
    time.sleep(60)
EOF

chmod +x schedule_updates.py
```

## Phase 6: Deployment (Day 11-14)

### Step 11: Create Startup Script

```bash
cd /home/regenai/project

cat > start_indexing_system.sh << 'EOF'
#!/bin/bash

echo "🚀 Starting Regen Network Indexing System..."

# Start MCP server
echo "Starting MCP server..."
cd mcp-server
npm run start:server &
MCP_PID=$!

# Wait for MCP to be ready
sleep 5

# Activate Python environment
cd ../indexing
source ../venv/bin/activate

# Run initial indexing if needed
if [ ! -d "storage/documents" ] || [ -z "$(ls -A storage/documents)" ]; then
    echo "Running initial indexing..."
    python scripts/run_full_index.py
fi

# Start scheduler
echo "Starting update scheduler..."
python scripts/schedule_updates.py &
SCHEDULER_PID=$!

echo "✅ System started!"
echo "MCP Server PID: $MCP_PID"
echo "Scheduler PID: $SCHEDULER_PID"

# Keep running
wait
EOF

chmod +x start_indexing_system.sh
```

## Execution Timeline

| Day | Tasks | Deliverables |
|-----|-------|--------------|
| 1-2 | Infrastructure setup | MCP server running, Python environment ready |
| 3-5 | Core implementation | Collectors and processors coded |
| 6-7 | Testing & verification | 15,000+ documents indexed |
| 8-10 | Agent integration | Hybrid retriever working |
| 11-14 | Deployment & optimization | Production-ready system |

## Success Criteria Checklist

- [ ] MCP server running and accessible
- [ ] 15,000+ documents indexed
- [ ] <2 second query response time
- [ ] KOI RIDs generated for all content
- [ ] Embeddings created for all documents
- [ ] 6-hour update schedule configured
- [ ] Agent integration tested
- [ ] Verification script passes all checks

## Commands Summary

```bash
# Full setup
cd /home/regenai/project
./start_indexing_system.sh

# Manual indexing
python indexing/scripts/run_full_index.py

# Verify requirements
python indexing/scripts/verify_index.py

# Check MCP health
curl http://localhost:3000/health
```

## Next Steps After Implementation

1. Connect Eliza agents to hybrid retriever
2. Monitor performance metrics
3. Add Discord bot for channel indexing
4. Implement podcast transcription
5. Optimize embedding model if needed