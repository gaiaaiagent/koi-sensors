# KOI Infrastructure for Regen Network

This directory contains the Knowledge Organization Infrastructure (KOI) implementation for Regen Network.

## Directory Structure

```
koi-infrastructure/
├── koi-regen-node/         # Main KOI sensor node implementation
│   ├── node/               # Node configuration and handlers
│   ├── storage/            # RID-tagged content storage
│   └── integration_bridge.py # Bridge to indexing system
├── naming-convention/      # Regen's KOI naming convention docs
│   └── koi-gov-regen/      # Naming manifesto and rules
├── koi-net/                # BlockScience KOI-net protocol library
└── koi-net-node-template/  # Template for creating new nodes
```

## Quick Start

To run the KOI sensor node:

```bash
cd koi-regen-node
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m node
```

The node will be available at http://localhost:8000

## Key Features

- **RID Generation**: Follows Regen's naming convention `[relevance].[type].[subject].vX.Y.Z`
- **Integration**: Connects with existing document indexing system
- **Health Monitoring**: Provides health checks and statistics endpoints
- **Contract Compliance**: Meets milestones 1.1.3 and 1.3.3 requirements

## Endpoints

- `/regen/health` - Health check with metrics
- `/regen/stats` - Detailed statistics
- `/regen/generate-rid` - RID generation service
- `/koi-net/*` - KOI protocol endpoints

## Documentation

- [Implementation Details](../docs/KOI_IMPLEMENTATION.md)
- [Naming Convention](naming-convention/koi-gov-regen/KOI.regen-naming-convention-manifesto.v1.0.0.md)
- [Integration Guide](koi-regen-node/README.md)