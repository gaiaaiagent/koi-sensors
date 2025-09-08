"""
KOI Protocol - Coordinator Node
Full KOI node implementing complete KOI-net protocol with FastAPI
"""

import asyncio
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import logging
import httpx

from ..nodes.koi_node import KOIFullNode
from ..core.rid_system import RID
from ..core.bundle_system import Bundle, KOIEvent, Manifest
from ..integration.koi_collector_adapter import (
    TwitterKOIAdapter, DiscourseKOIAdapter, 
    NotionKOIAdapter, WebScraperKOIAdapter
)


# FastAPI models for request/response
class EventBroadcastRequest(BaseModel):
    event_type: str
    rid: str
    timestamp: str
    source_node: str
    bundle: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    # Additional fields that sensors may send
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    event_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class EventPollResponse(BaseModel):
    events: List[Dict[str, Any]]
    node_id: str
    timestamp: str


class BundleFetchResponse(BaseModel):
    bundle: Optional[Dict[str, Any]]
    found: bool


class ManifestFetchResponse(BaseModel):
    manifest: Optional[Dict[str, Any]]
    found: bool


class RIDSFetchResponse(BaseModel):
    rids: List[str]
    count: int


class HealthResponse(BaseModel):
    status: str
    node_id: str
    node_name: str
    uptime_seconds: float
    cache_size: int
    event_queue_size: int
    connected_sensors: int


