# KOI Protocol Compliance Implementation

## KOI-net Protocol Requirements

### Node Types
- **Full Nodes**: Web servers implementing complete KOI-net protocol with all endpoints
- **Partial Nodes**: Web clients that poll for events and call other node endpoints

### Required Endpoints (Full Nodes)
- `POST /events/broadcast` - Broadcast events to network
- `POST /events/poll` - Poll for new events (KOI-net compliant; GET supported for legacy)
- `POST /bundles/fetch` - Fetch bundle by RID
- `POST /manifests/fetch` - Fetch manifest by RID
- `POST /rids/fetch` - List available RIDs
- `GET /health` - Health check

### Event System (FUN Events)
- **NEW**: Previously unknown RID was cached
- **UPDATE**: Previously known RID was updated
- **FORGET**: Previously known RID was deleted

### Data Structures
- **RID**: Resource Identifier (`<context>:<reference>`)
- **Bundle**: Content + Manifest + Metadata
- **Manifest**: Timestamp + SHA-256 hash + metadata
- **Event**: Type + RID + optional Bundle

## Implementation Strategy

### Phase 1: KOI Protocol Core
1. Implement KOI-net protocol handlers
2. Create RID management system
3. Build Bundle and Manifest structures
4. Implement FUN event system

### Phase 2: Sensor Node Integration
1. Convert existing collectors to KOI sensor nodes
2. Maintain existing data collection methods
3. Add KOI event emission layer
4. Implement coordinator node

### Phase 3: Network Formation
1. Deploy coordinator as Full Node
2. Deploy sensors as Partial Nodes
3. Establish event polling and broadcasting
4. Integrate with existing MCP server

## File Organization
```
koi_protocol/
├── core/               # Core KOI protocol implementation
├── nodes/              # Node implementations (Full/Partial)
├── sensors/            # Sensor-specific implementations
├── coordinator/        # Coordinator node implementation
└── integration/        # Integration with existing collectors
```