"""
Shared Persistent State Management for KOI Sensors
Provides deterministic, restart-safe crawling capabilities
"""

import json
import logging
from pathlib import Path
from typing import Dict, Set, Any, Optional
from datetime import datetime, timezone


class PersistentSensorState:
    """
    Manages persistent state for sensors to enable deterministic crawling
    that survives restarts and ensures complete data collection.

    Features:
    - Persistent queue of items to process
    - Tracking of processed items to avoid duplicates
    - Progress counters per source
    - Automatic save/load from JSON
    """

    def __init__(self, sensor_name: str, state_dir: Optional[Path] = None):
        """
        Initialize persistent state manager

        Args:
            sensor_name: Name of the sensor (e.g., 'discourse', 'podcast')
            state_dir: Directory to store state files (defaults to sensor directory)
        """
        self.sensor_name = sensor_name
        self.logger = logging.getLogger(f"koi.sensor.{sensor_name}.state")

        # Set state file path
        if state_dir is None:
            state_dir = Path.cwd()
        self.state_file = state_dir / f"{sensor_name}_sensor_state.json"

        # State data structures
        self.queues: Dict[str, Set[str]] = {}  # source -> set of item IDs to process
        self.processed: Set[str] = set()  # All processed item IDs
        self.pending: Dict[str, Set[str]] = {}  # source -> items sent but not yet confirmed
        self.counters: Dict[str, int] = {}  # source -> count of items processed
        self.metadata: Dict[str, Any] = {}  # Additional metadata

        # Load existing state if available
        self.load()

    def load(self):
        """Load state from JSON file"""
        if not self.state_file.exists():
            self.logger.info(f"No previous state file found at {self.state_file}, starting fresh")
            return

        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)

            # Restore queues (convert lists back to sets)
            self.queues = {
                source: set(items)
                for source, items in data.get('queues', {}).items()
            }

            # Restore processed set
            self.processed = set(data.get('processed', []))

            # Restore pending set (support legacy list format)
            pending_data = data.get('pending', {})
            if isinstance(pending_data, dict):
                self.pending = {
                    source: set(items)
                    for source, items in pending_data.items()
                }
            elif isinstance(pending_data, list):
                self.pending = {"_legacy": set(pending_data)}

            # Restore counters
            self.counters = data.get('counters', {})

            # Restore metadata
            self.metadata = data.get('metadata', {})

            total_queued = sum(len(q) for q in self.queues.values())
            self.logger.info(
                f"Loaded state: {len(self.queues)} sources, "
                f"{len(self.processed)} processed, "
                f"{sum(len(items) for items in self.pending.values())} pending, "
                f"{total_queued} queued"
            )

        except Exception as e:
            self.logger.error(f"Error loading state from {self.state_file}: {e}")

    def save(self):
        """Save state to JSON file"""
        try:
            data = {
                'queues': {
                    source: list(items)
                    for source, items in self.queues.items()
                },
                'processed': list(self.processed),
                'pending': {
                    source: list(items)
                    for source, items in self.pending.items()
                },
                'counters': self.counters,
                'metadata': self.metadata,
                'last_saved': datetime.now(timezone.utc).isoformat(),
                'sensor': self.sensor_name
            }

            # Write atomically (write to temp file, then rename)
            temp_file = self.state_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.state_file)

            total_queued = sum(len(q) for q in self.queues.values())
            self.logger.debug(
                f"Saved state: {len(self.queues)} sources, "
                f"{len(self.processed)} processed, "
                f"{sum(len(items) for items in self.pending.values())} pending, "
                f"{total_queued} queued"
            )

        except Exception as e:
            self.logger.error(f"Error saving state to {self.state_file}: {e}")

    def add_to_queue(self, source: str, item_id: str):
        """
        Add item to processing queue if not already processed

        Args:
            source: Source identifier (e.g., forum name, podcast feed)
            item_id: Unique identifier for the item
        """
        if item_id not in self.processed:
            if source not in self.queues:
                self.queues[source] = set()
            self.queues[source].add(item_id)

    def add_many_to_queue(self, source: str, item_ids: Set[str]):
        """
        Add multiple items to queue at once

        Args:
            source: Source identifier
            item_ids: Set of item IDs to add
        """
        if source not in self.queues:
            self.queues[source] = set()
        # Only add items not already processed
        new_items = item_ids - self.processed
        self.queues[source].update(new_items)

    def mark_processed(self, source: str, item_id: str):
        """
        Mark item as processed and increment counter

        Args:
            source: Source identifier
            item_id: Item ID that was processed
        """
        self.processed.add(item_id)
        if source in self.pending:
            self.pending[source].discard(item_id)

        # Remove from queue if present
        if source in self.queues:
            self.queues[source].discard(item_id)

        # Increment counter
        if source not in self.counters:
            self.counters[source] = 0
        self.counters[source] += 1

    def is_processed(self, item_id: str) -> bool:
        """Check if item has already been processed"""
        return item_id in self.processed

    def mark_pending(self, source: str, item_id: str):
        """
        Mark item as pending confirmation after emission.

        Removes from queue to avoid immediate re-processing.
        """
        if source not in self.pending:
            self.pending[source] = set()
        self.pending[source].add(item_id)
        if source in self.queues:
            self.queues[source].discard(item_id)

    def clear_pending(self, source: str, item_id: str):
        """Remove item from pending set (used when send fails)."""
        if source in self.pending:
            self.pending[source].discard(item_id)

    def is_pending(self, item_id: str) -> bool:
        """Check if item is awaiting confirmation"""
        return any(item_id in items for items in self.pending.values())

    def get_queue(self, source: str) -> Set[str]:
        """Get queue for a specific source"""
        return self.queues.get(source, set())

    def get_queue_size(self, source: str) -> int:
        """Get size of queue for a source"""
        return len(self.queues.get(source, set()))

    def get_processed_count(self, source: str) -> int:
        """Get count of processed items for a source"""
        return self.counters.get(source, 0)

    def clear_source(self, source: str):
        """Clear all state for a specific source"""
        if source in self.queues:
            del self.queues[source]
        if source in self.counters:
            del self.counters[source]
        if source in self.pending:
            del self.pending[source]
        self.logger.info(f"Cleared state for source: {source}")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about current state"""
        return {
            'sources': len(self.queues),
            'total_processed': len(self.processed),
            'total_pending': sum(len(items) for items in self.pending.values()),
            'total_queued': sum(len(q) for q in self.queues.values()),
            'by_source': {
                source: {
                    'queued': len(self.queues.get(source, set())),
                    'processed': self.counters.get(source, 0),
                    'pending': len(self.pending.get(source, set()))
                }
                for source in set(list(self.queues.keys()) + list(self.counters.keys()))
            }
        }
