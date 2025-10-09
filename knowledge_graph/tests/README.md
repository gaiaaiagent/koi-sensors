# Knowledge Graph Phase 2 Validation Suite

This directory contains comprehensive validation tests for the KG extraction pipeline.

## Overview

The validation suite tests KG extraction on **real scraped data** from multiple sensor types:
- Website (forum.regen.network, etc.)
- Discourse (forum posts)
- GitHub (repositories, documentation)
- Notion (pages)
- GitLab (project documentation)
- Podcast (transcripts)
- GitHub Activity (commits, issues)

## Test Files

### 1. `test_phase2_validation.py`
**Purpose**: Test KG extraction on real sensor data

**What it does**:
- Selects 17 sample documents across 7 sensor types
- Runs Pass A extraction on each document
- Verifies database storage and CAT receipts
- Validates RID formats and provenance
- Calculates metrics by sensor type

**Output**: `phase2_validation_results.json`

**Run**:
```bash
cd /opt/projects/koi-sensors
source venv/bin/activate
export POSTGRES_URL="postgresql://postgres:postgres@localhost:5433/eliza"
python knowledge_graph/tests/test_phase2_validation.py
```

### 2. `test_e2e_integration.py`
**Purpose**: End-to-end integration tests

**What it tests**:
- Direct extraction pipeline (simulating event bridge)
- Complete provenance chain validation
- RID format validation
- CAT receipt creation and metadata
- Deduplication logic

**Run**:
```bash
python knowledge_graph/tests/test_e2e_integration.py
```

### 3. `validate_cross_sensor.py`
**Purpose**: Cross-sensor quality analysis

**What it analyzes**:
- Extraction quality by sensor type
- Entity and statement type distribution
- Cost efficiency by sensor
- Performance ranking

**Run**:
```bash
python knowledge_graph/tests/validate_cross_sensor.py
```

### 4. `validate_provenance.sql`
**Purpose**: Provenance chain validation queries

**What it checks**:
- Source URL coverage (should be 100%)
- CAT receipt coverage (should be 100%)
- RID chain validity
- Orphaned records (should be 0)
- Broken references (should be 0)

**Run**:
```bash
psql $POSTGRES_URL -f knowledge_graph/tests/validate_provenance.sql
```

### 5. `generate_metrics_report.py`
**Purpose**: Comprehensive metrics report

**Metrics collected**:
- Overall extraction counts and averages
- Cost analysis (total, per-document, per-entity, per-statement)
- Provenance tracking metrics
- Quality distribution (confidence scores)
- Entity and statement type breakdowns
- Temporal metrics (daily/hourly)

**Output**: `kg_metrics_report.json`

**Run**:
```bash
python knowledge_graph/tests/generate_metrics_report.py
```

## Running the Full Suite

### Option 1: Run All Tests at Once (Recommended)
```bash
cd /opt/projects/koi-sensors/knowledge_graph
./tests/run_full_validation.sh
```

This script:
1. Activates the virtual environment
2. Runs all 5 test suites in order
3. Generates comprehensive reports
4. Provides a summary at the end

### Option 2: Run Tests Individually
Useful for debugging specific issues:

```bash
cd /opt/projects/koi-sensors
source venv/bin/activate
export POSTGRES_URL="postgresql://postgres:postgres@localhost:5433/eliza"

# Test 1: Historical data processing
python knowledge_graph/tests/test_phase2_validation.py

# Test 2: Integration tests
python knowledge_graph/tests/test_e2e_integration.py

# Test 3: Cross-sensor analysis
python knowledge_graph/tests/validate_cross_sensor.py

# Test 4: Provenance validation
psql $POSTGRES_URL -f knowledge_graph/tests/validate_provenance.sql

# Test 5: Metrics report
python knowledge_graph/tests/generate_metrics_report.py
```

## Expected Results

### Success Criteria

✅ **Extraction Quality**
- Entity extraction F1 ≥ 0.80 (Target: >0.90)
- Statement extraction F1 ≥ 0.80 (Target: >0.85)
- Average confidence score ≥ 0.75

✅ **Provenance Tracking**
- Source URL coverage: 100%
- CAT receipt coverage: 100%
- RID validity: 100%
- Orphaned records: 0

✅ **Cost Efficiency**
- Average cost per document: ~$0.0003-0.0005
- Projected monthly cost (if running continuously): <$50

✅ **Data Quality**
- No broken references
- Valid RID chains
- Complete metadata preservation

### Sample Output

After running the full suite, you should see:

```
📊 Overall Results:
   Total Tested: 17
   Successful: 17 (100.0%)
   Failed: 0

📈 Extraction Metrics:
   Total Entities: 45
   Total Statements: 62
   Avg Entities/Doc: 2.6
   Avg Statements/Doc: 3.6

💰 Cost Analysis:
   Total Cost: $0.0068
   Avg Cost/Doc: $0.0004

🔬 Results by Sensor Type:
   website:     3 docs, avg 3.0 entities, 4.5 statements
   discourse:   3 docs, avg 2.5 entities, 3.8 statements
   github:      3 docs, avg 2.2 entities, 3.2 statements
   ...
```

## Troubleshooting

### No Extractions Found
If tests report "No KG extractions found":
1. Run `test_phase2_validation.py` first to generate test data
2. Check that `KG_EXTRACTION_ENABLED=true` in `.env`
3. Verify database connection: `psql $POSTGRES_URL -c "\dt koi_kg_*"`

### Database Connection Issues
```bash
# Check PostgreSQL is running
docker ps | grep postgres

# Test connection
psql postgresql://postgres:postgres@localhost:5433/eliza -c "SELECT 1"

# Verify tables exist
psql postgresql://postgres:postgres@localhost:5433/eliza -c "\dt koi_kg_*"
```

### OpenAI API Errors
```bash
# Check API key is set
echo $OPENAI_API_KEY

# Or check in .env file
grep OPENAI_API_KEY /opt/projects/koi-sensors/.env
```

### Import Errors
```bash
# Make sure you're in the right directory
cd /opt/projects/koi-sensors

# Activate virtual environment
source venv/bin/activate

# Check Python path
python -c "import sys; print(sys.path)"
```

## Output Files

After running the full suite, you'll have:

- `phase2_validation_results.json` - Detailed test results by sensor
- `kg_metrics_report.json` - Cost and performance metrics
- `provenance_validation_results.txt` - SQL validation output

Review these files to:
- Identify sensor-specific extraction patterns
- Analyze cost efficiency
- Validate provenance completeness
- Plan Phase 3 priorities

## Next Steps

After validation:

1. **Review Results**: Check all metrics meet success criteria
2. **Identify Issues**: Note any sensors with low F1 scores or high costs
3. **Cost Analysis**: Decide if projections are acceptable for continuous operation
4. **Phase 3 Planning**: Choose which advanced features to implement:
   - Entity Resolution (merge duplicate entities)
   - Contradiction Detection (find conflicting statements)
   - MCP Server Enhancement (KG-enriched search)
   - Monitoring Integration (metrics dashboard)

## Support

For issues or questions:
- Check the implementation plan: `/opt/projects/.claude/Regen_KOI_Knowledge_Graph_Steps.md`
- Review extractor code: `/opt/projects/koi-sensors/knowledge_graph/extractors/`
- Check database schema: `/opt/projects/koi-processor/migrations/013_create_kg_tables.sql`
