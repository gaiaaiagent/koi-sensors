"""
KOI Protocol - Node Implementation
Base classes for Full and Partial KOI nodes following KOI-net specification
"""

import asyncio
import hashlib
import json
import os
import aiohttp
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import logging
import uuid
from pathlib import Path

from ..core.rid_system import RID
from ..core.bundle_system import Bundle, KOIEvent, Manifest

# Import persistent cache (P2a)
try:
    from ..core.persistent_cache import PersistentBundleCache, RID_LIB_CACHE_AVAILABLE
except ImportError:
    PersistentBundleCache = None
    RID_LIB_CACHE_AVAILABLE = False

# BlockScience-aligned protocol models (Phase 1)
from ..protocol.node import NodeProfile as KoiNetNodeProfile, NodeType, NodeProvides


@dataclass
class LegacyNodeProfile:
    """Legacy KOI Node Profile (pre-Phase 1).

    Kept for backward compatibility with existing callers.
    Use KOINodeBase.to_koi_net_profile() for BlockScience-compatible profiles.
    """
    node_id: str
    node_name: str
    node_type: str  # "FULL" or "PARTIAL"
    version: str
    capabilities: List[str]
    endpoints: Dict[str, str]
    metadata: Dict[str, Any]


@dataclass 
class NodeContact:
    """Contact information for a KOI node"""
    url: str
    node_id: str
    last_seen: Optional[str] = None
    status: str = "unknown"


@dataclass
class QueuedEvent:
    """Represents an event in the queue with delivery tracking"""
    event: KOIEvent
    event_id: str
    queued_at: datetime
    delivered_to: Set[str]  # Set of node_ids that have received this event
    confirmed_by: Set[str]  # Set of node_ids that have confirmed receipt


