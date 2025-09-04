"""
KOI Protocol - Node Implementation
Base classes for Full and Partial KOI nodes following KOI-net specification
"""

import asyncio
import json
import aiohttp
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import logging

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
        self.event_queue: List[KOIEvent] = []
        self.known_nodes: Dict[str, NodeContact] = {}
        
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
    
    async def stop(self):
        """Stop the node"""
        self.logger.info(f"Stopping node: {self.node_name}")
        self.running = False
        
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
                "event_queue_size": len(self.event_queue)
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
    def queue_event(self, event: KOIEvent):
        """Queue an event for processing"""
        self.event_queue.append(event)
        self.logger.debug(f"Queued {event.event_type} event for {event.rid}")
    
    def get_queued_events(self, max_events: int = None) -> List[KOIEvent]:
        """Get queued events"""
        if max_events:
            return self.event_queue[:max_events]
        return self.event_queue.copy()
    
    def clear_event_queue(self, max_events: int = None):
        """Clear processed events from queue"""
        if max_events:
            self.event_queue = self.event_queue[max_events:]
        else:
            self.event_queue.clear()
    
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
        if not self.session:
            self.logger.error("No active session for broadcasting")
            return
        
        try:
            async with self.session.post(
                f"{self.coordinator_url}/events/broadcast",
                json=event.to_dict(),
                timeout=30
            ) as response:
                if response.status == 200:
                    self.logger.debug(f"Broadcast {event.event_type} event for {event.rid}")
                else:
                    self.logger.error(f"Failed to broadcast event: {response.status}")
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
        event = KOIEvent.new_event(bundle, self.node_id)
        self.queue_event(event)
        await self.broadcast_event(event)
    
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
    
    # Web server methods (to be implemented with FastAPI or similar)
    async def start_web_server(self):
        """Start web server for KOI-net endpoints"""
        # Implementation depends on web framework choice
        pass