"""
KOI Protocol - Coordinator Node
Full KOI node implementing complete KOI-net protocol with FastAPI
"""

import asyncio
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
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


class DeliveryConfirmationRequest(BaseModel):
    node_id: str
    event_ids: List[str]
    timestamp: str


class EventPollResponse(BaseModel):
    events: List[Dict[str, Any]]
    event_ids: List[str]  # IDs of the events for delivery confirmation
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


class DeliveryConfirmationResponse(BaseModel):
    confirmed_count: int
    node_id: str
    timestamp: str


class HealthResponse(BaseModel):
    status: str
    node_id: str
    node_name: str
    uptime_seconds: float
    cache_size: int
    event_queue_size: int
    connected_sensors: int
    delivery_stats: Optional[Dict[str, Any]] = None


class KOICoordinator:
    """KOI Coordinator - Full Node with sensor management"""
    
    def __init__(self, node_name: str = "regen-coordinator", port: int = 8000):
        self.node_name = node_name
        self.port = port
        self.start_time = datetime.now()

        # Initialize KOI full node
        self.koi_node = KOIFullNode(node_name, port)

        # Store sensor monitoring data
        self.sensor_monitoring = {}
        
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
        # Use sensor type as key to avoid duplicates when sensors reconnect
        self.broadcast_sensors: Dict[str, Dict[str, Any]] = {}  # sensor_type -> sensor info
        self.sensor_timeout_seconds = 3600  # Mark sensors inactive after 1 hour (increased from 5 minutes)

        # Processor bridge URL (for forwarding events)
        self.processor_bridge_url = "http://localhost:8100/process-koi-event"

        # Content deduplication tracking
        # Maps RID -> content_hash to detect duplicate content
        self.content_hashes: Dict[str, str] = {}  # RID -> content_hash
        # For web pages, also track by URL since RID can vary
        self.url_hashes: Dict[str, str] = {}  # URL -> content_hash

        # Persistent state file for deduplication (survives restarts)
        self.dedup_state_file = Path(__file__).parent / "coordinator_dedup_state.json"
        self._load_dedup_state()

        # Sensor registry persistence
        self.sensor_registry_file = Path(__file__).parent / "coordinator_sensor_registry.json"
        self._load_sensor_registry()

        # Health monitoring
        self.health_check_interval = 300  # 5 minutes
        self.health_check_task = None

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

                # Check if this is a sensor heartbeat with monitoring data
                if event_data and event_data.get("data") and event_data.get("data", {}).get("type") == "sensor_heartbeat":
                    heartbeat_data = event_data.get("data", {})
                    sensor_id = heartbeat_data.get("sensor_id")
                    monitoring_list = heartbeat_data.get("monitoring", [])

                    if sensor_id and monitoring_list:
                        self.sensor_monitoring[sensor_id] = monitoring_list
                        self.logger.info(f"Updated monitoring data for {sensor_id}: {len(monitoring_list)} items")
                        # Show first few items for debugging
                        if len(monitoring_list) > 0:
                            self.logger.debug(f"First monitoring item: {monitoring_list[0]}")
                
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
                    
                    # Extract sensor type from node_id (e.g., "website-sensor-12345" -> "website-sensor")
                    # Handle multi-word sensors like "github-activity-sensor"
                    import re
                    sensor_type_match = re.match(r'^(.*?-sensor)', source_node)
                    if sensor_type_match:
                        sensor_type = sensor_type_match.group(1)
                    else:
                        # Fallback for sensors without standard naming
                        sensor_type = source_node.split('-')[0] if '-' in source_node else source_node
                    
                    # Update or create sensor entry using type as key
                    current_time = datetime.now(timezone.utc)
                    if sensor_type in self.broadcast_sensors:
                        # Update existing sensor
                        self.broadcast_sensors[sensor_type]["node_id"] = source_node  # Update to latest node_id
                        self.broadcast_sensors[sensor_type]["last_event"] = current_time.isoformat()
                        self.broadcast_sensors[sensor_type]["event_count"] += 1
                        self.broadcast_sensors[sensor_type]["status"] = "active"  # Mark as active when we receive events
                        self.logger.debug(f"Updated existing sensor: {sensor_type} (node: {source_node})")
                    else:
                        # New sensor type
                        self.broadcast_sensors[sensor_type] = {
                            "node_id": source_node,
                            "sensor_type": sensor_type,
                            "last_event": current_time.isoformat(),
                            "event_count": 1,
                            "event_type": event_data.get("event_type", "unknown"),
                            "status": "active"  # New sensors start as active
                        }
                        self.logger.debug(f"Tracked new sensor: {sensor_type} (node: {source_node})")
                        # Save registry when new sensor appears
                        self._save_sensor_registry()

                # Check for duplicate content before processing
                if event.bundle and event.rid:
                    content_hash = event.bundle.manifest.content_hash if event.bundle else ""
                    metadata = event.bundle.manifest.metadata if event.bundle else {}
                    source_url = metadata.get("url") or metadata.get("source_url")

                    # Check if this is duplicate content
                    is_duplicate = False if "podcast" in event.rid else self._check_duplicate_content(event.rid, content_hash, source_url)

                    if is_duplicate:
                        self.logger.info(f"Skipping duplicate content for RID {event.rid} (hash: {content_hash[:8]}...)")
                        return {"status": "skipped_duplicate", "event_id": event.rid, "reason": "duplicate_content"}

                # Create CAT receipt for sensor collection (only for new/changed content)
                try:
                    # Import the receipt manager
                    import sys
                    import os
                    sys.path.append(os.path.join(os.path.dirname(__file__), '../../../koi-processor/src'))
                    from cat.coordinator_receipt_integration import CoordinatorReceiptManager

                    receipt_manager = CoordinatorReceiptManager()

                    # Create sensor collection receipt
                    if event.bundle and event.rid:
                        sensor_name = event_data.get("source_node", "unknown")
                        content_hash = event.bundle.manifest.content_hash if event.bundle else ""
                        metadata = event.bundle.manifest.metadata if event.bundle else {}

                        collection_receipt = await receipt_manager.create_sensor_collection_receipt(
                            sensor_name=sensor_name,
                            rid=event.rid,
                            content_hash=content_hash,
                            source_url=metadata.get("url"),
                            document_count=1,
                            metadata=metadata
                        )

                        # Create forwarding receipt
                        forwarding_receipt = await receipt_manager.create_coordinator_forwarding_receipt(
                            input_rid=event.rid,
                            output_rid=event.rid,
                            target_service="event-bridge",
                            sensor_name=sensor_name,
                            event_type=event.event_type,
                            metadata={"collection_receipt": collection_receipt}
                        )

                        self.logger.info(f"Created CAT receipts - collection: {collection_receipt}, forwarding: {forwarding_receipt}")

                    await receipt_manager.close()

                except Exception as e:
                    self.logger.warning(f"Could not create CAT receipts: {e}")
                    # Don't fail the event processing if receipt creation fails

                # Process event through KOI node
                await self.koi_node.handle_event(event)

                # CRITICAL: Queue the event for other nodes to poll (KOI protocol requirement)
                self.koi_node.queue_event(event)
                self.logger.info(f"Queued event for polling: {event.rid}")

                # Also broadcast to connected nodes
                await self.koi_node.broadcast_event(event)

                # Note: Processor forwarding is now handled via polling pattern
                # The forwarder polls /events/poll and forwards to semantic bridge
                # await self._forward_to_processor(event)
                
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
                # Get queued events for this specific node (tracks delivery)
                events, event_ids = self.koi_node.get_queued_events_for_delivery(node_id, max_events)

                # Convert events to dict format
                event_dicts = [event.to_dict() for event in events]

                # Log delivery (but don't clear - events only cleared on confirmation)
                if events:
                    self.logger.info(f"Delivering {len(events)} events to {node_id} (IDs: {event_ids[:3]}...)")

                # Add node as subscriber
                self.koi_node.add_event_subscriber(node_id)

                return EventPollResponse(
                    events=event_dicts,
                    event_ids=event_ids,  # Return event IDs for confirmation
                    node_id=self.koi_node.node_id,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            except Exception as e:
                self.logger.error(f"Error polling events: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/events/confirm", response_model=DeliveryConfirmationResponse)
        async def confirm_delivery(
            request: DeliveryConfirmationRequest
        ):
            """Confirm delivery of events by a node (KOI-net endpoint)"""
            try:
                # Confirm delivery of events
                confirmed_count = self.koi_node.confirm_delivery(request.node_id, request.event_ids)

                self.logger.info(f"Node {request.node_id} confirmed {confirmed_count} events")

                return DeliveryConfirmationResponse(
                    confirmed_count=confirmed_count,
                    node_id=self.koi_node.node_id,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

            except Exception as e:
                self.logger.error(f"Error confirming delivery: {e}")
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
                connected_sensors=len(self.sensor_adapters) + len(self.broadcast_sensors),
                delivery_stats=self.koi_node.get_delivery_stats()
            )
        
        # Additional management endpoints
        @self.app.get("/sensors")
        async def get_sensors():
            """Get list of sensors in format expected by dashboard"""
            from datetime import datetime, timezone
            sensors = []
            
            # Add broadcast sensors (filter out inactive ones)
            current_time = datetime.now(timezone.utc)
            for sensor_key, sensor_info in self.broadcast_sensors.items():
                # Check if sensor is still active (has sent events recently)
                last_event_time = datetime.fromisoformat(sensor_info.get("last_event").replace('Z', '+00:00'))
                time_since_last = (current_time - last_event_time).total_seconds()
                
                # Skip inactive sensors (but be generous with timeout - sensors may batch events)
                # Changed from 5 minutes to 1 hour to show sensors that are still running but not actively sending
                if time_since_last > self.sensor_timeout_seconds:
                    continue
                
                node_id = sensor_info.get("node_id", sensor_key)
                
                # Determine sensor type from node_id
                sensor_type = "website"  # Default type
                if "discourse" in node_id.lower():
                    sensor_type = "discourse"
                elif "medium" in node_id.lower():
                    sensor_type = "medium"
                elif "twitter" in node_id.lower():
                    sensor_type = "twitter"
                elif "notion" in node_id.lower():
                    sensor_type = "notion"
                elif "discord" in node_id.lower():
                    sensor_type = "discord"
                elif "github" in node_id.lower():
                    sensor_type = "github"
                elif "gitlab" in node_id.lower():
                    sensor_type = "gitlab"
                elif "telegram" in node_id.lower():
                    sensor_type = "telegram"
                elif "podcast" in node_id.lower():
                    sensor_type = "podcast"
                    
                # Determine what the sensor is monitoring based on type
                monitoring = []
                if sensor_type == "website":
                    # List all websites the sensor is configured to monitor
                    monitoring = [
                        "regen.network",
                        "docs.regen.network", 
                        "guides.regen.network", 
                        "registry.regen.network",
                        "regen.foundation",
                        "researchretreat.org",
                        "desci.com",
                        "regentokenomics.org"
                    ]
                elif sensor_type == "medium":
                    monitoring = ["regen-network.medium.com"]
                elif sensor_type == "discourse":
                    monitoring = ["forum.regen.network", "regencommons.discourse.group"]
                elif sensor_type == "notion":
                    # Check if we have stored monitoring data for this sensor
                    # Try both node_id and simplified sensor type
                    monitoring_found = False
                    if hasattr(self, 'sensor_monitoring'):
                        # Try exact node_id match first
                        if node_id in self.sensor_monitoring:
                            monitoring = self.sensor_monitoring[node_id]
                            monitoring_found = True
                        # Try notion-sensor key
                        elif 'notion-sensor' in self.sensor_monitoring:
                            monitoring = self.sensor_monitoring['notion-sensor']
                            monitoring_found = True
                        # Try any key containing 'notion'
                        else:
                            for key in self.sensor_monitoring:
                                if 'notion' in key.lower():
                                    monitoring = self.sensor_monitoring[key]
                                    monitoring_found = True
                                    break

                    if not monitoring_found:
                        # Default until sensor sends its monitoring data
                        monitoring = ["Notion workspace (loading pages...)"]
                elif sensor_type == "twitter":
                    monitoring = ["@regen_network"]
                elif sensor_type == "github":
                    monitoring = [
                        "regen-network/regen-ledger",
                        "regen-network/regen-js",
                        "regen-network/regen-web",
                        "regen-network/regen-data-standards",
                        "regen-network/groups-ui"
                    ]
                elif sensor_type == "gitlab":
                    monitoring = [
                        "regen-public/regen-whitepapers",
                        "regen-public/regen-public-docs"
                    ]
                elif sensor_type == "telegram":
                    monitoring = ["Telegram channels"]
                elif sensor_type == "podcast":
                    monitoring = ["Planetary Regeneration Podcast"]
                    
                # Clean up the sensor name
                clean_name = node_id
                # Remove timestamp suffixes like -1757815850.574878
                import re
                clean_name = re.sub(r'-\d{10}\.\d+$', '', clean_name)
                clean_name = clean_name.replace("-", " ").title()
                
                sensors.append({
                    "id": node_id,
                    "name": clean_name,
                    "type": sensor_type,
                    "status": "active",
                    "lastActivity": sensor_info.get("last_event"),
                    "eventsProcessed": sensor_info.get("event_count", 0),
                    "monitoring": monitoring
                })
            
            # Add managed sensors if any
            for sensor_name, adapter in self.sensor_adapters.items():
                metrics = adapter.get_metrics()
                sensors.append({
                    "id": f"managed-{sensor_name}",
                    "name": sensor_name.title(),
                    "type": sensor_name,
                    "status": "active" if metrics.get("is_running") else "idle",
                    "lastActivity": datetime.now(timezone.utc).isoformat(),
                    "eventsProcessed": metrics.get("events_processed", 0),
                    "monitoring": metrics.get("monitoring", [])
                })
            
            return {"sensors": sensors}
        
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
            # Convert event to KOI protocol format for processor
            event_data = {
                "event_type": event.event_type,
                "rid": event.rid,
                "source_node": event.source_node or self.node_name,
                "timestamp": event.timestamp or datetime.now(timezone.utc).isoformat(),
                "bundle": {
                    "rid": event.rid,
                    "manifest": event.bundle.manifest.to_dict() if event.bundle and event.bundle.manifest else {},
                    "contents": event.bundle.contents if event.bundle else {}
                } if event.bundle else None,
                "reason": None  # For FORGET events
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
    
    async def _ping_sensors(self, target: Any) -> str:
        """Send ping request to sensors

        Args:
            target: "all" to ping all sensors, or list of sensor types to ping specific ones

        Returns:
            ping_id for tracking responses
        """
        ping_id = str(uuid.uuid4())

        # Prepare ping event
        ping_event = {
            "type": "PING_REQUEST",
            "id": ping_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "coordinator"
        }

        if target == "all":
            ping_event["target"] = "all"
        elif isinstance(target, list):
            # Ping specific sensors
            ping_event["target"] = target
        else:
            ping_event["target"] = str(target)

        # Clear any old responses for this ping_id
        self.ping_responses[ping_id] = {}

        # Broadcast ping event through event broadcast
        try:
            # Create a bundle for the ping request
            ping_bundle = {
                "rid": f"orn:coordinator.ping.{ping_id}",
                "cid": ping_id,
                "content": json.dumps(ping_event),
                "metadata": {"type": "ping_request"},
                "manifest": {
                    "version": "1.0.0",
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
            }

            # Create event for broadcast
            from ..core.bundle_system import KOIEvent
            event = KOIEvent(
                event_type="NEW",
                rid=f"orn:coordinator.ping.{ping_id}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                source_node="coordinator",
                bundle=ping_bundle
            )

            # Broadcast to all connected nodes
            await self.koi_node.broadcast_event(event)
            self.logger.info(f"Sent ping request {ping_id} to {target}")

        except Exception as e:
            self.logger.error(f"Error sending ping request: {e}")

        return ping_id

    def _load_dedup_state(self):
        """Load deduplication state from persistent storage"""
        try:
            if self.dedup_state_file.exists():
                with open(self.dedup_state_file, 'r') as f:
                    state = json.load(f)
                    self.content_hashes = state.get('content_hashes', {})
                    self.url_hashes = state.get('url_hashes', {})
                    self.logger.info(f"Loaded deduplication state: {len(self.content_hashes)} RIDs, {len(self.url_hashes)} URLs")
        except Exception as e:
            self.logger.warning(f"Could not load deduplication state: {e}")
            self.content_hashes = {}
            self.url_hashes = {}

    def _save_dedup_state(self):
        """Save deduplication state to persistent storage"""
        try:
            state = {
                'content_hashes': self.content_hashes,
                'url_hashes': self.url_hashes,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            with open(self.dedup_state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save deduplication state: {e}")

    def _check_duplicate_content(self, rid: str, content_hash: str, url: str = None) -> bool:
        """
        Check if this content has already been processed

        Returns:
            True if duplicate (should skip), False if new/changed (should process)
        """
        # For web pages with URLs, check by URL first (more reliable than RID)
        if url:
            existing_hash = self.url_hashes.get(url)
            if existing_hash == content_hash:
                self.logger.info(f"✓ DUPLICATE: URL {url} (hash: {content_hash[:8]}...) - SKIPPING")
                return True
            elif existing_hash:
                self.logger.info(f"✓ CONTENT CHANGED: URL {url} (old: {existing_hash[:8]}..., new: {content_hash[:8]}...) - PROCESSING")
            else:
                self.logger.info(f"✓ NEW URL: {url} (hash: {content_hash[:8]}...) - PROCESSING")
            # Update the hash for this URL
            self.url_hashes[url] = content_hash
            self._save_dedup_state()
            return False

        # For non-web content, check by RID
        existing_hash = self.content_hashes.get(rid)
        if existing_hash == content_hash:
            self.logger.info(f"✓ DUPLICATE: RID {rid} (hash: {content_hash[:8]}...) - SKIPPING")
            return True
        elif existing_hash:
            self.logger.info(f"✓ CONTENT CHANGED: RID {rid} (old: {existing_hash[:8]}..., new: {content_hash[:8]}...) - PROCESSING")
        else:
            self.logger.info(f"✓ NEW RID: {rid} (hash: {content_hash[:8]}...) - PROCESSING")

        # Update the hash for this RID
        self.content_hashes[rid] = content_hash
        self._save_dedup_state()
        return False

    def _load_sensor_registry(self):
        """Load sensor registry from disk"""
        if self.sensor_registry_file.exists():
            try:
                with open(self.sensor_registry_file, 'r') as f:
                    data = json.load(f)
                    self.broadcast_sensors = data.get('sensors', {})
                    self.logger.info(f"Loaded {len(self.broadcast_sensors)} sensors from registry")
            except Exception as e:
                self.logger.error(f"Error loading sensor registry: {e}")

    def _save_sensor_registry(self):
        """Save sensor registry to disk"""
        try:
            with open(self.sensor_registry_file, 'w') as f:
                json.dump({'sensors': self.broadcast_sensors}, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving sensor registry: {e}")

    async def check_sensor_health(self, sensor_key: str, sensor_info: Dict) -> str:
        """
        Check health of a sensor by seeing if it responds to polls.
        Returns: 'active', 'idle', or 'offline'
        """
        try:
            node_id = sensor_info.get('node_id')
            if not node_id:
                return 'offline'

            # Check time since last event
            last_event_str = sensor_info.get('last_event')
            if last_event_str:
                last_event = datetime.fromisoformat(last_event_str)
                time_since_event = (datetime.now(timezone.utc) - last_event).total_seconds()

                # If we've heard from sensor recently (< 10 minutes), it's active
                if time_since_event < 600:
                    return 'active'
                # If heard within 30 minutes but not recently, it's idle
                elif time_since_event < 1800:
                    return 'idle'

            # If no recent events, mark as offline
            return 'offline'

        except Exception as e:
            self.logger.error(f"Error checking health for {sensor_key}: {e}")
            return 'offline'

    async def periodic_health_checks(self):
        """Periodically check health of all registered sensors"""
        self.logger.info(f"Starting periodic health checks (interval: {self.health_check_interval}s)")

        while True:
            try:
                await asyncio.sleep(self.health_check_interval)

                self.logger.info("Running health check on all sensors...")
                sensors_checked = 0
                sensors_active = 0
                sensors_offline = 0

                for sensor_key, sensor_info in list(self.broadcast_sensors.items()):
                    status = await self.check_sensor_health(sensor_key, sensor_info)
                    old_status = sensor_info.get('status', 'unknown')

                    # Update status if changed
                    if status != old_status:
                        sensor_info['status'] = status
                        self.logger.info(f"Sensor {sensor_key} status changed: {old_status} → {status}")

                    sensors_checked += 1
                    if status == 'active':
                        sensors_active += 1
                    elif status == 'offline':
                        sensors_offline += 1

                self.logger.info(f"Health check complete: {sensors_checked} sensors ({sensors_active} active, {sensors_offline} offline)")

                # Save updated registry
                self._save_sensor_registry()

            except asyncio.CancelledError:
                self.logger.info("Health check task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in periodic health checks: {e}")

    async def startup_health_check(self):
        """Check health of all known sensors on startup"""
        self.logger.info("Running startup health check on all known sensors...")

        for sensor_key, sensor_info in list(self.broadcast_sensors.items()):
            status = await self.check_sensor_health(sensor_key, sensor_info)
            sensor_info['status'] = status
            sensor_name = sensor_info.get('node_id', sensor_key)
            self.logger.info(f"Sensor {sensor_name}: {status}")

        self._save_sensor_registry()
        self.logger.info("Startup health check complete")

    async def start(self):
        """Start the coordinator"""
        self.logger.info(f"Starting KOI Coordinator on port {self.port}")

        # Start KOI node
        await self.koi_node.start()

        # Run startup health check on known sensors
        await self.startup_health_check()

        # Start periodic health monitoring task
        self.health_check_task = asyncio.create_task(self.periodic_health_checks())
        self.logger.info("Started periodic health monitoring")

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

        # Stop health check task
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        # Save final sensor registry state
        self._save_sensor_registry()

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