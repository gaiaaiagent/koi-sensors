"""
KOI Protocol - Coordinator Node
Full KOI node implementing complete KOI-net protocol with FastAPI
"""

import asyncio
import hashlib
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Body, FastAPI, HTTPException, Query
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
from shared.koi_envelope import (
    EnvelopeError,
    load_private_key_from_env,
    load_public_keys_from_env,
    sign_envelope,
    verify_envelope
)

# Import rid-lib for JCS hash recomputation (P1a alignment)
try:
    from rid_lib.ext import Manifest as RidLibManifest
    RID_LIB_AVAILABLE = True
except ImportError:
    RidLibManifest = None
    RID_LIB_AVAILABLE = False


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


# ============================================================================
# P1a KOI-net Strict Wire Models (schema-exact for interoperability)
# Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
# ============================================================================

class KoiNetPollEventsRequest(BaseModel):
    """Strict KOI-net PollEvents request model."""
    type: str = "poll_events"
    limit: int = 0  # 0 means no limit


class KoiNetWireManifest(BaseModel):
    """Strict KOI-net wire manifest: {rid, timestamp, sha256_hash} only."""
    rid: str
    timestamp: str  # Must use Z suffix, not +00:00
    sha256_hash: str


class KoiNetWireEvent(BaseModel):
    """Strict KOI-net wire event: {rid, event_type, manifest, contents} only."""
    rid: str
    event_type: str
    manifest: Optional[KoiNetWireManifest] = None
    contents: Optional[Dict[str, Any]] = None


class KoiNetEventsPayloadResponse(BaseModel):
    """Strict KOI-net EventsPayload response model."""
    type: str = "events_payload"
    events: List[KoiNetWireEvent]


def _timestamp_to_z_format(ts: str) -> str:
    """Convert timestamp to Z suffix format (e.g., 2025-12-23T12:00:00Z).

    KOI-net Pydantic serializes UTC datetimes with Z suffix, not +00:00.
    This is critical for SignedEnvelope signature matching.
    """
    if not ts:
        return ts
    # Handle +00:00 suffix
    if ts.endswith("+00:00"):
        return ts[:-6] + "Z"
    # Handle timezone offset like +00:00 embedded in the string
    if "+00:00" in ts:
        return ts.replace("+00:00", "Z")
    return ts


def _to_koi_net_wire_event(internal_event: KOIEvent) -> KoiNetWireEvent:
    """Transform internal KOIEvent to strict KOI-net wire format.

    P1a Requirements:
    - Wire Event: {rid, event_type, manifest, contents} only
    - Wire Manifest: {rid, timestamp, sha256_hash} only
    - Timestamp: Z suffix (not +00:00)
    - Hash: Recompute sha256_hash via rid-lib JCS from contents

    Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
    """
    rid_str = internal_event.rid
    contents = internal_event.bundle.contents if internal_event.bundle else {}

    # Get timestamp from manifest, convert to Z format
    ts = ""
    if internal_event.bundle and internal_event.bundle.manifest:
        ts = internal_event.bundle.manifest.timestamp
    elif internal_event.timestamp:
        ts = internal_event.timestamp
    ts = _timestamp_to_z_format(ts)

    # Recompute sha256_hash via rid-lib JCS canonicalization
    sha256_hash = ""
    if RID_LIB_AVAILABLE and RidLibManifest and contents:
        try:
            rid_lib_manifest = RidLibManifest.generate(rid_str, contents)
            sha256_hash = rid_lib_manifest.sha256_hash
        except Exception:
            # Fallback to stored hash if rid-lib fails
            if internal_event.bundle and internal_event.bundle.manifest:
                sha256_hash = internal_event.bundle.manifest.sha256_hash
    elif internal_event.bundle and internal_event.bundle.manifest:
        # Fallback if rid-lib not available
        sha256_hash = internal_event.bundle.manifest.sha256_hash

    # Build strict wire manifest (only rid, timestamp, sha256_hash)
    wire_manifest = None
    if sha256_hash or ts:
        wire_manifest = KoiNetWireManifest(
            rid=rid_str,
            timestamp=ts,
            sha256_hash=sha256_hash
        )

    return KoiNetWireEvent(
        rid=rid_str,
        event_type=internal_event.event_type,
        manifest=wire_manifest,
        contents=contents if contents else None
    )