class KOICoordinator:
    """KOI Coordinator - Full Node with sensor management"""
    
    def __init__(self, node_name: str = "regen-coordinator", port: int = 8000):
        self.node_name = node_name
        self.port = port
        self.start_time = datetime.now()
        
        # Initialize KOI full node
        self.koi_node = KOIFullNode(node_name, port)
        
        # Initialize FastAPI app
        self.app = FastAPI(
            title="KOI Coordinator API",
            description="Full KOI node implementing KOI-net protocol",
            version="1.0.0"
        )
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Setup logging
        self.logger = logging.getLogger("koi.coordinator")
        
        # Sensor adapters
        self.sensor_adapters: Dict[str, Any] = {}
        self.sensor_status: Dict[str, Dict[str, Any]] = {}
        
        # Processor bridge URL (for forwarding events)
        self.processor_bridge_url = "http://localhost:8100/process-koi-event"
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for KOI-net protocol"""
        
        @self.app.post("/events/broadcast")
        async def broadcast_event(request: EventBroadcastRequest):
            """Broadcast event to network (KOI-net endpoint)"""
            try:
                # Convert request to KOIEvent
                event_data = request.dict()
                
                # Handle bundle if present, or create one from sensor data
                if event_data.get("bundle"):
                    bundle_data = event_data["bundle"]
                    bundle = Bundle.from_dict(bundle_data)
                    event_data["bundle"] = bundle
                elif "data" in event_data:
                    # Create bundle from sensor data
                    from ..core.bundle_system import Bundle, Manifest
                    
                    # Extract data from the sensor event
                    sensor_data = event_data.pop("data", {})
                    
                    # Create a simple manifest without using RID object
                    # Just create the necessary fields directly
                    import hashlib
                    from datetime import datetime, timezone
                    
                    content_str = json.dumps(sensor_data, sort_keys=True)
                    content_hash = hashlib.sha256(content_str.encode()).hexdigest()
                    
                    manifest = Manifest(
                        rid=event_data["rid"],
                        timestamp=event_data["timestamp"],
                        content_hash=content_hash,
                        size_bytes=len(content_str.encode()),
                        content_type="application/json",
                        version="1.0",
                        metadata=sensor_data.get("metadata", {})
                    )
                    
                    # Create bundle with the sensor content
                    bundle = Bundle(
                        rid=event_data["rid"],
                        cid="",  # Will be generated
                        content=sensor_data,
                        manifest=manifest
                    )
                    event_data["bundle"] = bundle
                    
                    # Clean up extra fields not needed by KOIEvent
                    event_data.pop("node_id", None)
                    event_data.pop("node_type", None)
                
                event = KOIEvent.from_dict(event_data)
                
                # Process event through KOI node
                await self.koi_node.handle_event(event)
                await self.koi_node.broadcast_event(event)
                
                # Forward to processor bridge
                await self._forward_to_processor(event)
                
                self.logger.info(f"Broadcast {event.event_type} event for {event.rid}")
                
                return {"status": "success", "event_id": event.rid}
                
            except Exception as e:
                self.logger.error(f"Error broadcasting event: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/events/poll", response_model=EventPollResponse)
        async def poll_events(
            node_id: str = Query(..., description="ID of polling node"),
            max_events: int = Query(50, description="Maximum events to return")
        ):
            """Poll for new events (KOI-net endpoint)"""
            try:
                # Get queued events
                events = self.koi_node.get_queued_events(max_events)
                
                # Convert events to dict format
                event_dicts = [event.to_dict() for event in events]
                
                # Clear processed events
                self.koi_node.clear_event_queue(len(events))
                
                # Add node as subscriber
                self.koi_node.add_event_subscriber(node_id)
                
                return EventPollResponse(
                    events=event_dicts,
                    node_id=self.koi_node.node_id,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                
            except Exception as e:
                self.logger.error(f"Error polling events: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/bundles/fetch/{rid}", response_model=BundleFetchResponse)
        async def fetch_bundle(rid: str):
            """Fetch bundle by RID (KOI-net endpoint)"""
            try:
                bundle = self.koi_node.get_cached_bundle(rid)
                
                return BundleFetchResponse(
                    bundle=bundle.to_dict() if bundle else None,
                    found=bundle is not None
                )
                
            except Exception as e:
                self.logger.error(f"Error fetching bundle {rid}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/manifests/fetch/{rid}", response_model=ManifestFetchResponse)
        async def fetch_manifest(rid: str):
            """Fetch manifest by RID (KOI-net endpoint)"""
            try:
                bundle = self.koi_node.get_cached_bundle(rid)
                manifest = bundle.manifest if bundle else None
                
                return ManifestFetchResponse(
                    manifest=manifest.to_dict() if manifest else None,
                    found=manifest is not None
                )
                
            except Exception as e:
                self.logger.error(f"Error fetching manifest {rid}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/rids/fetch", response_model=RIDSFetchResponse)
        async def fetch_rids():
            """Fetch list of available RIDs (KOI-net endpoint)"""
            try:
                rids = self.koi_node.get_cached_rids()
                
                return RIDSFetchResponse(
                    rids=rids,
                    count=len(rids)
                )
                
            except Exception as e:
                self.logger.error(f"Error fetching RIDs: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/health", response_model=HealthResponse)
        async def health_check():
            """Health check endpoint (KOI-net endpoint)"""
            uptime = (datetime.now() - self.start_time).total_seconds()
            
            return HealthResponse(
                status="healthy" if self.koi_node.running else "stopped",
                node_id=self.koi_node.node_id,
                node_name=self.node_name,
                uptime_seconds=uptime,
                cache_size=len(self.koi_node.cache),
                event_queue_size=len(self.koi_node.event_queue),
                connected_sensors=len(self.sensor_adapters)
            )
        
        # Additional management endpoints
        @self.app.get("/sensors/status")
        async def get_sensor_status():
            """Get status of all sensor adapters"""
            status = {}
            for sensor_name, adapter in self.sensor_adapters.items():
                status[sensor_name] = adapter.get_metrics()
            return status
        
        @self.app.post("/sensors/start/{sensor_type}")
        async def start_sensor(sensor_type: str):
            """Start a sensor adapter"""
            try:
                if sensor_type in self.sensor_adapters:
                    return {"status": "already_running", "sensor": sensor_type}
                
                # Create adapter based on type
                adapter_classes = {
                    "twitter": TwitterKOIAdapter,
                    "discourse": DiscourseKOIAdapter,
                    "notion": NotionKOIAdapter,
                    "web": WebScraperKOIAdapter
                }
                
                adapter_class = adapter_classes.get(sensor_type)
                if not adapter_class:
                    raise HTTPException(status_code=400, detail=f"Unknown sensor type: {sensor_type}")
                
                # Create and start adapter
                adapter = adapter_class(f"http://localhost:{self.port}")
                await adapter.start_koi_collection()
                
                self.sensor_adapters[sensor_type] = adapter
                self.logger.info(f"Started {sensor_type} sensor adapter")
                
                return {"status": "started", "sensor": sensor_type}
                
            except Exception as e:
                self.logger.error(f"Error starting sensor {sensor_type}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/sensors/stop/{sensor_type}")
        async def stop_sensor(sensor_type: str):
            """Stop a sensor adapter"""
            try:
                adapter = self.sensor_adapters.get(sensor_type)
                if not adapter:
                    raise HTTPException(status_code=404, detail=f"Sensor not found: {sensor_type}")
                
                await adapter.stop_koi_collection()
                del self.sensor_adapters[sensor_type]
                
                self.logger.info(f"Stopped {sensor_type} sensor adapter")
                
                return {"status": "stopped", "sensor": sensor_type}
                
            except Exception as e:
                self.logger.error(f"Error stopping sensor {sensor_type}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    
    async def _forward_to_processor(self, event: KOIEvent):
        """Forward KOI event to processor bridge"""
        try:
            # Convert event to format expected by processor
            event_data = {
                "event_type": event.event_type,
                "bundle": {
                    "rid": event.rid,
                    "cid": event.bundle.cid if event.bundle else "",
                    "content": event.bundle.content if event.bundle else {},
                    "metadata": event.bundle.manifest.metadata if event.bundle and event.bundle.manifest else {},
                    "manifest": event.bundle.manifest.to_dict() if event.bundle and event.bundle.manifest else {}
                },
                "timestamp": event.timestamp or datetime.now(timezone.utc).isoformat(),
                "source_sensor": event.source_node or self.node_name
            }
            
            # Send to processor bridge
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.processor_bridge_url,
                    json=event_data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self.logger.info(f"Event forwarded to processor: {result.get('chunks_created', 0)} chunks, {result.get('embeddings_created', 0)} embeddings")
                else:
                    self.logger.warning(f"Processor bridge returned {response.status_code}: {response.text}")
                    
        except Exception as e:
            # Log but don't fail - processor is optional
            self.logger.warning(f"Could not forward to processor: {e}")
    
    async def start(self):
        """Start the coordinator"""
        self.logger.info(f"Starting KOI Coordinator on port {self.port}")
        
        # Start KOI node
        await self.koi_node.start()
        
        # Start web server
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    async def stop(self):
        """Stop the coordinator"""
        self.logger.info("Stopping KOI Coordinator")
        
        # Stop all sensor adapters
        for sensor_type in list(self.sensor_adapters.keys()):
            try:
                await self.sensor_adapters[sensor_type].stop_koi_collection()
                del self.sensor_adapters[sensor_type]
            except Exception as e:
                self.logger.error(f"Error stopping sensor {sensor_type}: {e}")
        
        # Stop KOI node
        await self.koi_node.stop()


# Main entry point
async def main():
    """Run KOI coordinator"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Get port from environment or use default
    port = int(os.environ.get('KOI_COORDINATOR_PORT', '8000'))
    
    # Create and start coordinator
    coordinator = KOICoordinator(port=port)
    
    try:
        await coordinator.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await coordinator.stop()


if __name__ == "__main__":
    asyncio.run(main())