class KOINodeBase(ABC):
    """Base class for KOI nodes"""

    def __init__(self, node_name: str, node_type: str, port: int = None, cache_dir: str = None):
        self.node_name = node_name
        self.node_type = node_type
        self.port = port
        self._cache_dir = cache_dir

        # Logging (must be first for other init steps to use)
        self.logger = logging.getLogger(f"koi.node.{node_name}")

        # Cryptographic identity (Phase 5: key-derived RID)
        self.private_key = None
        self.public_key = None

        # Resolve stable node identity (persisted across restarts)
        self.node_id = self._resolve_node_id()
        self.logger.info(f"Node identity: {self.node_id}")

        # Node state
        self.running = False
        self.cache: Dict[str, Bundle] = {}
        self.event_queue: List[QueuedEvent] = []  # Changed to use QueuedEvent
        self.known_nodes: Dict[str, NodeContact] = {}

        # Persistent cache (P2a) - uses rid_lib.ext.Cache for disk persistence
        self._persistent_cache: Optional[PersistentBundleCache] = None
        if cache_dir and PersistentBundleCache and RID_LIB_CACHE_AVAILABLE:
            try:
                self._persistent_cache = PersistentBundleCache(cache_dir)
                self.logger.info(f"Persistent cache enabled at {cache_dir}")
            except Exception as e:
                self.logger.warning(f"Failed to initialize persistent cache: {e}")

        # Event delivery tracking
        self.pending_deliveries: Dict[str, QueuedEvent] = {}  # event_id -> QueuedEvent
        self.delivery_timeout_seconds = 300  # 5 minutes
        self.event_queue_path: Optional[Path] = None

        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None

    def _resolve_node_id(self) -> str:
        """Resolve a stable node identity, persisted across restarts.

        Phase 5: Key-derived identity using ECDSA P-256 keypair.

        Priority:
        1. KOI_NODE_ID env var (explicit override — skips key derivation)
        2. Load keypair from {cache_dir}/node_private_key.pem → derive RID
        3. Generate new keypair → derive RID → persist

        The node RID is derived deterministically:
            orn:koi-net.node:{name}+sha256(base64(DER(public_key)))
        producing a 64-character hex hash matching BlockScience's canonical pattern.

        Migration: If an old .node_id exists with a different (16-char random) hash,
        the old RID is backed up and peer state is updated.
        """
        # Priority 1: explicit env var (escape hatch, skips crypto)
        env_id = os.getenv("KOI_NODE_ID")
        if env_id:
            return env_id

        # Priority 2+3: key-derived identity
        try:
            from shared.koi_envelope import (
                generate_and_save_keypair,
                derive_node_rid,
                _CRYPTO_AVAILABLE,
            )
        except ImportError:
            self.logger.warning("shared.koi_envelope not available — falling back to legacy identity")
            return self._resolve_node_id_legacy()

        if not _CRYPTO_AVAILABLE:
            self.logger.warning("cryptography not installed — falling back to legacy identity")
            return self._resolve_node_id_legacy()

        if not self._cache_dir:
            # No cache dir — generate ephemeral keypair (no persistence)
            from shared.koi_envelope import generate_keypair
            self.private_key, self.public_key = generate_keypair()
            return derive_node_rid(self.node_name, self.public_key)

        # Load or generate keypair from persistent storage
        key_path = str(Path(self._cache_dir) / "node_private_key.pem")
        password = os.getenv("KOI_PRIVATE_KEY_PASSWORD")
        self.private_key, self.public_key = generate_and_save_keypair(key_path, password)

        new_rid = derive_node_rid(self.node_name, self.public_key)

        # Check for migration from old .node_id
        id_file = Path(self._cache_dir) / ".node_id"
        if id_file.exists():
            try:
                old_rid = id_file.read_text().strip()
                if old_rid and old_rid != new_rid:
                    self._migrate_node_identity(old_rid, new_rid, id_file)
            except Exception as e:
                self.logger.warning(f"Failed to check old node_id for migration: {e}")

        # Persist new RID
        try:
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(new_rid)
        except Exception as e:
            self.logger.warning(f"Failed to persist node_id: {e}")

        self.logger.info(f"Key-derived identity: {new_rid}")
        return new_rid

    def _resolve_node_id_legacy(self) -> str:
        """Legacy identity resolution (pre-Phase 5, no cryptography)."""
        if self._cache_dir:
            id_file = Path(self._cache_dir) / ".node_id"
            if id_file.exists():
                try:
                    stored_id = id_file.read_text().strip()
                    if stored_id:
                        return stored_id
                except Exception as e:
                    self.logger.warning(f"Failed to read persisted node_id: {e}")

        random_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:16]
        node_id = f"orn:koi-net.node:{self.node_name}+{random_hash}"

        if self._cache_dir:
            try:
                id_file = Path(self._cache_dir) / ".node_id"
                id_file.parent.mkdir(parents=True, exist_ok=True)
                id_file.write_text(node_id)
                self.logger.info(f"Persisted new node_id to {id_file}")
            except Exception as e:
                self.logger.warning(f"Failed to persist node_id: {e}")

        return node_id

    def _migrate_node_identity(self, old_rid: str, new_rid: str, id_file: Path):
        """Migrate from old (random/16-char) node identity to new (key-derived/64-char).

        Steps:
        1. Backup old .node_id to .node_id.legacy
        2. Update peer state file (replace old self-RID with new)
        3. Log migration warning
        """
        self.logger.warning(
            f"Node identity migrated from {old_rid} to {new_rid}. "
            f"Peers using old RID will need re-handshake."
        )

        # Backup old identity
        legacy_file = id_file.with_suffix(".legacy")
        try:
            legacy_file.write_text(old_rid)
            self.logger.info(f"Backed up old node_id to {legacy_file}")
        except Exception as e:
            self.logger.warning(f"Failed to backup old node_id: {e}")

        # Update coordinator_peers.json if it exists
        # The peers file may be at a different path; look for it relative to this module
        peers_candidates = [
            Path(self._cache_dir).parent / "koi_protocol" / "coordinator" / "coordinator_peers.json",
            Path(__file__).parent.parent / "coordinator" / "coordinator_peers.json",
        ]
        for peers_path in peers_candidates:
            if peers_path.exists():
                try:
                    raw = peers_path.read_text()
                    if old_rid in raw:
                        updated = raw.replace(old_rid, new_rid)
                        temp = peers_path.with_suffix(".tmp")
                        temp.write_text(updated)
                        temp.replace(peers_path)
                        self.logger.info(f"Updated peer state: replaced {old_rid} with {new_rid} in {peers_path}")
                except Exception as e:
                    self.logger.error(
                        f"Failed to update peer state in {peers_path}: {e}. "
                        f"Manual intervention may be required."
                    )

    async def start(self):
        """Start the node"""
        self.logger.info(f"Starting {self.node_type} node: {self.node_name}")
        self.running = True
        self.session = aiohttp.ClientSession()

        # Load persisted bundles from disk (P2a)
        if self._persistent_cache:
            loaded = self._persistent_cache.load_all()
            # Populate memory cache from persistent cache
            self.cache = dict(self._persistent_cache._memory_cache)
            self.logger.info(f"Loaded {loaded} bundles from persistent cache")

        if self.event_queue_path and not self.event_queue:
            self._load_event_queue()

        if self.node_type == "PARTIAL":
            # Partial nodes start polling loop
            asyncio.create_task(self.polling_loop())
        elif self.node_type == "FULL":
            # Full nodes start cleanup loop
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """Stop the node"""
        self.logger.info(f"Stopping node: {self.node_name}")
        self.running = False

        # Cancel cleanup task for full nodes
        if hasattr(self, 'cleanup_task') and self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        if self.session:
            await self.session.close()

        self._persist_event_queue()

    def configure_event_queue_persistence(self, path: Path):
        """Enable persistence for event queue state."""
        self.event_queue_path = path
        self._load_event_queue()

    def _persist_event_queue(self):
        if self.event_queue_path:
            self._save_event_queue(self.event_queue_path)

    def _load_event_queue(self):
        """Load queued events from disk if present."""
        if not self.event_queue_path or not self.event_queue_path.exists():
            return

        try:
            with open(self.event_queue_path, "r") as f:
                data = json.load(f)

            self.event_queue = []
            self.pending_deliveries = {}

            for item in data.get("events", []):
                event = KOIEvent.from_dict(item["event"])
                queued_event = QueuedEvent(
                    event=event,
                    event_id=item["event_id"],
                    queued_at=datetime.fromisoformat(item["queued_at"]),
                    delivered_to=set(item.get("delivered_to", [])),
                    confirmed_by=set(item.get("confirmed_by", []))
                )
                self.event_queue.append(queued_event)
                self.pending_deliveries[queued_event.event_id] = queued_event

            self.logger.info(f"Loaded {len(self.event_queue)} queued events from {self.event_queue_path}")
        except Exception as e:
            self.logger.error(f"Error loading event queue: {e}")

    def _save_event_queue(self, path: Path):
        """Persist queued events to disk."""
        try:
            payload = {
                "node_id": self.node_id,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "events": [
                    {
                        "event": qe.event.to_dict(),
                        "event_id": qe.event_id,
                        "queued_at": qe.queued_at.isoformat(),
                        "delivered_to": list(qe.delivered_to),
                        "confirmed_by": list(qe.confirmed_by)
                    }
                    for qe in self.event_queue
                ]
            }

            temp_path = path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(payload, f, indent=2)
            temp_path.replace(path)
        except Exception as e:
            self.logger.error(f"Error saving event queue: {e}")
    
    def get_profile(self) -> LegacyNodeProfile:
        """Get legacy node profile (pre-Phase 1 format)."""
        capabilities = ["events", "bundles", "manifests"]

        endpoints = {}
        if self.node_type == "FULL" and self.port:
            base_url = f"http://localhost:{self.port}"
            endpoints = {
                "events_broadcast": f"{base_url}/events/broadcast",
                "events_poll": f"{base_url}/events/poll",
                "bundles_fetch": f"{base_url}/bundles/fetch",
                "manifests_fetch": f"{base_url}/manifests/fetch",
                "rids_fetch": f"{base_url}/rids/fetch",
                "health": f"{base_url}/health"
            }

        return LegacyNodeProfile(
            node_id=self.node_id,
            node_name=self.node_name,
            node_type=self.node_type,
            version="1.0.0",
            capabilities=capabilities,
            endpoints=endpoints,
            metadata={
                "started_at": datetime.now(timezone.utc).isoformat(),
                "cache_size": len(self.cache),
                "event_queue_size": len(self.event_queue),
                "pending_deliveries": len(self.pending_deliveries)
            }
        )

    def to_koi_net_profile(self) -> KoiNetNodeProfile:
        """Build a BlockScience-compatible NodeProfile for this node.

        Returns a Pydantic model that can be serialized as Bundle contents
        for peer discovery.  The profile contains:
        - base_url: for FULL nodes, the /koi-net endpoint root
        - node_type: FULL or PARTIAL
        - provides: RID types this node offers
        - public_key: base64 DER if configured
        """
        node_type = NodeType.FULL if self.node_type == "FULL" else NodeType.PARTIAL

        base_url = None
        if node_type == NodeType.FULL and self.port:
            base_url = f"http://localhost:{self.port}/koi-net"

        # Public key: prefer key-derived (Phase 5), fall back to env var
        public_key = None
        if self.public_key:
            try:
                from shared.koi_envelope import public_key_to_b64der
                public_key = public_key_to_b64der(self.public_key)
            except Exception:
                pass
        if not public_key:
            public_key = os.getenv("KOI_PUBLIC_KEY_B64")

        # Declare RID types this coordinator provides (Phase 2)
        provides = NodeProvides(
            event=[
                "orn:twitter.tweet",
                "orn:discourse.post",
                "orn:web.page",
                "orn:notion.page",
                "orn:github.file",
                "orn:youtube.video",
                "orn:gmail.message",
                "orn:gmail.attachment",
            ],
            state=[
                "orn:koi-net.node",
                "orn:koi-net.edge",
            ],
        )

        return KoiNetNodeProfile(
            base_url=base_url,
            node_type=node_type,
            provides=provides,
            public_key=public_key,
        )
    
    # Cache operations
    def cache_bundle(self, bundle: Bundle):
        """Cache a bundle (memory + disk if persistent cache enabled)"""
        self.cache[bundle.rid] = bundle
        # Write-through to disk (P2a)
        if self._persistent_cache:
            try:
                self._persistent_cache.write(bundle)
            except Exception as e:
                self.logger.warning(f"Failed to persist bundle {bundle.rid}: {e}")
        self.logger.debug(f"Cached bundle: {bundle.rid}")

    def get_cached_bundle(self, rid: str) -> Optional[Bundle]:
        """Get cached bundle by RID (memory first, then disk)"""
        bundle = self.cache.get(rid)
        if bundle:
            return bundle
        # Try persistent cache (P2a)
        if self._persistent_cache:
            try:
                bundle = self._persistent_cache.read(rid)
                if bundle:
                    # Populate memory cache
                    self.cache[rid] = bundle
                    return bundle
            except Exception as e:
                self.logger.debug(f"Failed to read bundle {rid} from disk: {e}")
        return None

    def has_cached_bundle(self, rid: str) -> bool:
        """Check if bundle is cached (memory or disk)"""
        if rid in self.cache:
            return True
        if self._persistent_cache:
            return self._persistent_cache.exists(rid)
        return False

    def remove_cached_bundle(self, rid: str) -> bool:
        """Remove bundle from cache (memory + disk)"""
        deleted = False
        if rid in self.cache:
            del self.cache[rid]
            deleted = True
        # Also delete from persistent cache (P2a)
        if self._persistent_cache:
            try:
                if self._persistent_cache.delete(rid):
                    deleted = True
            except Exception as e:
                self.logger.warning(f"Failed to delete bundle {rid} from disk: {e}")
        if deleted:
            self.logger.debug(f"Removed cached bundle: {rid}")
        return deleted

    def get_cached_rids(self) -> List[str]:
        """Get list of cached RIDs (from memory cache, which is synced with disk on startup)"""
        return list(self.cache.keys())
    
    # Event operations
    def queue_event(self, event: KOIEvent) -> str:
        """Queue an event for processing"""
        event_id = str(uuid.uuid4())
        queued_event = QueuedEvent(
            event=event,
            event_id=event_id,
            queued_at=datetime.now(timezone.utc),
            delivered_to=set(),
            confirmed_by=set()
        )
        self.event_queue.append(queued_event)
        self.pending_deliveries[event_id] = queued_event
        self.logger.debug(f"Queued {event.event_type} event for {event.rid} with ID {event_id}")
        self._persist_event_queue()
        return event_id
    
    def get_queued_events(self, max_events: int = None) -> List[KOIEvent]:
        """Get queued events"""
        events = [qe.event for qe in self.event_queue]
        if max_events:
            return events[:max_events]
        return events

    def get_queued_events_for_delivery(self, node_id: str, max_events: int = None) -> Tuple[List[KOIEvent], List[str]]:
        """Get queued events for a specific node, returning events and their IDs"""
        events = []
        event_ids = []

        count = 0
        for queued_event in self.event_queue:
            if max_events and count >= max_events:
                break

            # Only include events that haven't been delivered to this node yet
            if node_id not in queued_event.delivered_to:
                events.append(queued_event.event)
                event_ids.append(queued_event.event_id)
                # Mark as delivered to this node
                queued_event.delivered_to.add(node_id)
                count += 1

        self.logger.debug(f"Delivering {len(events)} events to {node_id}")
        if events:
            self._persist_event_queue()
        return events, event_ids
    
    def clear_event_queue(self, max_events: int = None):
        """Clear processed events from queue (legacy method - use confirm_delivery instead)"""
        if max_events:
            self.event_queue = self.event_queue[max_events:]
        else:
            self.event_queue.clear()

    def confirm_delivery(self, node_id: str, event_ids: List[str]) -> int:
        """Confirm delivery of events by a node"""
        confirmed_count = 0

        for event_id in event_ids:
            queued_event = self.pending_deliveries.get(event_id)
            if queued_event:
                queued_event.confirmed_by.add(node_id)
                confirmed_count += 1
                self.logger.debug(f"Node {node_id} confirmed receipt of event {event_id}")

        # Clean up fully confirmed events
        self._cleanup_confirmed_events()

        self._persist_event_queue()
        return confirmed_count

    def _cleanup_confirmed_events(self):
        """Remove events that have been confirmed by all nodes that received them"""
        events_to_remove = []

        for queued_event in self.event_queue:
            # An event can be removed if:
            # 1. It has been delivered to at least one node, AND
            # 2. All nodes that received it have confirmed receipt
            if (queued_event.delivered_to and
                queued_event.delivered_to.issubset(queued_event.confirmed_by)):
                events_to_remove.append(queued_event)

        for event_to_remove in events_to_remove:
            self.event_queue.remove(event_to_remove)
            self.pending_deliveries.pop(event_to_remove.event_id, None)
            self.logger.debug(f"Removed confirmed event {event_to_remove.event_id} from queue")

        if events_to_remove:
            self.logger.info(f"Cleaned up {len(events_to_remove)} confirmed events")
            self._persist_event_queue()

    def _cleanup_expired_events(self):
        """Remove events that have exceeded the delivery timeout"""
        current_time = datetime.now(timezone.utc)
        events_to_remove = []

        for queued_event in self.event_queue:
            age_seconds = (current_time - queued_event.queued_at).total_seconds()
            if age_seconds > self.delivery_timeout_seconds:
                events_to_remove.append(queued_event)
                self.logger.warning(f"Event {queued_event.event_id} expired after {age_seconds}s")

        for event_to_remove in events_to_remove:
            self.event_queue.remove(event_to_remove)
            self.pending_deliveries.pop(event_to_remove.event_id, None)

        if events_to_remove:
            self.logger.info(f"Cleaned up {len(events_to_remove)} expired events")
            self._persist_event_queue()
    
    # Abstract methods for node-specific behavior
    @abstractmethod
    async def handle_event(self, event: KOIEvent):
        """Handle incoming KOI event"""
        pass
    
    @abstractmethod
    async def broadcast_event(self, event: KOIEvent):
        """Broadcast event to network"""
        pass