class KOICoordinator:
    """KOI Coordinator - Full Node with sensor management"""
    
    def __init__(self, node_name: str = "regen-coordinator", port: int = 8000):
        self.node_name = node_name
        self.port = port
        self.start_time = datetime.now()

        # Initialize KOI full node
        self.koi_node = KOIFullNode(node_name, port)
        self.event_queue_file = Path(__file__).parent / "coordinator_event_queue.json"
        self.koi_node.configure_event_queue_persistence(self.event_queue_file)

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

        # Envelope signing/verification
        self.envelope_private_key = load_private_key_from_env()
        self.envelope_public_keys = load_public_keys_from_env()
        self.envelope_sign = bool(self.envelope_private_key)
        self.envelope_verify = bool(self.envelope_public_keys)
        self.envelope_verify_target = os.getenv("KOI_ENVELOPE_VERIFY_TARGET", "false").lower() in ("1", "true", "yes")
        if os.getenv("KOI_ENVELOPE_SIGN") is not None:
            self.envelope_sign = os.getenv("KOI_ENVELOPE_SIGN", "").lower() in ("1", "true", "yes")
        if os.getenv("KOI_ENVELOPE_VERIFY") is not None:
            self.envelope_verify = os.getenv("KOI_ENVELOPE_VERIFY", "").lower() in ("1", "true", "yes")
        
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

        def _unwrap_envelope(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[str], bool]:
            """Accept SignedEnvelope-style payloads with optional signature verification."""
            if isinstance(payload, dict) and "payload" in payload and "source_node" in payload:
                if self.envelope_verify:
                    try:
                        payload, source_node = verify_envelope(
                            payload,
                            self.envelope_public_keys,
                            expected_target=self.koi_node.node_id,
                            enforce_target=self.envelope_verify_target
                        )
                    except EnvelopeError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
                else:
                    source_node = payload.get("source_node")
                    payload = payload.get("payload", {})
                return payload, source_node, True
            return payload, None, False

        def _wrap_response(payload: Dict[str, Any], target_node: Optional[str], use_envelope: bool):
            if use_envelope and self.envelope_sign and target_node:
                return sign_envelope(payload, self.koi_node.node_id, target_node, self.envelope_private_key)
            return payload

        def _koi_net_event_to_koi_event_data(event: Dict[str, Any], source_node: Optional[str]) -> Dict[str, Any]:
            """Convert KOI-net event shape into local KOIEvent-compatible dict."""
            event_type = event.get("event_type")
            rid = event.get("rid")
            timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
            event_data = {
                "event_type": event_type,
                "rid": rid,
                "timestamp": timestamp,
                "source_node": event.get("source_node") or source_node or "unknown"
            }

            manifest = event.get("manifest") or {}
            contents = event.get("contents") or {}
            if manifest or contents:
                content_hash = manifest.get("sha256_hash") or manifest.get("content_hash")
                if not content_hash:
                    content_hash = hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()

                manifest_payload = {
                    "rid": rid,
                    "timestamp": manifest.get("timestamp") or timestamp,
                    "content_hash": content_hash,
                    "size_bytes": manifest.get("size_bytes") or len(json.dumps(contents).encode()),
                    "content_type": manifest.get("content_type") or "application/json",
                    "version": manifest.get("version") or "1.0",
                    "metadata": manifest.get("metadata") or {}
                }
                event_data["bundle"] = {
                    "rid": rid,
                    "manifest": manifest_payload,
                    "contents": contents
                }

            if event.get("reason"):
                event_data["reason"] = event["reason"]

            return event_data

        def _manifest_to_koi_net(manifest: Manifest) -> Dict[str, Any]:
            """Convert local Manifest to KOI-net manifest shape."""
            return {
                "rid": manifest.rid,
                "timestamp": manifest.timestamp,
                "sha256_hash": manifest.content_hash,
                "size_bytes": manifest.size_bytes,
                "content_type": manifest.content_type,
                "version": manifest.version,
                "metadata": manifest.metadata or {}
            }

        def _normalize_broadcast_events(payload: Dict[str, Any], source_node: Optional[str]) -> List[Dict[str, Any]]:
            """Accept KOI-net EventsPayload or legacy single-event payloads."""
            if isinstance(payload, dict) and isinstance(payload.get("events"), list):
                events = []
                for event in payload["events"]:
                    if isinstance(event, dict):
                        if "bundle" in event or "timestamp" in event or "source_node" in event:
                            if source_node and "source_node" not in event:
                                event["source_node"] = source_node
                            events.append(event)
                        else:
                            events.append(_koi_net_event_to_koi_event_data(event, source_node))
                return events
            if isinstance(payload, dict):
                if source_node and "source_node" not in payload:
                    payload["source_node"] = source_node
                return [payload]
            return []
        
        @self.app.post("/events/broadcast")
        async def broadcast_event(request: Dict[str, Any] = Body(...)):
            """Broadcast event to network (KOI-net endpoint)"""
            try:
                payload, envelope_source, envelope_used = _unwrap_envelope(request)
                events_data = _normalize_broadcast_events(payload, envelope_source)
                if not events_data:
                    raise ValueError("No events found in broadcast payload")

                results = []
                for event_data in events_data:
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
                            results.append({"status": "skipped_duplicate", "event_id": event.rid, "reason": "duplicate_content"})
                            continue

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

                    # Broadcast queues for polling and forwards to connected nodes
                    await self.koi_node.broadcast_event(event)

                    # Note: Processor forwarding is now handled via polling pattern
                    # The forwarder polls /events/poll and forwards to semantic bridge
                    # await self._forward_to_processor(event)
                    
                    self.logger.info(f"Broadcast {event.event_type} event for {event.rid}")
                    results.append({"status": "success", "event_id": event.rid})

                if len(results) == 1:
                    return _wrap_response(results[0], envelope_source, envelope_used)
                return _wrap_response(
                    {"status": "success", "event_count": len(results), "results": results},
                    envelope_source,
                    envelope_used
                )
                
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

        @self.app.post("/events/poll")
        async def poll_events_post(request: Dict[str, Any] = Body(...)):
            """KOI-net compatible poll endpoint (POST with optional envelope)."""
            try:
                payload, source_node, envelope_used = _unwrap_envelope(request)
                if not isinstance(payload, dict):
                    raise ValueError("Invalid poll payload")

                node_id = source_node or payload.get("node_id")
                if not node_id:
                    raise ValueError("Missing node_id (use SignedEnvelope or include node_id)")

                limit = payload.get("limit", 50)
                include_event_ids = bool(payload.get("include_event_ids"))
                max_events = 50 if not isinstance(limit, int) or limit <= 0 else limit

                events, event_ids = self.koi_node.get_queued_events_for_delivery(node_id, max_events)
                event_dicts = []
                for event in events:
                    manifest_payload = _manifest_to_koi_net(event.bundle.manifest) if event.bundle else None
                    event_payload = {
                        "rid": event.rid,
                        "event_type": event.event_type,
                        "timestamp": event.timestamp,
                        "source_node": event.source_node,
                        "manifest": manifest_payload,
                        "contents": event.bundle.contents if event.bundle else None
                    }
                    event_dicts.append(event_payload)

                # Add node as subscriber
                self.koi_node.add_event_subscriber(node_id)

                response_payload = {
                    "type": "events_payload",
                    "events": event_dicts
                }
                if include_event_ids:
                    response_payload["event_ids"] = event_ids
                return _wrap_response(response_payload, node_id, envelope_used)
            except Exception as e:
                self.logger.error(f"Error polling events (POST): {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/events/confirm")
        async def confirm_delivery(
            request: Dict[str, Any] = Body(...)
        ):
            """Confirm delivery of events by a node (KOI-net endpoint)"""
            try:
                payload, envelope_source, envelope_used = _unwrap_envelope(request)
                if envelope_source:
                    payload["node_id"] = payload.get("node_id") or envelope_source
                confirm_request = DeliveryConfirmationRequest(**payload)
                # Confirm delivery of events
                confirmed_count = self.koi_node.confirm_delivery(confirm_request.node_id, confirm_request.event_ids)

                self.logger.info(f"Node {confirm_request.node_id} confirmed {confirmed_count} events")

                response_payload = DeliveryConfirmationResponse(
                    confirmed_count=confirmed_count,
                    node_id=self.koi_node.node_id,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                return _wrap_response(response_payload.model_dump(), confirm_request.node_id, envelope_used)

            except Exception as e:
                self.logger.error(f"Error confirming delivery: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # ====================================================================
        # P1a: Strict KOI-net interop surface (/koi-net/*)
        # Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
        # ====================================================================

        @self.app.post("/koi-net/events/poll", response_model=KoiNetEventsPayloadResponse)
        async def koi_net_poll_events(request: KoiNetPollEventsRequest = Body(...)):
            """Strict KOI-net events poll endpoint (P1a Level 2 interop).

            Requirements:
            - Request: {"type": "poll_events", "limit": 0}
            - Response: {"type": "events_payload", "events": [...]}
            - Wire Event: {rid, event_type, manifest, contents} only
            - Wire Manifest: {rid, timestamp, sha256_hash} only
            - Timestamp: Z suffix (not +00:00)
            - Hash: Recomputed via rid-lib JCS from contents
            - Queue: Read-only (does NOT mark events as delivered)

            This endpoint is designed for external KOI-net node interoperability.
            Internal clients should use /events/poll for delivery tracking.
            """
            try:
                # Determine limit (0 means no limit, use reasonable default)
                max_events = request.limit if request.limit > 0 else 100

                # Read-only: use get_queued_events() which doesn't mark as delivered
                internal_events = self.koi_node.get_queued_events(max_events)

                # Transform to strict KOI-net wire format
                wire_events = [_to_koi_net_wire_event(event) for event in internal_events]

                self.logger.info(f"KOI-net poll: returning {len(wire_events)} events (read-only)")

                return KoiNetEventsPayloadResponse(
                    type="events_payload",
                    events=wire_events
                )

            except Exception as e:
                self.logger.error(f"Error in /koi-net/events/poll: {e}")
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

        @self.app.post("/bundles/fetch")
        async def fetch_bundles_post(request: Dict[str, Any] = Body(...)):
            """KOI-net compatible bundle fetch endpoint (POST with optional envelope)."""
            try:
                payload, source_node, envelope_used = _unwrap_envelope(request)
                rids = payload.get("rids", []) if isinstance(payload, dict) else []
                bundles = []
                not_found = []
                for rid in rids:
                    bundle = self.koi_node.get_cached_bundle(rid)
                    if bundle:
                        bundle_payload = bundle.to_dict()
                        bundle_payload["manifest"] = _manifest_to_koi_net(bundle.manifest)
                        bundles.append(bundle_payload)
                    else:
                        not_found.append(rid)
                response_payload = {
                    "type": "bundles_payload",
                    "bundles": bundles,
                    "not_found": not_found,
                    "deferred": []
                }
                return _wrap_response(response_payload, source_node, envelope_used)
            except Exception as e:
                self.logger.error(f"Error fetching bundles (POST): {e}")
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

        @self.app.post("/manifests/fetch")
        async def fetch_manifests_post(request: Dict[str, Any] = Body(...)):
            """KOI-net compatible manifest fetch endpoint (POST with optional envelope)."""
            try:
                payload, source_node, envelope_used = _unwrap_envelope(request)
                rids = payload.get("rids", []) if isinstance(payload, dict) else []
                manifests = []
                not_found = []
                for rid in rids:
                    bundle = self.koi_node.get_cached_bundle(rid)
                    if bundle and bundle.manifest:
                        manifests.append(_manifest_to_koi_net(bundle.manifest))
                    else:
                        not_found.append(rid)
                response_payload = {
                    "type": "manifests_payload",
                    "manifests": manifests,
                    "not_found": not_found
                }
                return _wrap_response(response_payload, source_node, envelope_used)
            except Exception as e:
                self.logger.error(f"Error fetching manifests (POST): {e}")
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

        @self.app.post("/rids/fetch")
        async def fetch_rids_post(request: Dict[str, Any] = Body(...)):
            """KOI-net compatible RIDs fetch endpoint (POST with optional envelope)."""
            try:
                _payload, source_node, envelope_used = _unwrap_envelope(request)
                rids = self.koi_node.get_cached_rids()
                response_payload = {
                    "type": "rids_payload",
                    "rids": rids
                }
                return _wrap_response(response_payload, source_node, envelope_used)
            except Exception as e:
                self.logger.error(f"Error fetching RIDs (POST): {e}")
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
