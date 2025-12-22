# KOI Sensors Integration Guide

Complete technical guide for integrating the KOI sensor network with the processing pipeline and Apache Jena triplestore.

## Overview

The KOI sensor network is **Phase 1 Complete** of the 3-repository architecture. This guide explains how to integrate it with the processing pipeline (koi-processor) and Apache Jena backend.

## Current Architecture Status

### ✅ **Phase 1: Sensor Network (COMPLETE)**
```
📡 koi-sensors (THIS REPO)
├── KOI Coordinator (Full Node) - Port 8000
│   ├── POST /events/broadcast - Receive events from sensors
│   ├── POST /events/poll - Distribute events to processors (KOI-net compliant)
│   ├── POST /bundles/fetch - Retrieve cached bundles
│   ├── POST /manifests/fetch - Retrieve manifests
│   ├── POST /rids/fetch - List available RIDs
│   └── GET /health - Node status
├── Sensor Adapters (Partial Nodes)
│   ├── TwitterKOIAdapter - Wraps existing Twitter collector
│   ├── DiscourseKOIAdapter - Wraps existing Discourse collector
│   ├── NotionKOIAdapter - Wraps existing Notion collector
│   └── WebScraperKOIAdapter - Wraps existing web scraper
└── Event System
    ├── NEW events - Previously unknown content
    ├── UPDATE events - Content changed
    └── FORGET events - Content removed
```

### 🔄 **Phase 2: Integration Layer (REQUIRED)**
```
🔄 koi-processor
├── /process-koi-event (NEW ENDPOINT NEEDED)
├── bundle_to_document() (CONVERSION NEEDED)  
├── Apache Jena integration (REPLACES Neo4j)
└── Existing processing pipeline (PRESERVED)
```

### 📋 **Phase 3: Apache Jena Backend (REQUIRED)**
```
🗄️ Apache Jena Fuseki - Port 3030
├── /koi/sparql - SPARQL endpoint
├── /koi/data - Data upload endpoint
└── regen-unified-ontology.ttl (LOADED)
```

## Integration Implementation

### Step 1: Add KOI Event Endpoint to Processor

Add this endpoint to your existing processor (likely in `koi-processor/main.py` or similar):

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

# KOI Event data structures
class KOIManifest(BaseModel):
    rid: str
    timestamp: str
    content_hash: str
    size_bytes: int
    content_type: str
    version: str = "1.0"
    metadata: Optional[Dict[str, Any]] = None

class KOIBundle(BaseModel):
    rid: str
    manifest: KOIManifest
    contents: Any

class KOIEventRequest(BaseModel):
    event_type: str  # "NEW", "UPDATE", "FORGET"
    rid: str
    timestamp: str
    source_node: str
    bundle: Optional[KOIBundle] = None
    reason: Optional[str] = None

