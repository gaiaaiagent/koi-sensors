# Quick Start Guide

## 🚀 5-Minute Setup

### 1. Prerequisites Check
```bash
python3 --version  # Need 3.12+
node --version     # Need v18+
npm --version      # Need 9+
```

### 2. Automated Setup
```bash
# Clone repository
git clone https://github.com/regen-network/ai-agent-system.git
cd ai-agent-system

# Run setup (handles everything)
chmod +x setup.sh
./setup.sh
```

### 3. Quick Test
```bash
# Activate environment
source venv/bin/activate

# Test with 5 documents
python indexing/scripts/test_collection.py --limit 5

# Verify it worked
ls -la indexing/storage/documents/
```

## 📊 Full Indexing

### Option 1: Test Mode (Recommended First)
```bash
# Index 50-100 documents as a test
python indexing/scripts/run_full_index.py --test --limit 50
```

### Option 2: Production Indexing
```bash
# Index all 15,000+ documents (takes hours)
python indexing/scripts/run_full_index.py
```

### Option 3: With MCP Server
```bash
# Terminal 1: Start MCP server
cd mcp-server
npm run dev:server

# Terminal 2: Run indexing
cd ..
source venv/bin/activate
python indexing/scripts/run_full_index.py
```

## 🔍 Using the Search

```python
# Python example
from indexing.processors import Embedder

embedder = Embedder()
results = embedder.search("carbon credits", n_results=5)

for result in results:
    print(f"Content: {result['content'][:200]}...")
```

## ✅ Verify System

```bash
# Check all requirements
python indexing/scripts/verify_requirements.py

# Expected output:
# ✅ Query response time: <2s
# ✅ Embeddings generated
# ✅ KOI RIDs implemented
# ⚠️ Need to run full indexing for 15,000 documents
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