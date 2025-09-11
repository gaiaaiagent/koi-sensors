# Regen Network Ledger Sensor

Direct blockchain integration for querying Regen Network ledger data including governance proposals, ecocredit classes/batches, validators, and network statistics.

## Overview

The Ledger Sensor connects directly to Regen Network RPC and REST endpoints to collect:
- **Governance**: Proposals, votes, parameters
- **Ecocredits**: Credit classes, batches, marketplace listings
- **Consensus**: Validators, block heights, network status
- **Statistics**: Daily/weekly aggregated metrics

## Architecture

```
Regen Network Blockchain
    ├── RPC Endpoints ──┐
    └── REST Endpoints ─┴── Ledger Sensor
                                ├── Governance Queries
                                ├── Ecocredit Queries
                                ├── Consensus Queries
                                ├── Stats Aggregator
                                └── KOI Event Bridge Integration
```

## Components

### Core Modules

- `ledger_sensor.py` - Main sensor class extending BaseSensor
- `governance_queries.py` - Governance proposal and vote queries
- `ecocredit_queries.py` - Credit class, batch, and marketplace queries
- `consensus_queries.py` - Validator and network consensus queries
- `stats_aggregator.py` - Generate daily/weekly statistics
- `query_templates.py` - Pre-built query patterns for reports
- `koi_integration.py` - Send data to KOI Event Bridge

### Configuration

- `config.yaml` - Sensor configuration with endpoints and intervals

### Testing

- `test_ledger_sensor.py` - Comprehensive test suite
- `requirements.txt` - Python dependencies

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Test connectivity
python test_ledger_sensor.py
```

## Configuration

Edit `config.yaml` to configure:
- RPC/REST endpoint fallbacks
- Query intervals (governance, ecocredit, consensus)
- KOI Event Bridge URL
- Report generation settings

## Usage

### Test Mode

```python
# Run comprehensive tests
python test_ledger_sensor.py
```

This will:
1. Test endpoint connectivity
2. Query governance proposals
3. Query credit classes and batches
4. Check validator status
5. Generate daily statistics
6. Create sample outputs in `test_outputs/`

### Production Mode

```python
import asyncio
from ledger_sensor import LedgerSensor, LedgerSensorConfig

async def main():
    # Load configuration
    config = LedgerSensorConfig.load_from_yaml("config.yaml")
    
    # Create and start sensor
    sensor = LedgerSensor(config)
    await sensor.initialize()
    await sensor.start()

asyncio.run(main())
```

### Query Templates

Use pre-built templates for common queries:

```python
from query_templates import QueryTemplates

# Get data for daily tweet
tweet_data = await templates.data_for_daily_tweet()

# Get weekly digest content
digest = await templates.data_for_weekly_digest()

# Check network health
health = await templates.network_health_check()
```

## Data Flow

1. **Collection**: Queries blockchain endpoints on configured intervals
2. **Processing**: Normalizes and enriches raw blockchain data
3. **RID Generation**: Creates unique identifiers for each entity
4. **KOI Events**: Sends NEW/UPDATE/FORGET events to KOI bridge
5. **Statistics**: Aggregates metrics for daily/weekly reports

## Query Intervals

Default intervals (configurable):
- **Governance**: 5 minutes
- **Ecocredits**: 10 minutes
- **Consensus**: 1 minute
- **Statistics**: 1 hour
- **Daily Report**: 24 hours
- **Weekly Report**: 7 days

## Endpoints

### Primary Endpoints

**RPC**:
- `https://regen-rpc.polkachu.com`

**REST**:
- `https://regen-rest.publicnode.com`

### Fallback Endpoints

The sensor automatically fails over to backup endpoints if primary ones are unavailable.

## Output Examples

### Governance Proposal
```json
{
  "type": "governance_proposal",
  "proposal_id": "123",
  "title": "Parameter Change Proposal",
  "status": "PROPOSAL_STATUS_VOTING_PERIOD",
  "voting_end_time": "2024-01-15T12:00:00Z"
}
```

### Credit Class
```json
{
  "type": "credit_class",
  "class_id": "C01",
  "credit_type": "carbon",
  "metadata": "Verified Carbon Standard"
}
```

### Daily Statistics
```json
{
  "type": "daily_stats",
  "date": "2024-01-10",
  "stats": {
    "total_credits_retired": 1500000,
    "retirement_rate": 0.65,
    "active_proposals": 2,
    "marketplace_orders": 45
  }
}
```

## KOI Integration

The sensor sends structured events to the KOI Event Bridge:

```python
# RID format examples
"governance:proposal:123"
"ecocredit:class:C01"
"ecocredit:batch:C01-20240110"
"marketplace:order:456"
"stats:daily:2024-01-10"
```

## Session 2 Deliverables ✅

- [x] Created `/koi-sensors/sensors/ledger/` directory
- [x] Implemented direct RPC/REST endpoint queries
- [x] Created governance, ecocredit, and consensus query modules
- [x] Built stats aggregation for daily/weekly reports
- [x] Integrated with KOI Event Bridge
- [x] Added query templates for common operations
- [x] Created comprehensive test suite
- [x] Generated sample outputs

## Next Steps

1. Start KOI Event Bridge: `python /path/to/koi_event_bridge_v2.py`
2. Run sensor in production mode for continuous monitoring
3. Configure daily/weekly report generation times
4. Set up alerts for governance proposals or large credit issuances