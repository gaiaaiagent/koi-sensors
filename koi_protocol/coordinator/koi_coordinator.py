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
        
        # Track broadcast sensors (external sensors that send events)
        self.broadcast_sensors: Dict[str, Dict[str, Any]] = {}  # node_id -> sensor info
        
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
                self.logger.debug(f"Received event data keys: {event_data.keys()}")
                self.logger.debug(f"Event type: {event_data.get('event_type')}")
                
                # Handle bundle if present, or create one from sensor data
                if event_data.get("bundle"):
                    bundle_data = event_data["bundle"]
                    self.logger.debug(f"Bundle data keys: {bundle_data.keys() if isinstance(bundle_data, dict) else 'not a dict'}")
                    # Keep bundle as dictionary for KOIEvent.from_dict()
                    # It will be converted to Bundle object inside KOIEvent.from_dict()
                    if not isinstance(bundle_data, dict):
                        self.logger.error(f"Bundle data is not a dictionary: {type(bundle_data)}")
                        raise ValueError("Bundle must be a dictionary")
                elif "data" in event_data:
                    self.logger.debug(f"Creating bundle from sensor data")
                    # Create bundle from sensor data
                    from ..core.bundle_system import Bundle, Manifest
                    
                    # Extract data from the sensor event
                    sensor_data = event_data.pop("data", {})
                    
                    # Create a simple manifest without using RID object
                    # Just create the necessary fields directly
                    import hashlib
                    
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
                    self.logger.debug(f"Creating Bundle with rid={event_data['rid']}")
                    bundle = Bundle(
                        rid=event_data["rid"],
                        manifest=manifest,
                        contents=sensor_data
                    )
                    self.logger.debug(f"Bundle created successfully, type: {type(bundle)}")
                    # Convert Bundle to dictionary for KOIEvent.from_dict()
                    event_data["bundle"] = bundle.to_dict()
                    
                    # Clean up extra fields not needed by KOIEvent
                    event_data.pop("node_id", None)
                    event_data.pop("node_type", None)
                    event_data.pop("event_id", None)
                    event_data.pop("data", None)
                
                self.logger.debug(f"Creating KOIEvent from data")
                event = KOIEvent.from_dict(event_data)
                self.logger.debug(f"KOIEvent created: type={type(event)}, has_bundle={event.bundle is not None}")
                
                # Track the broadcast sensor
                if "source_node" in event_data:
                    source_node = event_data["source_node"]
                    self.broadcast_sensors[source_node] = {
                        "node_id": source_node,
                        "last_event": datetime.now(timezone.utc).isoformat(),
                        "event_count": self.broadcast_sensors.get(source_node, {}).get("event_count", 0) + 1,
                        "event_type": event_data.get("event_type", "unknown")
                    }
                    self.logger.debug(f"Tracked broadcast sensor: {source_node}")
                
                # Process event through KOI node
                await self.koi_node.handle_event(event)
                await self.koi_node.broadcast_event(event)
                
                # Forward to processor bridge
                self.logger.debug(f"Forwarding event to processor bridge")
                await self._forward_to_processor(event)
                
                self.logger.info(f"Broadcast {event.event_type} event for {event.rid}")
                
                return {"status": "success", "event_id": event.rid}
                
            except Exception as e:
                import traceback
                self.logger.error(f"Error broadcasting event: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")
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
                connected_sensors=len(self.sensor_adapters) + len(self.broadcast_sensors)
            )
        
        # Additional management endpoints
        @self.app.get("/sensors/status")
        async def get_sensor_status():
            """Get status of all sensor adapters"""
            status = {
                "managed_sensors": {},
                "broadcast_sensors": self.broadcast_sensors
            }
            for sensor_name, adapter in self.sensor_adapters.items():
                status["managed_sensors"][sensor_name] = adapter.get_metrics()
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
                    "cid": "",  # Bundle doesn't have cid attribute
                    "content": event.bundle.contents if event.bundle else {},
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
    import argparse
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='KOI Coordinator')
    parser.add_argument('--port', type=int, default=8200, help='Port to run on')
    args = parser.parse_args()
    
    # Get port from command line or environment
    port = args.port if args.port else int(os.environ.get('KOI_COORDINATOR_PORT', '8200'))
    
    # Create and start coordinator
    coordinator = KOICoordinator(port=port)
    
    try:
        await coordinator.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await coordinator.stop()


if __name__ == "__main__":
    asyncio.run(main())