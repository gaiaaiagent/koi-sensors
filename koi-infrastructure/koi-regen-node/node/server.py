import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.responses import JSONResponse
from koi_net.processor.knowledge_object import KnowledgeSource
from koi_net.protocol.api_models import (
    PollEvents,
    FetchRids,
    FetchManifests,
    FetchBundles,
    EventsPayload,
    RidsPayload,
    ManifestsPayload,
    BundlesPayload
)
from koi_net.protocol.consts import (
    BROADCAST_EVENTS_PATH,
    POLL_EVENTS_PATH,
    FETCH_RIDS_PATH,
    FETCH_MANIFESTS_PATH,
    FETCH_BUNDLES_PATH
)
from .core import node

logger = logging.getLogger(__name__)

# Track server start time for uptime calculation
SERVER_START_TIME = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):    
    node.start()
    # Initialize metrics
    node.metrics = {
        "total_rids": 0,
        "agent_outputs_processed": 0,
        "credit_data_processed": 0,
        "governance_processed": 0,
        "documents_processed": 0,
        "manifests_processed": 0,
        "errors": 0
    }
    yield
    node.stop()

app = FastAPI(
    lifespan=lifespan, 
    title="Regen KOI-net Node",
    description="KOI sensor node for Regen Network - Implements RID tagging for AI agent outputs",
    version="1.0.0"
)

# Main KOI-net protocol router
koi_net_router = APIRouter(
    prefix="/koi-net"
)

@koi_net_router.post(BROADCAST_EVENTS_PATH)
async def broadcast_events(req: EventsPayload):
    logger.info(f"Request to {BROADCAST_EVENTS_PATH}, received {len(req.events)} event(s)")
    for event in req.events:
        node.processor.handle(event=event, source=KnowledgeSource.External)
    
@koi_net_router.post(POLL_EVENTS_PATH)
async def poll_events(req: PollEvents) -> EventsPayload:
    logger.info(f"Request to {POLL_EVENTS_PATH}")
    events = node.network.flush_poll_queue(req.rid)
    return EventsPayload(events=events)

@koi_net_router.post(FETCH_RIDS_PATH)
async def fetch_rids(req: FetchRids) -> RidsPayload:
    return node.network.response_handler.fetch_rids(req)

@koi_net_router.post(FETCH_MANIFESTS_PATH)
async def fetch_manifests(req: FetchManifests) -> ManifestsPayload:
    return node.network.response_handler.fetch_manifests(req)

@koi_net_router.post(FETCH_BUNDLES_PATH)
async def fetch_bundles(req: FetchBundles) -> BundlesPayload:
    return node.network.response_handler.fetch_bundles(req)

# Regen-specific endpoints
regen_router = APIRouter(
    prefix="/regen"
)

@regen_router.get("/health")
async def health_check():
    """
    Health check endpoint required by contract (Milestone 1.1.3)
    Returns node health status and metrics
    """
    uptime_seconds = time.time() - SERVER_START_TIME
    
    health_status = {
        "status": "healthy",
        "node_id": "regen-koi-sensor",
        "namespace": "regen",
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "metrics": node.metrics if hasattr(node, 'metrics') else {},
        "milestone_status": {
            "1.1.3": "KOI sensor node deployed with RID namespace established",
            "1.3.3": f"Progress: {node.metrics.get('total_rids', 0)}/10000 RID-tagged outputs"
        }
    }
    
    return JSONResponse(content=health_status)

@regen_router.get("/stats")
async def get_statistics():
    """
    Get detailed statistics about processed content
    """
    stats = {
        "total_rids_generated": node.metrics.get("total_rids", 0),
        "by_type": {
            "agent_outputs": node.metrics.get("agent_outputs_processed", 0),
            "credit_data": node.metrics.get("credit_data_processed", 0),
            "governance": node.metrics.get("governance_processed", 0),
            "documents": node.metrics.get("documents_processed", 0)
        },
        "manifests_processed": node.metrics.get("manifests_processed", 0),
        "errors": node.metrics.get("errors", 0),
        "uptime_seconds": time.time() - SERVER_START_TIME,
        "node_info": {
            "name": "regen-koi-sensor",
            "type": "FULL",
            "provides_events": [
                "core.memo", "core.analysis", "core.credit", "core.registry",
                "relevant.agent", "relevant.governance", "relevant.notes", "background.readme"
            ],
            "provides_state": [
                "core.credit", "core.registry", "relevant.agent", "relevant.governance"
            ]
        }
    }
    
    return JSONResponse(content=stats)

@regen_router.post("/generate-rid")
async def generate_rid(request: dict):
    """
    Generate a RID for content following Regen's naming convention
    Expects: {"content": str, "object_type": str, "subject": str, "relevance": str}
    """
    from .handlers import generate_regen_rid
    
    content = request.get("content", "")
    object_type = request.get("object_type", "notes")
    subject = request.get("subject", "unnamed")
    relevance = request.get("relevance", "relevant")
    
    rid = generate_regen_rid(content, object_type, subject, relevance)
    
    return JSONResponse(content={
        "rid": rid,
        "format": "[relevance].[type].[subject].vX.Y.Z.hash",
        "components": {
            "relevance": relevance,
            "object_type": object_type,
            "subject": subject,
            "version": "v1.0.0"
        }
    })

@regen_router.get("/ready")
async def readiness_check():
    """
    Kubernetes-style readiness probe
    """
    # Check if node is properly initialized
    if not hasattr(node, 'metrics'):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "Node not initialized"}
        )
    
    return JSONResponse(content={"status": "ready"})

# Include routers
app.include_router(koi_net_router)
app.include_router(regen_router)

# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint with basic information
    """
    return {
        "service": "Regen KOI Sensor Node",
        "description": "KOI sensor node for monitoring and tagging AI agent outputs",
        "endpoints": {
            "health": "/regen/health",
            "stats": "/regen/stats",
            "generate_rid": "/regen/generate-rid",
            "koi_protocol": "/koi-net/*"
        },
        "documentation": "/docs",
        "contract_milestone": "1.1.3 - KOI sensor node deployed with RID namespace established"
    }