# Add to existing FastAPI app
@app.post("/process-koi-event")
async def process_koi_event(event: KOIEventRequest):
    """Process KOI event from sensor coordinator"""
    
    try:
        logger.info(f"Processing {event.event_type} event for {event.rid}")
        
        if event.event_type == "FORGET":
            # Handle content removal
            await handle_forget_event(event.rid, event.reason)
            return {"status": "success", "action": "forgotten"}
        
        if not event.bundle:
            raise HTTPException(status_code=400, detail="Bundle required for NEW/UPDATE events")
        
        # Convert KOI Bundle to existing Document format
        document = bundle_to_document(event.bundle)
        
        # Process through existing unified ontology pipeline
        processed_result = await process_document_with_unified_ontology(document)
        
        # Store in Apache Jena (instead of Neo4j/Graphiti)
        await store_in_jena_triplestore(processed_result, event.event_type)
        
        return {
            "status": "success", 
            "action": "processed",
            "rid": event.rid,
            "entities_extracted": len(processed_result.get("entities", [])),
            "stored_in": "apache_jena"
        }
        
    except Exception as e:
        logger.error(f"Error processing KOI event {event.rid}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def bundle_to_document(bundle: KOIBundle) -> Dict[str, Any]:
    """Convert KOI Bundle to existing Document format"""
    
    contents = bundle.contents
    
    # Extract document data from bundle contents
    doc_data = contents.get("document", {})
    metadata = contents.get("metadata", {})
    processing = contents.get("processing", {})
    
    # Convert to existing Document format
    document = {
        "id": doc_data.get("id") or bundle.rid.replace(":", "_"),
        "source": doc_data.get("source", "koi-sensor"),
        "source_type": doc_data.get("source_type", "unknown"),
        "url": doc_data.get("url", ""),
        "title": doc_data.get("title", ""),
        "content": doc_data.get("content", ""),
        "metadata": {
            **metadata,
            "koi_rid": bundle.rid,
            "koi_manifest": bundle.manifest.dict(),
            "processed_via_koi": True,
            "source_node": processing.get("source_node")
        },
        "collected_at": doc_data.get("collected_at"),
        "last_modified": doc_data.get("last_modified"),
        "author": doc_data.get("author"),
        "tags": doc_data.get("tags", [])
    }
    
    return document


async def store_in_jena_triplestore(processed_result: Dict[str, Any], event_type: str):
    """Store processed result in Apache Jena instead of Neo4j"""
    
    # Generate RDF triples from processed result
    rdf_triples = generate_rdf_triples(processed_result)
    
    # Send to Jena Fuseki
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3030/koi/data",
            headers={"Content-Type": "text/turtle"},
            data=rdf_triples
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to store in Jena: {response.status_code}")
    
    logger.info(f"Stored {event_type} data in Apache Jena for {processed_result.get('id')}")


def generate_rdf_triples(processed_result: Dict[str, Any]) -> str:
    """Generate RDF triples from processed document result"""
    
    document_uri = f"<orn:regen.document:{processed_result['id']}>"
    
    triples = []
    triples.append(f"{document_uri} a regen:Document .")
    triples.append(f"{document_uri} regen:hasContent \"{escape_literal(processed_result['content'])}\" .")
    triples.append(f"{document_uri} regen:hasSource \"{processed_result['source']}\" .")
    
    # Add entity triples
    for entity in processed_result.get("entities", []):
        entity_uri = f"<orn:regen.entity:{entity['id']}>"
        triples.append(f"{entity_uri} a regen:{entity['type']} .")
        triples.append(f"{entity_uri} regen:hasLabel \"{escape_literal(entity['label'])}\" .")
        triples.append(f"{document_uri} regen:containsEntity {entity_uri} .")
        
        # Add essence alignment triples
        if entity.get("essence_alignment"):
            for essence, score in entity["essence_alignment"].items():
                triples.append(f"{entity_uri} regen:hasEssenceAlignment regen:{essence.replace(' ', '')} .")
                triples.append(f"{entity_uri} regen:essenceScore_{essence.replace(' ', '')} \"{score}\"^^xsd:double .")
    
    # Combine with ontology prefixes
    prefixes = '''
@prefix regen: <https://regen.network/ontology#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix koi: <https://koi.network/ontology#> .

'''
    
    return prefixes + "\\n".join(triples)


def escape_literal(text: str) -> str:
    """Escape string for RDF literal"""
    return text.replace('\\', '\\\\').replace('"', '\\"').replace('\\n', '\\\\n')


async def handle_forget_event(rid: str, reason: str = None):
    """Handle FORGET event - remove data from Jena"""
    
    # SPARQL DELETE query
    delete_query = f"""
    PREFIX regen: <https://regen.network/ontology#>
    
    DELETE WHERE {{
        <{rid}> ?p ?o .
        ?s ?p2 <{rid}> .
    }}
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3030/koi/update",
            headers={"Content-Type": "application/sparql-update"},
            data=delete_query
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to delete from Jena: {response.status_code}")
    
    logger.info(f"Removed {rid} from Apache Jena (reason: {reason})")
```

### Step 2: Update Coordinator to Route Events

Add processor integration to the KOI Coordinator:

```python
# In koi_protocol/coordinator/koi_coordinator.py

class KOICoordinator:
    def __init__(self, node_name: str = "regen-coordinator", port: int = 8000, 
                 processor_url: str = "http://localhost:8100"):
        # ... existing init code ...
        self.processor_url = processor_url
    
    async def route_to_processor(self, event: KOIEvent):
        """Route KOI event to processor for processing"""
        
        try:
            async with self.session.post(
                f"{self.processor_url}/process-koi-event",
                json=event.to_dict(),
                timeout=30
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info(f"Processor handled {event.event_type} event for {event.rid}")
                    return result
                else:
                    self.logger.error(f"Processor error {response.status} for {event.rid}")
                    
        except Exception as e:
            self.logger.error(f"Error routing to processor: {e}")
    
    # Update the broadcast_event handler to route to processor
    @app.post("/events/broadcast")
    async def broadcast_event(request: EventBroadcastRequest):
        """Broadcast event to network and route to processor"""
        try:
            # ... existing event handling code ...
            
            # Route to processor for processing
            await self.route_to_processor(event)
            
            # Process event through KOI node
            await self.koi_node.handle_event(event)
            await self.koi_node.broadcast_event(event)
            
            return {"status": "success", "event_id": event.rid}
            
        except Exception as e:
            # ... existing error handling ...
```

### Step 3: Deploy Apache Jena Fuseki

Replace Neo4j/Graphiti with Apache Jena:

```bash
# Stop Neo4j if running
docker stop neo4j

# Start Apache Jena Fuseki
docker run -d --name jena-fuseki \\
  -p 3030:3030 \\
  -v $(pwd)/jena-data:/fuseki \\
  -e ADMIN_PASSWORD=koi-regen \\
  stain/jena-fuseki

# Wait for startup
sleep 10

# Create KOI dataset
curl -X POST http://localhost:3030/$/datasets \\
  -H "Content-Type: application/x-www-form-urlencoded" \\
  -d "dbName=koi&dbType=tdb2"

# Load unified ontology
curl -X POST http://localhost:3030/koi/data \\
  -H "Content-Type: text/turtle" \\
  --data-binary @../koi-research/ontologies/regen-unified-ontology.ttl

echo "Apache Jena Fuseki deployed successfully!"
echo "SPARQL endpoint: http://localhost:3030/koi/sparql"
echo "Admin interface: http://localhost:3030"
```

### Step 4: Test End-to-End Integration

Test the complete pipeline:

```bash
# 1. Start all services
docker-compose up -d  # Start sensors and coordinator

# Start processor with KOI integration
cd ../koi-processor
python main.py  # Should now have /process-koi-event endpoint

# Start Apache Jena
# (from step 3 above)

# 2. Test sensor event flow
curl -X POST http://localhost:8000/sensors/start/twitter

# 3. Monitor processing
curl http://localhost:8000/sensors/status
curl http://localhost:8100/health  # Processor health
curl http://localhost:3030/$/stats  # Jena statistics

# 4. Query processed data
curl -X POST http://localhost:3030/koi/sparql \\
  -H "Content-Type: application/sparql-query" \\
  -d "SELECT ?doc ?entity WHERE { ?doc regen:containsEntity ?entity } LIMIT 10"
```

## Event Flow Verification

The complete event flow should be:

1. **Sensor detects content** → Creates RID and Bundle
2. **Sensor emits KOI event** → Coordinator receives via `/events/broadcast`
3. **Coordinator routes to processor** → `/process-koi-event` endpoint
4. **Processor converts Bundle** → Existing Document format
5. **Processor extracts entities** → Using unified ontology (existing pipeline)
6. **Processor stores in Jena** → RDF triples via `/koi/data`
7. **Agents query via SPARQL** → `/koi/sparql` endpoint

## Troubleshooting

### Common Issues

**Coordinator can't reach processor:**
```bash
# Check processor is running
curl http://localhost:8100/health

# Check coordinator logs
docker logs koi-coordinator
```

**Apache Jena connection fails:**
```bash
# Check Jena is running
curl http://localhost:3030/$/ping

# Check dataset exists
curl http://localhost:3030/$/datasets
```

**Sensor events not processing:**
```bash
# Check sensor adapter logs
curl http://localhost:8000/sensors/status

# Manually trigger collection
curl -X POST http://localhost:8000/sensors/start/twitter
```

### Performance Monitoring

```bash
# Monitor event queue size
curl http://localhost:8000/health | jq '.event_queue_size'

# Monitor Jena triple count  
curl -X POST http://localhost:3030/koi/sparql \\
  -H "Content-Type: application/sparql-query" \\
  -d "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"

# Monitor processing rate
curl http://localhost:8100/metrics  # If metrics endpoint exists
```

## Production Deployment

For deployment to your server (202.61.196.119):

1. **Copy sensor network** to `/home/regenai/project/koi-sensors/`
2. **Update processor** with KOI integration endpoints  
3. **Deploy Apache Jena** replacing Neo4j references
4. **Configure service mesh** with proper networking
5. **Set up monitoring** with existing Grafana/Prometheus

The integration preserves all your existing successful collection methods while adding full KOI protocol compliance and real-time event streaming capabilities.