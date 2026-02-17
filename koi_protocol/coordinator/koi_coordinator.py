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
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from typing import Literal
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
from ..protocol.config import NodeConfig, NodeContact
from ..protocol.node import NodeProfile as KoiNetNodeProfile, NodeType, NodeProvides
from ..protocol.edge import (
    EdgeProfile, EdgeType, EdgeStatus,
    generate_edge_bundle, generate_edge_rid,
)
from shared.koi_envelope import (
    AmbiguousNodeError,
    EnvelopeError,
    ErrorResponse,
    ErrorType,
    load_private_key_from_env,
    load_public_keys_from_env,
    node_rid_matches_public_key,
    sign_envelope,
    verify_envelope,
)

# rid-lib is a required dependency (Phase 2)
from rid_lib.ext import Manifest as RidLibManifest


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
    type: Literal["events_payload"] = "events_payload"
    events: List[KoiNetWireEvent]


# ============================================================================
# P1b KOI-net Strict Request/Response Models (SignedEnvelope interop)
# Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
# ============================================================================

class KoiNetFetchRidsRequest(BaseModel):
    """Strict KOI-net FetchRids request model."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_rids"] = "fetch_rids"


class KoiNetFetchManifestsRequest(BaseModel):
    """Strict KOI-net FetchManifests request model."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_manifests"] = "fetch_manifests"
    rids: List[str]


