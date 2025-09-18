"""
KOI Protocol - Node Implementation
Base classes for Full and Partial KOI nodes following KOI-net specification
"""

import asyncio
import json
import aiohttp
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import logging
import uuid

from ..core.rid_system import RID
from ..core.bundle_system import Bundle, KOIEvent, Manifest


@dataclass
class NodeProfile:
    """KOI Node Profile"""
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

    def __init__(self, node_name: str, node_type: str, port: int = None):
        self.node_name = node_name
        self.node_type = node_type
        self.port = port
        self.node_id = f"{node_name}-{datetime.now().timestamp()}"

        # Node state
        self.running = False
        self.cache: Dict[str, Bundle] = {}
        self.event_queue: List[QueuedEvent] = []  # Changed to use QueuedEvent
        self.known_nodes: Dict[str, NodeContact] = {}

        # Event delivery tracking
        self.pending_deliveries: Dict[str, QueuedEvent] = {}  # event_id -> QueuedEvent
        self.delivery_timeout_seconds = 300  # 5 minutes

        # Logging
        self.logger = logging.getLogger(f"koi.node.{node_name}")

        # HTTP session
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """Start the node"""
        self.logger.info(f"Starting {self.node_type} node: {self.node_name}")
        self.running = True
        self.session = aiohttp.ClientSession()

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
    
    def get_profile(self) -> NodeProfile:
        """Get node profile"""
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
        
        return NodeProfile(
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
    
    # Cache operations
    def cache_bundle(self, bundle: Bundle):
        """Cache a bundle"""
        self.cache[bundle.rid] = bundle
        self.logger.debug(f"Cached bundle: {bundle.rid}")
    
    def get_cached_bundle(self, rid: str) -> Optional[Bundle]:
        """Get cached bundle by RID"""
        return self.cache.get(rid)
    
    def has_cached_bundle(self, rid: str) -> bool:
        """Check if bundle is cached"""
        return rid in self.cache
    
    def remove_cached_bundle(self, rid: str) -> bool:
        """Remove bundle from cache"""
        if rid in self.cache:
            del self.cache[rid]
            self.logger.debug(f"Removed cached bundle: {rid}")
            return True
        return False
    
    def get_cached_rids(self) -> List[str]:
        """Get list of cached RIDs"""
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
            return
        
        url = f"{self.coordinator_url}/events/broadcast"
        self.logger.info(f"POSTing to {url}")
        
        try:
            async with self.session.post(
                url,
                json=event.to_dict(),
                timeout=30
            ) as response:
                if response.status == 200:
                    self.logger.info(f"Successfully broadcast {event.event_type} event for {event.rid}")
                else:
                    text = await response.text()
                    self.logger.error(f"Failed to broadcast event: {response.status} - {text}")
        except Exception as e:
            self.logger.error(f"Error broadcasting event: {e}")
    
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
            params = {"node_id": self.node_id, "max_events": 50}
            async with self.session.get(
                f"{self.coordinator_url}/events/poll",
                params=params,
                timeout=30
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    events = [KOIEvent.from_dict(event_data) for event_data in data.get("events", [])]
                    
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
        await self.broadcast_event(event)
        self.logger.info(f"Finished broadcasting NEW event for RID: {event.rid}")
    
    async def emit_update_event(self, bundle: Bundle):
        """Emit UPDATE event for a bundle"""
        event = KOIEvent.update_event(bundle, self.node_id)
        self.queue_event(event)
        await self.broadcast_event(event)
    
    async def emit_forget_event(self, rid: RID, reason: str = None):
        """Emit FORGET event for a RID"""
        event = KOIEvent.forget_event(rid, self.node_id, reason)
        self.queue_event(event)
        await self.broadcast_event(event)


class KOIFullNode(KOINodeBase):
    """Full KOI Node - implements complete KOI-net protocol"""

    def __init__(self, node_name: str, port: int = 8000):
        super().__init__(node_name, "FULL", port)
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