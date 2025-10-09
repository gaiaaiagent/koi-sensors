# Bulk KG Extraction Scripts

## Overview

Scripts for bulk processing existing memories through the Knowledge Graph extraction pipeline.

**Current Status**:
- 5,157 documents ready for extraction (Website, Discourse, Notion, Podcast)
- Excludes: GitHub and GitLab repos (less important)
- Estimated cost: ~$5.16 (at $0.001/doc with gpt-5-mini)
- Estimated time: ~45-60 min (with 5 parallel workers)

## Quick Start

### 1. Dry Run (Preview)
```bash
cd /opt/projects/koi-sensors
source venv/bin/activate
export POSTGRES_URL="postgresql://postgres:postgres@localhost:5433/eliza"
export OPENAI_API_KEY="your-key-here"

python knowledge_graph/scripts/bulk_extract.py --dry-run
```

### 2. Test Run (100 documents)
```bash
python knowledge_graph/scripts/bulk_extract.py --limit 100
```

### 3. Full Run (All 5,157 documents)
```bash
# Run in background with progress logging
nohup python knowledge_graph/scripts/bulk_extract.py > bulk_extract.log 2>&1 &

# Monitor progress
tail -f bulk_extract.log
```

## Command Line Options

```bash
python knowledge_graph/scripts/bulk_extract.py [OPTIONS]

Options:
  --limit INT         Limit number of documents (default: all)
  --batch-size INT    Batch size (default: 100)
  --workers INT       Max parallel workers (default: 5)
  --model STR         Model to use (default: gpt-5-mini)
  --dry-run          Preview what would be processed
```

## Examples

### Fast Processing (10 workers)
```bash
python knowledge_graph/scripts/bulk_extract.py --workers 10
```

### Using Claude instead of GPT
```bash
export ANTHROPIC_API_KEY="your-key"
python knowledge_graph/scripts/bulk_extract.py --model claude-3-5-haiku-20241022
```

### Process only Website docs
Modify the SQL query in `bulk_extract.py` line 60:
```python
AND m.source_sensor LIKE 'website%'
```

## Output

The script provides real-time progress updates:

```
📦 Batch 1/52 (100 docs)
✓ Progress: 100/5157 docs
  Success: 98 | Failed: 2 | Skipped: 0
  Cost so far: $0.10
  Rate: 2.5 docs/sec | ETA: 33.6 min
```

Final summary:
```
================================================================================
BULK EXTRACTION COMPLETE
================================================================================
Total Processed: 5157
Successful: 5120
Failed: 35
Skipped: 2
Total Entities: 25,000
Total Statements: 35,000
Total Cost: $5.16
Avg Cost/Doc: $0.0010
```

## Post-Processing

After bulk extraction completes:

### 1. Run Entity Resolution
```bash
cd /opt/projects/koi-sensors
python -m knowledge_graph.entity_resolver
```

### 2. Generate Metrics
```bash
python -m knowledge_graph.monitoring.kg_metrics --export metrics_$(date +%Y%m%d).json
```

### 3. Enable Real-Time Processing
```bash
# In /opt/projects/koi-processor/.env
KG_EXTRACTION_ENABLED=true
```

## Troubleshooting

### Rate Limits
If you hit OpenAI rate limits, reduce workers:
```bash
python knowledge_graph/scripts/bulk_extract.py --workers 2
```

### Resuming After Interruption
The script automatically skips already-extracted documents. Just re-run:
```bash
python knowledge_graph/scripts/bulk_extract.py
```

### Checking Progress
```bash
# Count extractions
docker exec gaia-postgres-1 psql -U postgres -d eliza -c \
  "SELECT COUNT(*) FROM koi_kg_extractions;"

# Check cost so far
docker exec gaia-postgres-1 psql -U postgres -d eliza -c \
  "SELECT SUM(cost_usd) as total_cost FROM koi_kg_extractions;"
```

## Excluded Sensors

The following are excluded from bulk extraction:
- **GitHub repos**: 6,177 docs (code files, less valuable for KG)
- **GitLab repos**: 1,600 docs (code files, less valuable for KG)

To include them, remove the exclusion filter in `bulk_extract.py` line 65-66.

## Next Steps After Bulk Extraction

1. **Entity Resolution** - Merge duplicate entities across documents
2. **Contradiction Detection** - Find conflicting statements
3. **Metrics Dashboard** - Visualize extraction quality and coverage
4. **Enable Real-Time** - Process new docs automatically via event bridge