class KoiNetFetchBundlesRequest(BaseModel):
    """Strict KOI-net FetchBundles request model."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["fetch_bundles"] = "fetch_bundles"
    rids: List[str]


class KoiNetEventsPayloadRequest(BaseModel):
    """Strict KOI-net EventsPayload request model (for broadcast)."""
    model_config = ConfigDict(extra="forbid")
    type: Literal["events_payload"] = "events_payload"
    events: List[Dict[str, Any]]


class KoiNetRidsPayloadResponse(BaseModel):
    """Strict KOI-net RidsPayload response model."""
    type: Literal["rids_payload"] = "rids_payload"
    rids: List[str]


class KoiNetManifestsPayloadResponse(BaseModel):
    """Strict KOI-net ManifestsPayload response model."""
    type: Literal["manifests_payload"] = "manifests_payload"
    manifests: List[Dict[str, Any]]


class KoiNetBundlesPayloadResponse(BaseModel):
    """Strict KOI-net BundlesPayload response model."""
    type: Literal["bundles_payload"] = "bundles_payload"
    bundles: List[Dict[str, Any]]


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
    if contents:
        try:
            rid_lib_manifest = RidLibManifest.generate(rid_str, contents)
            sha256_hash = rid_lib_manifest.sha256_hash
        except Exception:
            # Fallback to stored hash if JCS canonicalization fails
            if internal_event.bundle and internal_event.bundle.manifest:
                sha256_hash = internal_event.bundle.manifest.sha256_hash
    elif internal_event.bundle and internal_event.bundle.manifest:
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

    def __init__(self, node_name: str = "regen-coordinator", port: int = 8000, cache_dir: str = None, config: NodeConfig = None):
        self.node_name = node_name
        self.port = port
        self.start_time = datetime.now()

        # Phase 1: NodeConfig support (optional, backward compat)
        self.node_config = config

        # Cache directory for persistent bundle storage (P2a)
        # Default to KOI_CACHE_DIR env var or project-local .rid_cache
        if cache_dir is None:
            if config:
                cache_dir = config.koi_net.cache_directory_path
            else:
                cache_dir = os.getenv("KOI_CACHE_DIR")
            if cache_dir is None:
                # Default to project-local cache directory
                cache_dir = str(Path(__file__).parent.parent.parent / ".rid_cache")

        # Initialize KOI full node with persistent cache
        self.koi_node = KOIFullNode(node_name, port, cache_dir=cache_dir)
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
        # Phase 5: Prefer key-derived identity from koi_node, fall back to env vars
        if self.koi_node.private_key:
            self.envelope_private_key = self.koi_node.private_key
        else:
            self.envelope_private_key = load_private_key_from_env()
        self.envelope_public_keys = load_public_keys_from_env()

        # Auto-register our own public key so we can verify our own signed responses in tests
        if self.koi_node.public_key and self.koi_node.node_id not in self.envelope_public_keys:
            self.envelope_public_keys[self.koi_node.node_id] = self.koi_node.public_key

        self.envelope_sign = bool(self.envelope_private_key)
        self.envelope_verify = bool(self.envelope_public_keys)
        self.envelope_verify_target = os.getenv("KOI_ENVELOPE_VERIFY_TARGET", "false").lower() in ("1", "true", "yes")
        if os.getenv("KOI_ENVELOPE_SIGN") is not None:
            self.envelope_sign = os.getenv("KOI_ENVELOPE_SIGN", "").lower() in ("1", "true", "yes")
        if os.getenv("KOI_ENVELOPE_VERIFY") is not None:
            self.envelope_verify = os.getenv("KOI_ENVELOPE_VERIFY", "").lower() in ("1", "true", "yes")
        # When true, /koi-net/* endpoints reject unsigned requests (federation mode)
        self.koi_net_require_signed = os.getenv(
            "KOI_NET_REQUIRE_SIGNED", "false"
        ).lower() in ("1", "true", "yes")
        # When true, poll delivery filters events by edge rid_types (Phase 6)
        self.koi_net_edge_filtering = os.getenv(
            "KOI_NET_EDGE_FILTERING", "false"
        ).lower() in ("1", "true", "yes")
        # When true, polls return empty if no APPROVED edge exists for the polling node (Phase 6a)
        self.koi_net_require_approved_edge_for_poll = os.getenv(
            "KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL", "false"
        ).lower() in ("1", "true", "yes")
        # When false, proposed edges stay PROPOSED in handshake_with() (Phase 6a)
        self.koi_net_auto_approve_edges = os.getenv(
            "KOI_NET_AUTO_APPROVE_EDGES", "true"
        ).lower() in ("1", "true", "yes")
        # Inbound broadcast policy: "allow" (default) or "deny" (Phase 6a)
        self.koi_net_inbound_broadcast = os.getenv(
            "KOI_NET_INBOUND_BROADCAST", "allow"
        ).lower()
        
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

        # Phase 1: Peer discovery state
        self.known_peers: Dict[str, Dict[str, Any]] = {}  # node_rid -> {profile, edges, last_seen}
        self.edges: Dict[str, EdgeProfile] = {}  # edge_rid -> EdgeProfile
        self.peers_file = Path(__file__).parent / "coordinator_peers.json"
        self._load_peers()

        # Phase 3: Handler chain pipeline
        from ..processor import KnowledgePipeline
        from ..processor.default_handlers import (
            heartbeat_handler,
            bundle_normalization_handler,
            sensor_tracking_handler,
            dedup_handler,
            cat_receipt_handler,
            event_emission_handler,
        )
        self.pipeline = KnowledgePipeline(
            coordinator=self,
            default_handlers=[
                heartbeat_handler,
                bundle_normalization_handler,
                sensor_tracking_handler,
                dedup_handler,
                cat_receipt_handler,
                event_emission_handler,
            ],
        )

        # Setup routes
        self._setup_routes()

    def _lookup_public_key(self, source_node: str):
        """Look up public key for a source_node with hash-length aliasing.

        Supports both 16-char (legacy/Octo) and 64-char (BlockScience canonical) hashes.

        1. Exact match against envelope_public_keys (always authoritative)
        2. If no exact match and source_node has 16-char hash, check if any
           64-char peer's truncated hash matches
        3. Reject ambiguous matches (multiple 64-char peers collide at 16 chars)

        Returns:
            public_key object, or None if not found
        """
        # Exact match first
        key = self.envelope_public_keys.get(source_node)
        if key:
            return key

        # Extract hash suffix from source_node RID
        if "+" not in source_node:
            return None
        suffix = source_node.rsplit("+", 1)[-1]

        # Only try aliasing for 16-char (legacy) hashes
        if len(suffix) != 16:
            return None

        # Search for 64-char peers whose truncated hash matches
        from shared.koi_envelope import _derive_hash_from_public_key
        candidates = []
        for node_rid, pub_key in self.envelope_public_keys.items():
            if "+" not in node_rid:
                continue
            peer_suffix = node_rid.rsplit("+", 1)[-1]
            if len(peer_suffix) == 64:
                try:
                    truncated = _derive_hash_from_public_key(pub_key, length=16)
                    if truncated == suffix:
                        candidates.append((node_rid, pub_key))
                except Exception:
                    continue

        if len(candidates) == 1:
            alias_rid, alias_key = candidates[0]
            self.logger.info(
                f"Hash alias: {source_node} resolved to {alias_rid} (16→64 char)"
            )
            return alias_key
        elif len(candidates) > 1:
            candidate_rids = [c[0] for c in candidates]
            self.logger.warning(
                f"Ambiguous hash alias: {source_node} matches {len(candidates)} "
                f"64-char peers: {candidate_rids}"
            )
            raise AmbiguousNodeError(
                f"16-char hash {suffix} is ambiguous — matches {candidate_rids}"
            )

        return None

    def _try_learn_public_key_from_handshake(self, payload: dict, source_node: str):
        """Try to extract and learn public key from a handshake payload.

        During first-contact, the peer's public_key is in the NodeProfile contents
        of the NEW event. This implements TOFU (trust-on-first-use) — we accept
        the key on first contact, then verify all subsequent messages.

        Returns:
            public_key object if successfully learned, None otherwise
        """
        try:
            from shared.koi_envelope import (
                public_key_from_b64der,
                node_rid_matches_public_key,
            )
        except ImportError:
            return None

        events = payload.get("events", [])
        for event in events:
            if event.get("event_type") == "NEW" and "koi-net.node" in event.get("rid", ""):
                contents = event.get("contents", {})
                b64_key = contents.get("public_key")
                if b64_key:
                    try:
                        pub_key = public_key_from_b64der(b64_key)
                        # Verify key matches the source_node RID
                        if node_rid_matches_public_key(source_node, pub_key):
                            self.envelope_public_keys[source_node] = pub_key
                            self.logger.info(
                                f"TOFU: Learned public key for {source_node} from handshake"
                            )
                            return pub_key
                        else:
                            self.logger.warning(
                                f"TOFU rejected: public_key in handshake does not match "
                                f"source_node RID {source_node}"
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to learn public key from handshake: {e}"
                        )
        return None

    async def _ingest_events(self, events_data: list[dict]) -> list[dict]:
        """Shared event ingestion through pipeline. Used by both broadcast endpoints.

        Returns list of result dicts with status and event_id for each event.
        Pipeline returns either KnowledgeObject (success) or PipelineStop (halted).
        """
        from ..processor import KnowledgeObject, PipelineStop

        results = []
        for event_data in events_data:
            kobj = KnowledgeObject.from_event_data(event_data)
            result = await self.pipeline.process(kobj)

            if isinstance(result, PipelineStop):
                stopped_kobj = result.kobj
                status = stopped_kobj.result_status or "stopped"
                entry = {"status": status, "event_id": stopped_kobj.rid}
                if status == "skipped_duplicate":
                    entry["reason"] = "duplicate_content"
                results.append(entry)
            else:
                self.logger.info(f"Broadcast {result.event_type} event for {result.rid}")
                results.append({
                    "status": result.result_status or "success",
                    "event_id": result.rid,
                })
        return results

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
            """Broadcast event to network — Phase 3: unified pipeline ingestion."""
            try:
                payload, envelope_source, envelope_used = _unwrap_envelope(request)
                events_data = _normalize_broadcast_events(payload, envelope_source)
                if not events_data:
                    raise ValueError("No events found in broadcast payload")

                results = await self._ingest_events(events_data)

                # Preserve response shape: single event = flat dict, multi = wrapped
                if len(results) == 1:
                    return _wrap_response(results[0], envelope_source, envelope_used)
                return _wrap_response(
                    {"status": "success", "event_count": len(results), "results": results},
                    envelope_source,
                    envelope_used,
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
        # P1b: Strict KOI-net interop surface (/koi-net/*) with SignedEnvelope
        # Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
        #
        # Key differences from internal endpoints:
        # - Uses ErrorResponse (not HTTPException) for KOI-net interop
        # - Supports SignedEnvelope with signature verification
        # - Signed request → signed response required
        # - Schema-exact wire models only
        # ====================================================================

        async def _handle_koi_net_envelope(
            request: Request,
            process_fn,
            endpoint_name: str,
            body: dict = None
        ):
            """Generic handler for /koi-net/* endpoints with SignedEnvelope support.

            Args:
                request: FastAPI Request object
                process_fn: Function(payload, source_node) -> response_payload
                    Can be sync or async. Receives source_node as second arg.
                endpoint_name: Endpoint name for logging
                body: Optional pre-parsed request body (avoids double-read)

            Returns:
                JSONResponse with signed or unsigned payload
            """
            if body is None:
                try:
                    body = await request.json()
                except Exception:
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error="invalid_json",
                            detail="Request body is not valid JSON"
                        ).model_dump()
                    )

            # Check if request is a SignedEnvelope
            is_signed = (
                isinstance(body, dict) and
                "signature" in body and
                "payload" in body and
                "source_node" in body and
                "target_node" in body
            )

            if is_signed:
                source_node = body.get("source_node")
                target_node = body.get("target_node")

                # Validate target_node matches our node_id
                if target_node != self.koi_node.node_id:
                    self.logger.warning(
                        f"KOI-net {endpoint_name}: target_node mismatch "
                        f"(got {target_node}, expected {self.koi_node.node_id})"
                    )
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error="invalid_target",
                            detail=f"target_node {target_node} does not match {self.koi_node.node_id}"
                        ).model_dump()
                    )

                # Get public key for source_node (supports 16/64-char hash aliasing)
                try:
                    public_key = self._lookup_public_key(source_node)
                except AmbiguousNodeError as exc:
                    self.logger.warning(
                        f"KOI-net {endpoint_name}: ambiguous node hash for {source_node}"
                    )
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error=ErrorType.UnknownNode,
                            detail=str(exc)
                        ).model_dump()
                    )
                if not public_key:
                    # Auto-learn public key from handshake payload if this is a handshake
                    if endpoint_name == "handshake":
                        public_key = self._try_learn_public_key_from_handshake(
                            body.get("payload", {}), source_node
                        )
                    if not public_key:
                        self.logger.warning(
                            f"KOI-net {endpoint_name}: no public key for {source_node}"
                        )
                        return JSONResponse(
                            status_code=400,
                            content=ErrorResponse(
                                error=ErrorType.UnknownNode,
                                detail=f"No public key for {source_node}"
                            ).model_dump()
                        )

                # Validate key is usable (catch malformed/corrupt keys)
                try:
                    _ = public_key.key_size
                except Exception as exc:
                    self.logger.warning(
                        f"KOI-net {endpoint_name}: invalid key for {source_node} - {exc}"
                    )
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error=ErrorType.InvalidKey,
                            detail=f"Public key for {source_node} is malformed"
                        ).model_dump()
                    )

                # Verify signature using the resolved key (supports alias resolution)
                # NOTE: We use verify_envelope_with_key (not verify_envelope) because
                # verify_envelope re-does exact source_node lookup from the dict,
                # which would miss alias-resolved keys for 16-char legacy peers.
                from shared.koi_envelope import verify_envelope_with_key
                try:
                    verify_envelope_with_key(body, public_key)
                except EnvelopeError as exc:
                    self.logger.warning(
                        f"KOI-net {endpoint_name}: signature verification failed - {exc}"
                    )
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error="invalid_signature",
                            detail="Signature verification failed"
                        ).model_dump()
                    )

                payload = body["payload"]
            else:
                # Unsigned request
                if self.koi_net_require_signed:
                    self.logger.warning(
                        f"KOI-net {endpoint_name}: unsigned request rejected "
                        f"(KOI_NET_REQUIRE_SIGNED=true)"
                    )
                    return JSONResponse(
                        status_code=400,
                        content=ErrorResponse(
                            error="unsigned_not_allowed",
                            detail="This endpoint requires a SignedEnvelope. "
                                   "Set KOI_NET_REQUIRE_SIGNED=false to allow unsigned requests."
                        ).model_dump()
                    )
                payload = body
                source_node = None

            # Process the request (supports sync or async process_fn)
            try:
                import inspect as _inspect
                response_payload = process_fn(payload, source_node)
                if _inspect.isawaitable(response_payload):
                    response_payload = await response_payload
                if hasattr(response_payload, "model_dump"):
                    response_dict = response_payload.model_dump(exclude_none=True)
                else:
                    response_dict = response_payload
            except ValueError as exc:
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_request",
                        detail=str(exc)
                    ).model_dump()
                )
            except PermissionError as exc:
                return JSONResponse(
                    status_code=403,
                    content=ErrorResponse(
                        error="forbidden",
                        detail=str(exc)
                    ).model_dump()
                )
            except Exception as exc:
                self.logger.error(f"KOI-net {endpoint_name}: processing error - {exc}")
                return JSONResponse(
                    status_code=500,
                    content=ErrorResponse(
                        error="internal_error",
                        detail=str(exc)
                    ).model_dump()
                )

            # Sign response if request was signed
            if is_signed:
                if not self.envelope_private_key:
                    self.logger.error(
                        f"KOI-net {endpoint_name}: cannot sign response - no private key"
                    )
                    return JSONResponse(
                        status_code=500,
                        content=ErrorResponse(
                            error="signing_unavailable",
                            detail="Cannot sign response: no private key configured"
                        ).model_dump()
                    )
                signed_response = sign_envelope(
                    payload=response_dict,
                    source_node=self.koi_node.node_id,
                    target_node=source_node,
                    private_key=self.envelope_private_key
                )
                return JSONResponse(content=signed_response)
            else:
                return JSONResponse(content=response_dict)

        @self.app.post("/koi-net/events/poll")
        async def koi_net_poll_events(request: Request):
            """Strict KOI-net events poll endpoint (P1b Level 3 interop).

            Request (unsigned or SignedEnvelope):
                {"type": "poll_events", "limit": 0}

            Response:
                {"type": "events_payload", "events": [...]}

            Wire Event: {rid, event_type, manifest, contents} only
            Wire Manifest: {rid, timestamp, sha256_hash} only
            Timestamp: Z suffix (not +00:00)
            Hash: Recomputed via rid-lib JCS from contents

            Signed requests: per-node destructive flush (BlockScience compat)
            Unsigned requests: read-only queue view (backward compat)

            For signed requests, response is also signed.
            """
            # We need source_node from envelope to do per-node flush,
            # so we handle envelope unwrapping here before calling process_fn
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content=ErrorResponse(
                        error="invalid_json",
                        detail="Request body is not valid JSON"
                    ).model_dump()
                )

            # Check if request is a SignedEnvelope
            is_signed = (
                isinstance(body, dict) and
                "signature" in body and
                "payload" in body and
                "source_node" in body and
                "target_node" in body
            )

            source_node = None
            if is_signed:
                source_node = body.get("source_node")

            def process_poll(payload: dict, source_node=source_node):
                # Validate request type
                req_type = payload.get("type", "poll_events")
                if req_type != "poll_events":
                    raise ValueError(f"Expected type='poll_events', got '{req_type}'")

                limit = payload.get("limit", 0)
                max_events = limit if isinstance(limit, int) and limit > 0 else 100

                if source_node:
                    # Phase 6a: Require approved edge check
                    if self.koi_net_require_approved_edge_for_poll:
                        has_approved = self._has_approved_edge_for_peer(source_node)
                        if not has_approved:
                            self.logger.info(
                                f"KOI-net poll: no approved edge for {source_node}, returning empty"
                            )
                            return KoiNetEventsPayloadResponse(
                                type="events_payload",
                                events=[]
                            )

                    # Phase 6: Edge RID-type filtering (filter before delivery-marking)
                    rid_types = None
                    if self.koi_net_edge_filtering:
                        rid_types_list = self._get_edge_rid_types_for_peer(source_node)
                        if rid_types_list:
                            rid_types = rid_types_list

                    # Signed request: per-node destructive flush (BlockScience compat)
                    internal_events, _event_ids = self.koi_node.get_queued_events_for_delivery(
                        source_node, max_events, rid_types=rid_types
                    )

                    if rid_types:
                        self.logger.info(
                            f"KOI-net poll: edge filter applied for {source_node} "
                            f"(rid_types={rid_types}), {len(internal_events)} events delivered"
                        )

                    self.logger.info(
                        f"KOI-net poll: returning {len(internal_events)} events "
                        f"for {source_node} (per-node flush)"
                    )
                else:
                    # Unsigned request: read-only queue view (backward compat)
                    # Phase 6a: If approved edge required, unsigned polls get empty
                    if self.koi_net_require_approved_edge_for_poll:
                        self.logger.info(
                            "KOI-net poll: unsigned poll with REQUIRE_APPROVED_EDGE_FOR_POLL=true, returning empty"
                        )
                        return KoiNetEventsPayloadResponse(
                            type="events_payload",
                            events=[]
                        )
                    internal_events = self.koi_node.get_queued_events(max_events)
                    self.logger.info(
                        f"KOI-net poll: returning {len(internal_events)} events (read-only)"
                    )

                wire_events = [_to_koi_net_wire_event(event) for event in internal_events]

                return KoiNetEventsPayloadResponse(
                    type="events_payload",
                    events=wire_events
                )

            return await _handle_koi_net_envelope(request, process_poll, "events/poll", body=body)

        @self.app.post("/koi-net/events/broadcast")
        async def koi_net_broadcast_events(request: Request):
            """Strict KOI-net events broadcast endpoint (P1b Level 3 interop).

            Request (unsigned or SignedEnvelope):
                {"type": "events_payload", "events": [...]}

            Response:
                Empty on success (HTTP 200)
                ErrorResponse on failure

            Accepts events from external KOI-net nodes.
            For signed requests, response is also signed.
            """
            async def process_broadcast(payload: dict, source_node=None):
                # Phase 6a: Inbound broadcast policy
                if self.koi_net_inbound_broadcast == "deny":
                    raise PermissionError("Inbound broadcasts disabled")

                req_type = payload.get("type", "events_payload")
                if req_type != "events_payload":
                    raise ValueError(f"Expected type='events_payload', got '{req_type}'")

                events = payload.get("events", [])
                if not isinstance(events, list):
                    raise ValueError("events must be a list")

                events_data = [
                    _koi_net_event_to_koi_event_data(e, source_node)
                    for e in events if isinstance(e, dict)
                ]
                results = await self._ingest_events(events_data)
                processed = sum(1 for r in results if r["status"] == "success")

                self.logger.info(f"KOI-net broadcast: processed {processed}/{len(events)} events")
                return {"status": "ok", "processed": processed}

            return await _handle_koi_net_envelope(request, process_broadcast, "events/broadcast")

        @self.app.post("/koi-net/rids/fetch")
        async def koi_net_fetch_rids(request: Request):
            """Strict KOI-net RIDs fetch endpoint (P1b Level 3 interop).

            Request (unsigned or SignedEnvelope):
                {"type": "fetch_rids"}

            Response:
                {"type": "rids_payload", "rids": [...]}

            For signed requests, response is also signed.
            """
            def process_fetch_rids(payload: dict, source_node=None):
                req_type = payload.get("type", "fetch_rids")
                if req_type != "fetch_rids":
                    raise ValueError(f"Expected type='fetch_rids', got '{req_type}'")

                rids = self.koi_node.get_cached_rids()

                return KoiNetRidsPayloadResponse(
                    type="rids_payload",
                    rids=rids
                )

            return await _handle_koi_net_envelope(request, process_fetch_rids, "rids/fetch")

        @self.app.post("/koi-net/manifests/fetch")
        async def koi_net_fetch_manifests(request: Request):
            """Strict KOI-net manifests fetch endpoint (P1b Level 3 interop).

            Request (unsigned or SignedEnvelope):
                {"type": "fetch_manifests", "rids": [...]}

            Response:
                {"type": "manifests_payload", "manifests": [...]}

            Wire Manifest: {rid, timestamp, sha256_hash} only
            Timestamp: Z suffix (not +00:00)

            For signed requests, response is also signed.
            """
            def process_fetch_manifests(payload: dict, source_node=None):
                req_type = payload.get("type", "fetch_manifests")
                if req_type != "fetch_manifests":
                    raise ValueError(f"Expected type='fetch_manifests', got '{req_type}'")

                rids = payload.get("rids", [])
                if not isinstance(rids, list):
                    raise ValueError("rids must be a list")

                manifests = []
                for rid in rids:
                    bundle = self.koi_node.get_cached_bundle(rid)
                    if bundle and bundle.manifest:
                        # Return strict KOI-net wire manifest format
                        ts = _timestamp_to_z_format(bundle.manifest.timestamp)
                        sha256_hash = bundle.manifest.sha256_hash if hasattr(bundle.manifest, 'sha256_hash') else bundle.manifest.content_hash
                        manifests.append({
                            "rid": rid,
                            "timestamp": ts,
                            "sha256_hash": sha256_hash
                        })

                return KoiNetManifestsPayloadResponse(
                    type="manifests_payload",
                    manifests=manifests
                )

            return await _handle_koi_net_envelope(request, process_fetch_manifests, "manifests/fetch")

        @self.app.post("/koi-net/bundles/fetch")
        async def koi_net_fetch_bundles(request: Request):
            """Strict KOI-net bundles fetch endpoint (P1b Level 3 interop).

            Request (unsigned or SignedEnvelope):
                {"type": "fetch_bundles", "rids": [...]}

            Response:
                {"type": "bundles_payload", "bundles": [...]}

            Bundle: {manifest: {...}, contents: {...}}
            Wire Manifest: {rid, timestamp, sha256_hash} only
            Timestamp: Z suffix (not +00:00)

            For signed requests, response is also signed.
            """
            def process_fetch_bundles(payload: dict, source_node=None):
                req_type = payload.get("type", "fetch_bundles")
                if req_type != "fetch_bundles":
                    raise ValueError(f"Expected type='fetch_bundles', got '{req_type}'")

                rids = payload.get("rids", [])
                if not isinstance(rids, list):
                    raise ValueError("rids must be a list")

                bundles = []
                for rid in rids:
                    bundle = self.koi_node.get_cached_bundle(rid)
                    if bundle:
                        # Return strict KOI-net wire bundle format
                        ts = _timestamp_to_z_format(bundle.manifest.timestamp)
                        sha256_hash = bundle.manifest.sha256_hash if hasattr(bundle.manifest, 'sha256_hash') else bundle.manifest.content_hash
                        bundles.append({
                            "manifest": {
                                "rid": rid,
                                "timestamp": ts,
                                "sha256_hash": sha256_hash
                            },
                            "contents": bundle.contents
                        })

                return KoiNetBundlesPayloadResponse(
                    type="bundles_payload",
                    bundles=bundles
                )

            return await _handle_koi_net_envelope(request, process_fetch_bundles, "bundles/fetch")

        # ====================================================================
        # Phase 1: Handshake endpoint for peer discovery
        # ====================================================================

        @self.app.post("/koi-net/handshake")
        async def koi_net_handshake(request: Request):
            """KOI-net peer handshake endpoint.

            Implements the BlockScience handshake protocol:
            1. Incoming node sends events_payload with FORGET (reset) + NEW (own NodeProfile)
            2. We store peer's NodeProfile, respond with our own
            3. We propose an EdgeProfile (POLL type)

            Request (unsigned or SignedEnvelope):
                {"type": "events_payload", "events": [
                    {"rid": "<peer_rid>", "event_type": "FORGET"},
                    {"rid": "<peer_rid>", "event_type": "NEW",
                     "manifest": {...}, "contents": {<NodeProfile>}}
                ]}

            Response:
                {"type": "handshake_response",
                 "node_rid": "<our_rid>",
                 "profile": {<our NodeProfile>},
                 "proposed_edge": {<EdgeProfile>} | null}
            """
            def process_handshake(payload: dict, source_node=None):
                req_type = payload.get("type", "events_payload")
                events = payload.get("events", [])

                peer_rid = None
                peer_profile_data = None

                for event in events:
                    event_type = event.get("event_type", "")
                    rid = event.get("rid", "")

                    if event_type == "FORGET" and "koi-net.node" in rid:
                        # Reset stale state for this peer
                        if rid in self.known_peers:
                            self.logger.info(f"Handshake FORGET: clearing stale state for {rid}")
                            del self.known_peers[rid]

                    elif event_type == "NEW" and "koi-net.node" in rid:
                        peer_rid = rid
                        peer_profile_data = event.get("contents", {})

                if not peer_rid or not peer_profile_data:
                    raise ValueError(
                        "Handshake requires a NEW event with node RID and NodeProfile contents"
                    )

                # Validate and store peer profile
                try:
                    peer_profile = KoiNetNodeProfile.model_validate(peer_profile_data)
                except Exception as e:
                    raise ValueError(f"Invalid NodeProfile in handshake: {e}")

                self.known_peers[peer_rid] = {
                    "profile": peer_profile.model_dump(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "edges": [],
                }
                self._save_peers()
                self.logger.info(f"Handshake: stored peer profile for {peer_rid}")

                # Build our own profile
                our_rid = self.koi_node.node_id
                our_profile = self.koi_node.to_koi_net_profile()

                # If config provides base_url, use it
                if self.node_config and self.node_config.koi_net.node_profile.base_url:
                    our_profile.base_url = self.node_config.koi_net.node_profile.base_url
                elif self.port:
                    our_profile.base_url = os.getenv('KOI_BASE_URL') or f"http://localhost:{self.port}/koi-net"

                # Propose an edge (POLL type — peer polls us)
                proposed_edge = None
                edge_bundle = generate_edge_bundle(
                    source=our_rid,
                    target=peer_rid,
                    rid_types=[],  # All types for now
                    edge_type=EdgeType.POLL,
                )
                edge_rid = edge_bundle["rid"]
                edge_profile = EdgeProfile.model_validate(edge_bundle["contents"])
                self.edges[edge_rid] = edge_profile

                # Track edge on peer
                self.known_peers[peer_rid]["edges"].append(edge_rid)
                self._save_peers()

                proposed_edge = edge_profile.model_dump()
                self.logger.info(f"Handshake: proposed POLL edge {edge_rid} to {peer_rid}")

                return {
                    "type": "handshake_response",
                    "node_rid": our_rid,
                    "profile": our_profile.model_dump(),
                    "proposed_edge": proposed_edge,
                    "edge_rid": edge_rid,
                }

            return await _handle_koi_net_envelope(request, process_handshake, "handshake")

        @self.app.post("/koi-net/edges/approve")
        async def koi_net_approve_edge(request: Request):
            """Approve a proposed edge (completes handshake).

            Request:
                {"type": "edge_approve", "edge_rid": "...", "node_rid": "..."}

            Response:
                {"type": "edge_approved", "edge_rid": "...", "status": "APPROVED"}
            """
            def process_approve(payload: dict, source_node=None):
                edge_rid = payload.get("edge_rid")
                approving_node = payload.get("node_rid")

                if not edge_rid:
                    raise ValueError("edge_rid is required")

                edge = self.edges.get(edge_rid)
                if not edge:
                    raise ValueError(f"Unknown edge: {edge_rid}")

                if edge.status == EdgeStatus.APPROVED:
                    return {"type": "edge_approved", "edge_rid": edge_rid, "status": "APPROVED"}

                # Approve the edge
                edge.status = EdgeStatus.APPROVED
                self.edges[edge_rid] = edge
                self._save_peers()

                self.logger.info(f"Edge {edge_rid} approved by {approving_node}")

                return {"type": "edge_approved", "edge_rid": edge_rid, "status": "APPROVED"}

            return await _handle_koi_net_envelope(request, process_approve, "edges/approve")

        @self.app.get("/koi-net/peers")
        async def koi_net_list_peers():
            """List known peers and their edge status."""
            peers = []
            for rid, info in self.known_peers.items():
                peer_edges = []
                for edge_rid in info.get("edges", []):
                    edge = self.edges.get(edge_rid)
                    if edge:
                        peer_edges.append({
                            "edge_rid": edge_rid,
                            "edge_type": edge.edge_type,
                            "status": edge.status,
                        })
                peers.append({
                    "node_rid": rid,
                    "profile": info.get("profile"),
                    "last_seen": info.get("last_seen"),
                    "edges": peer_edges,
                })
            return {"peers": peers, "count": len(peers)}

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
        
        @self.app.get("/koi-net/health")
        async def koi_net_health():
            """KOI-net federation health endpoint.

            Returns nested response matching Octo's contract for automatic
            public key discovery during handshake. Peers GET this endpoint
            and extract response["node"]["public_key"].
            """
            our_profile = self.koi_node.to_koi_net_profile()

            # Override base_url from config if available
            if self.node_config and self.node_config.koi_net.node_profile.base_url:
                our_profile.base_url = self.node_config.koi_net.node_profile.base_url
            elif self.port:
                our_profile.base_url = os.getenv('KOI_BASE_URL') or f"http://localhost:{self.port}/koi-net"

            # Build peer list
            peers = []
            for rid, info in self.known_peers.items():
                for edge_rid in info.get("edges", []):
                    edge = self.edges.get(edge_rid)
                    if edge:
                        peers.append({
                            "node_rid": rid,
                            "edge_type": edge.edge_type,
                            "status": edge.status,
                        })

            node_data = our_profile.model_dump(exclude_none=True)
            node_data["node_rid"] = self.koi_node.node_id
            node_data["node_name"] = self.node_name
            # Ensure node_type is a string
            if hasattr(node_data.get("node_type"), "value"):
                node_data["node_type"] = node_data["node_type"].value

            return {
                "status": "healthy",
                "node": node_data,
                "peers": peers,
                "event_queue_size": len(self.koi_node.event_queue),
                "protocol": {
                    "strict_mode": self.koi_net_require_signed,
                    "require_signed_envelopes": self.koi_net_require_signed,
                    "envelope_sign": self.envelope_sign,
                    "envelope_verify": self.envelope_verify,
                },
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

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

    # ====================================================================
    # Phase 1: Peer discovery persistence
    # ====================================================================

    def _load_peers(self):
        """Load known peers and edges from disk."""
        if self.peers_file.exists():
            try:
                with open(self.peers_file, 'r') as f:
                    data = json.load(f)
                    self.known_peers = data.get('peers', {})
                    # Reconstruct EdgeProfile objects from serialized dicts
                    for edge_rid, edge_data in data.get('edges', {}).items():
                        try:
                            self.edges[edge_rid] = EdgeProfile.model_validate(edge_data)
                        except Exception as e:
                            self.logger.warning(f"Failed to load edge {edge_rid}: {e}")
                    self.logger.info(
                        f"Loaded {len(self.known_peers)} peers, "
                        f"{len(self.edges)} edges from {self.peers_file}"
                    )
            except Exception as e:
                self.logger.error(f"Error loading peers: {e}")

    def _save_peers(self):
        """Persist known peers and edges to disk."""
        try:
            data = {
                'peers': self.known_peers,
                'edges': {
                    rid: edge.model_dump() for rid, edge in self.edges.items()
                },
                'last_updated': datetime.now(timezone.utc).isoformat(),
            }
            temp_path = self.peers_file.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self.peers_file)
        except Exception as e:
            self.logger.error(f"Error saving peers: {e}")

    @staticmethod
    def _node_rids_match(rid_a: str, rid_b: str) -> bool:
        """Check if two node RIDs refer to the same node (alias-aware).

        Handles 16-char (legacy) and 64-char (canonical) hash suffixes.
        Requires same prefix (before +), valid hash lengths {16,64}, hex-only.
        """
        if rid_a == rid_b:
            return True
        if "+" not in rid_a or "+" not in rid_b:
            return False
        prefix_a, suffix_a = rid_a.rsplit("+", 1)
        prefix_b, suffix_b = rid_b.rsplit("+", 1)
        if prefix_a != prefix_b:
            return False
        if len(suffix_a) not in (16, 64) or len(suffix_b) not in (16, 64):
            return False
        if not all(c in '0123456789abcdef' for c in suffix_a):
            return False
        if not all(c in '0123456789abcdef' for c in suffix_b):
            return False
        shorter, longer = sorted([suffix_a, suffix_b], key=len)
        return longer.startswith(shorter)

    def _has_approved_edge_for_peer(self, peer_node_rid: str) -> bool:
        """Check if any APPROVED edge exists where peer is the target (alias-aware)."""
        for edge in self.edges.values():
            if (self._node_rids_match(edge.target, peer_node_rid) and
                    edge.status == EdgeStatus.APPROVED):
                return True
        return False

    def _get_edge_rid_types_for_peer(self, peer_node_rid: str) -> list[str]:
        """Get the combined rid_types from all APPROVED edges where peer is target.

        Returns empty list if no edges have rid_types set (meaning allow all).
        Uses alias-aware RID matching to handle 16/64-char hash variants.
        """
        rid_types = []
        for edge in self.edges.values():
            if (self._node_rids_match(edge.target, peer_node_rid) and
                    edge.status == EdgeStatus.APPROVED and
                    edge.rid_types):
                rid_types.extend(edge.rid_types)
        return rid_types

    @staticmethod
    def _rid_matches_types(rid: str, rid_types: list[str]) -> bool:
        """Check if a RID string matches any of the allowed RID type prefixes.

        Delegates to KOIFullNode._rid_matches_types for single implementation.
        """
        return KOIFullNode._rid_matches_types(rid, rid_types)

    async def handshake_with(self, target_rid: str, target_url: str):
        """Initiate a handshake with a remote KOI-net node.

        Sends FORGET (reset stale state) then NEW (our NodeProfile) to the
        target's /koi-net/handshake endpoint.

        Phase 5 enhancements:
        - Signs edge approval when envelope_sign is True
        - Verifies response signature when peer key is known
        - Validates envelope↔payload identity binding (anti-spoofing)
        - TOFU for first contact (accept unverified when no key yet)
        - Auto-learns peer public key from /koi-net/health

        Args:
            target_rid: The target node's RID
            target_url: The target node's base URL (e.g. http://host:port/koi-net)
        """
        from shared.koi_envelope import verify_envelope_with_key

        our_rid = self.koi_node.node_id
        our_profile = self.koi_node.to_koi_net_profile()

        # Override base_url from config if available
        if self.node_config and self.node_config.koi_net.node_profile.base_url:
            our_profile.base_url = self.node_config.koi_net.node_profile.base_url
        elif self.port:
            our_profile.base_url = os.getenv('KOI_BASE_URL') or f"http://localhost:{self.port}/koi-net"

        # Build handshake payload with full NodeProfile
        # Uses the direct profile-exchange format for interop with Octo and
        # other KOI-net implementations that expect {type: "handshake", profile: ...}
        profile_data = our_profile.model_dump()
        profile_data["node_rid"] = our_rid
        profile_data["node_name"] = self.node_name

        handshake_payload = {
            "type": "handshake",
            "profile": profile_data,
        }

        # Optionally sign the handshake
        if self.envelope_sign and self.envelope_private_key and target_rid:
            handshake_payload = sign_envelope(
                handshake_payload, our_rid, target_rid, self.envelope_private_key
            )

        url = f"{target_url.rstrip('/')}/handshake"
        self.logger.info(f"Initiating handshake with {target_rid} at {url}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try to learn peer's public key from /koi-net/health first
                await self._try_learn_key_from_health(client, target_url, target_rid)

                response = await client.post(url, json=handshake_payload)

                if response.status_code == 200:
                    result = response.json()

                    # Verify signed response if we have peer's key
                    if "payload" in result and "signature" in result:
                        envelope_source = result.get("source_node")
                        peer_key = self._lookup_public_key(envelope_source) if envelope_source else None

                        if peer_key and self.envelope_verify:
                            try:
                                verify_envelope_with_key(result, peer_key)
                            except EnvelopeError:
                                self.logger.warning(
                                    f"Handshake response from {envelope_source} failed signature verification"
                                )
                                return False

                            # Enforce target_node matches us (anti-replay/misdirection)
                            envelope_target = result.get("target_node")
                            if envelope_target and envelope_target != our_rid:
                                self.logger.warning(
                                    f"Handshake response target mismatch: "
                                    f"target_node={envelope_target}, expected={our_rid}"
                                )
                                return False

                            # Bind envelope identity to payload identity (anti-spoofing)
                            inner = result["payload"]
                            payload_node_rid = inner.get("node_rid") or inner.get("source_node")
                            if payload_node_rid and payload_node_rid != envelope_source:
                                self.logger.warning(
                                    f"Identity mismatch: envelope source={envelope_source}, "
                                    f"payload node_rid={payload_node_rid} — rejecting"
                                )
                                return False
                        elif not peer_key:
                            self.logger.info(
                                f"First contact with {envelope_source} — "
                                f"accepting unverified response (no key yet)"
                            )

                        result = result["payload"]

                    peer_profile = result.get("profile")
                    peer_rid = result.get("node_rid")
                    # Octo-style response: node_rid lives inside profile
                    if not peer_rid and peer_profile:
                        peer_rid = peer_profile.get("node_rid")
                    proposed_edge = result.get("proposed_edge")
                    edge_rid = result.get("edge_rid")

                    if peer_rid and peer_profile:
                        # Learn public key from handshake response profile
                        peer_pub_key_b64 = peer_profile.get("public_key")
                        if peer_pub_key_b64 and peer_rid not in self.envelope_public_keys:
                            try:
                                from shared.koi_envelope import (
                                    public_key_from_b64der,
                                    node_rid_matches_public_key,
                                )
                                learned_key = public_key_from_b64der(peer_pub_key_b64)
                                if node_rid_matches_public_key(peer_rid, learned_key):
                                    self.envelope_public_keys[peer_rid] = learned_key
                                    self.logger.info(
                                        f"Learned public key for {peer_rid} from handshake response"
                                    )
                            except Exception as e:
                                self.logger.warning(f"Failed to learn peer key from response: {e}")

                        self.known_peers[peer_rid] = {
                            "profile": peer_profile,
                            "last_seen": datetime.now(timezone.utc).isoformat(),
                            "edges": [edge_rid] if edge_rid else [],
                        }

                        # Auto-approve the proposed edge (or leave PROPOSED if disabled)
                        if proposed_edge and edge_rid:
                            edge = EdgeProfile.model_validate(proposed_edge)
                            if not self.koi_net_auto_approve_edges:
                                edge.status = EdgeStatus.PROPOSED
                                self.edges[edge_rid] = edge
                                self.logger.info(
                                    f"Auto-approve disabled: edge {edge_rid} stays PROPOSED"
                                )
                                self._save_peers()
                                self.logger.info(f"Handshake complete with {peer_rid} (edge PROPOSED)")
                                return True
                            edge.status = EdgeStatus.APPROVED
                            self.edges[edge_rid] = edge

                            # Step 4a: Sign the edge approval
                            approve_url = f"{target_url.rstrip('/')}/edges/approve"
                            approve_payload = {
                                "type": "edge_approve",
                                "edge_rid": edge_rid,
                                "node_rid": our_rid,
                            }
                            if self.envelope_sign and self.envelope_private_key:
                                approve_payload = sign_envelope(
                                    approve_payload, our_rid, peer_rid,
                                    self.envelope_private_key
                                )
                            approval_ok = False
                            try:
                                approve_resp = await client.post(approve_url, json=approve_payload)
                                if approve_resp.status_code == 200:
                                    self.logger.info(f"Approved edge {edge_rid} with {peer_rid}")
                                    approval_ok = True
                                else:
                                    self.logger.warning(
                                        f"Edge approval failed for {edge_rid}: "
                                        f"{approve_resp.status_code} - {approve_resp.text[:200]}"
                                    )
                                    edge.status = EdgeStatus.PROPOSED
                                    self.edges[edge_rid] = edge
                            except Exception as e:
                                self.logger.warning(f"Failed to send edge approval: {e}")
                                edge.status = EdgeStatus.PROPOSED
                                self.edges[edge_rid] = edge

                            if not approval_ok:
                                self._save_peers()
                                self.logger.warning(
                                    f"Handshake with {peer_rid} incomplete — edge approval failed"
                                )
                                return False

                        self._save_peers()
                        self.logger.info(f"Handshake complete with {peer_rid}")
                        return True
                    else:
                        self.logger.warning(f"Handshake response missing node_rid or profile")
                        return False
                else:
                    self.logger.error(
                        f"Handshake failed with {target_rid}: "
                        f"{response.status_code} - {response.text}"
                    )
                    return False
        except Exception as e:
            self.logger.error(f"Error during handshake with {target_rid}: {e}")
            return False

    async def _try_learn_key_from_health(self, client, target_url: str, target_rid: str):
        """Try to learn peer's public key from /koi-net/health before handshake.

        Matches Octo's pattern of auto-discovering public keys from the health endpoint.
        """
        if target_rid in self.envelope_public_keys:
            return  # Already have key

        health_url = f"{target_url.rstrip('/')}/health"
        try:
            resp = await client.get(health_url, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                node_data = data.get("node", {})
                pub_key_b64 = node_data.get("public_key")
                node_rid = node_data.get("node_rid")
                if pub_key_b64 and node_rid:
                    from shared.koi_envelope import (
                        public_key_from_b64der,
                        node_rid_matches_public_key,
                    )
                    pub_key = public_key_from_b64der(pub_key_b64)
                    if node_rid_matches_public_key(node_rid, pub_key):
                        self.envelope_public_keys[node_rid] = pub_key
                        # Also store under target_rid if different (hash length alias)
                        if target_rid != node_rid:
                            self.envelope_public_keys[target_rid] = pub_key
                        self.logger.info(
                            f"Learned public key for {node_rid} from /koi-net/health"
                        )
                    else:
                        self.logger.warning(
                            f"Public key from {health_url} doesn't match node_rid {node_rid}"
                        )
        except Exception as e:
            self.logger.debug(f"Could not fetch /koi-net/health from {target_url}: {e}")

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

        # Phase 1: First-contact bootstrap (if configured and no known peers)
        if not self.known_peers:
            fc = None
            if self.node_config:
                fc = self.node_config.koi_net.first_contact
            else:
                fc_rid = os.getenv("KOI_FIRST_CONTACT_RID")
                fc_url = os.getenv("KOI_FIRST_CONTACT_URL")
                if fc_rid and fc_url:
                    fc = NodeContact(rid=fc_rid, url=fc_url)

            if fc and fc.rid and fc.url:
                self.logger.info(
                    f"No known peers — initiating first-contact handshake "
                    f"with {fc.rid} at {fc.url}"
                )
                asyncio.create_task(self.handshake_with(fc.rid, fc.url))

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

        # Save peer state
        self._save_peers()

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