class KOIPartialNode(KOINodeBase):
    """Partial KOI Node - polls coordinator for events"""
    
    def __init__(self, node_name: str, coordinator_url: str, poll_interval: int = 30):
        super().__init__(node_name, "PARTIAL")
        self.coordinator_url = coordinator_url
        self.poll_interval = poll_interval
        self.coordinator_node_id = os.getenv("KOI_COORDINATOR_NODE_ID")
        self.envelope_private_key = None
        self.envelope_sign = False
        self.envelope_public_keys = {}
        self.envelope_verify = False
        self._configure_envelope_signing()

    def _configure_envelope_signing(self):
        from shared.koi_envelope import load_private_key_from_env, load_public_keys_from_env

        self.envelope_private_key = load_private_key_from_env()
        self.envelope_public_keys = load_public_keys_from_env()
        sign_env = os.getenv("KOI_ENVELOPE_SIGN")
        if self.envelope_private_key and (sign_env is None or sign_env.lower() not in ("0", "false", "no")):
            self.envelope_sign = True
        verify_env = os.getenv("KOI_ENVELOPE_VERIFY")
        if self.envelope_public_keys and (verify_env is None or verify_env.lower() not in ("0", "false", "no")):
            self.envelope_verify = True
    
    async def handle_event(self, event: KOIEvent):
        """Handle event received from coordinator"""
        self.logger.info(f"Handling {event.event_type} event for {event.rid}")
        
        if event.event_type in ["NEW", "UPDATE"] and event.bundle:
            # Cache the bundle
            self.cache_bundle(event.bundle)
        elif event.event_type == "FORGET":
            # Remove from cache
            self.remove_cached_bundle(event.rid)
    
    async def broadcast_event(self, event: KOIEvent):
        """Send event to coordinator"""
        self.logger.info(f"broadcast_event called for {event.event_type} event, RID: {event.rid}")
        if not self.session:
            self.logger.error("No active session for broadcasting")
            return False
        
        url = f"{self.coordinator_url}/events/broadcast"
        self.logger.info(f"POSTing to {url}")

        payload = event.to_dict()
        if self.envelope_sign:
            from shared.koi_envelope import sign_envelope
            target_node = self.coordinator_node_id or "coordinator"
            payload = sign_envelope(payload, self.node_id, target_node, self.envelope_private_key)
        
        try:
            async with self.session.post(
                url,
                json=payload,
                timeout=30
            ) as response:
                if response.status == 200:
                    self.logger.info(f"Successfully broadcast {event.event_type} event for {event.rid}")
                    return True
                else:
                    text = await response.text()
                    self.logger.error(f"Failed to broadcast event: {response.status} - {text}")
                    return False
        except Exception as e:
            self.logger.error(f"Error broadcasting event: {e}")
            return False
    
    async def polling_loop(self):
        """Poll coordinator for new events"""
        self.logger.info(f"Starting polling loop (interval: {self.poll_interval}s)")
        
        while self.running:
            try:
                await self.poll_for_events()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                self.logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(60)  # Wait longer after errors
    
    async def poll_for_events(self):
        """Poll coordinator for new events"""
        if not self.session:
            return
        
        try:
            payload = {
                "type": "poll_events",
                "limit": 50,
                "node_id": self.node_id
            }
            if self.envelope_sign:
                from shared.koi_envelope import sign_envelope
                target_node = self.coordinator_node_id or "coordinator"
                payload = sign_envelope(payload, self.node_id, target_node, self.envelope_private_key)

            async with self.session.post(
                f"{self.coordinator_url}/events/poll",
                json=payload,
                timeout=30
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and "payload" in data:
                        if self.envelope_verify:
                            from shared.koi_envelope import verify_envelope
                            data, _source_node = verify_envelope(
                                data,
                                self.envelope_public_keys,
                                expected_target=self.node_id,
                                enforce_target=True
                            )
                        else:
                            data = data.get("payload", {})

                    events = []
                    for event_data in data.get("events", []):
                        if "bundle" in event_data:
                            events.append(KOIEvent.from_dict(event_data))
                        else:
                            events.append(KOIEvent.from_dict({
                                "event_type": event_data.get("event_type"),
                                "rid": event_data.get("rid"),
                                "timestamp": event_data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                                "source_node": event_data.get("source_node", "unknown"),
                                "bundle": {
                                    "rid": event_data.get("rid"),
                                    "manifest": event_data.get("manifest"),
                                    "contents": event_data.get("contents")
                                } if event_data.get("manifest") or event_data.get("contents") else None
                            }))
                    
                    for event in events:
                        await self.handle_event(event)
                    
                    if events:
                        self.logger.info(f"Processed {len(events)} events from coordinator")
        except Exception as e:
            self.logger.error(f"Error polling for events: {e}")
    
    async def emit_new_event(self, bundle: Bundle):
        """Emit NEW event for a bundle"""
        self.logger.info(f"emit_new_event called for bundle RID: {bundle.rid}")
        event = KOIEvent.new_event(bundle, self.node_id)
        self.queue_event(event)
        self.logger.info(f"About to broadcast NEW event for RID: {event.rid}")
        success = await self.broadcast_event(event)
        self.logger.info(f"Finished broadcasting NEW event for RID: {event.rid}")
        return success
    
    async def emit_update_event(self, bundle: Bundle):
        """Emit UPDATE event for a bundle"""
        event = KOIEvent.update_event(bundle, self.node_id)
        self.queue_event(event)
        return await self.broadcast_event(event)
    
    async def emit_forget_event(self, rid: RID, reason: str = None):
        """Emit FORGET event for a RID"""
        event = KOIEvent.forget_event(rid, self.node_id, reason)
        self.queue_event(event)
        return await self.broadcast_event(event)


class KOIFullNode(KOINodeBase):
    """Full KOI Node - implements complete KOI-net protocol"""

    def __init__(self, node_name: str, port: int = 8000, cache_dir: str = None):
        super().__init__(node_name, "FULL", port, cache_dir=cache_dir)
        self.app = None  # Will be set when starting web server

        # Network state
        self.connected_nodes: Set[str] = set()
        self.event_subscribers: Set[str] = set()

        # Cleanup task
        self.cleanup_task: Optional[asyncio.Task] = None
    
    async def handle_event(self, event: KOIEvent):
        """Handle event from another node"""
        self.logger.info(f"Handling {event.event_type} event for {event.rid}")
        
        if event.event_type in ["NEW", "UPDATE"] and event.bundle:
            # Cache the bundle
            self.cache_bundle(event.bundle)
        elif event.event_type == "FORGET":
            # Remove from cache
            self.remove_cached_bundle(event.rid)
        
        # Forward event to subscribers
        await self.forward_event_to_subscribers(event)
    
    async def broadcast_event(self, event: KOIEvent):
        """Broadcast event to connected nodes"""
        self.logger.info(f"Broadcasting {event.event_type} event for {event.rid}")
        
        # Queue event for polling nodes
        self.queue_event(event)
        
        # Forward to other full nodes
        await self.forward_event_to_network(event)
    
    async def forward_event_to_subscribers(self, event: KOIEvent):
        """Forward event to subscribed nodes"""
        # Implementation depends on subscriber management
        pass
    
    async def forward_event_to_network(self, event: KOIEvent):
        """Forward event to other nodes in network"""
        # Implementation depends on network topology
        pass
    
    def add_event_subscriber(self, node_id: str):
        """Add node as event subscriber"""
        self.event_subscribers.add(node_id)
        self.logger.info(f"Added event subscriber: {node_id}")
    
    def remove_event_subscriber(self, node_id: str):
        """Remove node as event subscriber"""
        self.event_subscribers.discard(node_id)
        self.logger.info(f"Removed event subscriber: {node_id}")

    async def _cleanup_loop(self):
        """Periodic cleanup of expired and confirmed events"""
        while self.running:
            try:
                self._cleanup_confirmed_events()
                self._cleanup_expired_events()
                await asyncio.sleep(60)  # Run cleanup every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)
    
    # Web server methods (to be implemented with FastAPI or similar)
    async def start_web_server(self):
        """Start web server for KOI-net endpoints"""
        # Implementation depends on web framework choice
        pass

    def get_delivery_stats(self) -> Dict[str, Any]:
        """Get statistics about event delivery"""
        total_events = len(self.event_queue)
        pending_events = len(self.pending_deliveries)
        delivered_events = sum(1 for qe in self.event_queue if qe.delivered_to)
        confirmed_events = sum(1 for qe in self.event_queue if qe.confirmed_by)

        return {
            "total_queued_events": total_events,
            "pending_deliveries": pending_events,
            "delivered_events": delivered_events,
            "confirmed_events": confirmed_events,
            "subscribers": list(self.event_subscribers)
        }
