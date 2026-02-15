"""
KOI Protocol - Default Handlers (Regen-Specific)

Phase 3: Extracted from coordinator inline logic into registered handler functions.
Each handler's logic is lifted as-is from koi_coordinator.py broadcast_event().

Handler chain order:
  RID:     heartbeat_handler, bundle_normalization_handler
  Bundle:  sensor_tracking_handler, dedup_handler, cat_receipt_handler
  Network: event_emission_handler
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .handler import HandlerType, KnowledgeHandler, STOP_CHAIN
from .knowledge_object import KnowledgeObject


# ===========================================================================
# RID Phase Handlers
# ===========================================================================

@KnowledgeHandler.create(HandlerType.RID)
def heartbeat_handler(coordinator: Any, kobj: KnowledgeObject):
    """Detect sensor heartbeats from raw event data.

    Checks raw_event_data["data"]["type"] == "sensor_heartbeat" (matching
    current behavior at koi_coordinator.py L475). Updates coordinator's
    sensor_monitoring state. Does NOT stop the chain — current behavior
    is additive (heartbeat is detected AND event continues processing).
    """
    raw = kobj.raw_event_data or {}
    data = raw.get("data")
    if not (isinstance(data, dict) and data.get("type") == "sensor_heartbeat"):
        return None  # pass through

    sensor_id = data.get("sensor_id")
    monitoring = data.get("monitoring", [])
    if sensor_id and monitoring:
        coordinator.sensor_monitoring[sensor_id] = monitoring

    # Note: heartbeat events still continue through the pipeline in current behavior.
    # They have a bundle and go through dedup/emit like any other event.
    return None


@KnowledgeHandler.create(HandlerType.RID)
def bundle_normalization_handler(coordinator: Any, kobj: KnowledgeObject):
    """Create Bundle from raw sensor 'data' field if no bundle present.

    Matches koi_coordinator.py L488-528: when event has 'data' but no 'bundle',
    creates a Manifest + Bundle from the sensor data.
    """
    # If bundle already present (manifest + contents set), pass through
    if kobj.manifest is not None and kobj.contents is not None:
        return None

    # If there's bundle data in raw_event_data, it was already parsed
    raw = kobj.raw_event_data or {}
    if raw.get("bundle"):
        return None

    # Check for raw 'data' field that needs bundle creation
    sensor_data = raw.get("data")
    if not isinstance(sensor_data, dict):
        return None

    from ..core.bundle_system import Bundle, Manifest

    content_str = json.dumps(sensor_data, sort_keys=True)
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()

    manifest = Manifest(
        rid=kobj.rid,
        timestamp=raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        sha256_hash=content_hash,
        size_bytes=len(content_str.encode()),
        content_type="application/json",
        version="1.0",
        metadata=sensor_data.get("metadata", {}),
    )

    kobj.manifest = manifest
    kobj.contents = sensor_data
    return kobj


# ===========================================================================
# Bundle Phase Handlers
# ===========================================================================

@KnowledgeHandler.create(HandlerType.Bundle)
def sensor_tracking_handler(coordinator: Any, kobj: KnowledgeObject):
    """Track broadcast sensors by type, update registry.

    Matches koi_coordinator.py L540-575: extracts sensor_type from source_node
    using regex pattern, updates broadcast_sensors dict.
    """
    source_node = kobj.source
    if not source_node:
        return None

    # Extract sensor type (e.g., "website-sensor-12345" → "website-sensor")
    sensor_type_match = re.match(r'^(.*?-sensor)', source_node)
    if sensor_type_match:
        sensor_type = sensor_type_match.group(1)
    else:
        sensor_type = source_node.split('-')[0] if '-' in source_node else source_node

    current_time = datetime.now(timezone.utc)
    if sensor_type in coordinator.broadcast_sensors:
        coordinator.broadcast_sensors[sensor_type]["node_id"] = source_node
        coordinator.broadcast_sensors[sensor_type]["last_event"] = current_time.isoformat()
        coordinator.broadcast_sensors[sensor_type]["event_count"] += 1
        coordinator.broadcast_sensors[sensor_type]["status"] = "active"
    else:
        coordinator.broadcast_sensors[sensor_type] = {
            "node_id": source_node,
            "sensor_type": sensor_type,
            "last_event": current_time.isoformat(),
            "event_count": 1,
            "event_type": kobj.event_type or "unknown",
            "status": "active",
        }
        coordinator._save_sensor_registry()

    return None


@KnowledgeHandler.create(HandlerType.Bundle)
def dedup_handler(coordinator: Any, kobj: KnowledgeObject):
    """Check content hash for duplicates, return STOP_CHAIN if duplicate.

    Matches koi_coordinator.py L577-589: checks content hash against
    coordinator's dedup state. Podcasts bypass dedup.
    """
    if not (kobj.manifest and kobj.rid):
        return None

    content_hash = kobj.manifest.content_hash if kobj.manifest else ""
    metadata = kobj.manifest.metadata if kobj.manifest else {}
    source_url = None
    if isinstance(metadata, dict):
        source_url = metadata.get("url") or metadata.get("source_url")

    # Podcasts bypass dedup (matches current behavior)
    is_duplicate = False if "podcast" in kobj.rid else coordinator._check_duplicate_content(
        kobj.rid, content_hash, source_url
    )

    if is_duplicate:
        kobj.result_status = "skipped_duplicate"
        return STOP_CHAIN

    return None


@KnowledgeHandler.create(HandlerType.Bundle)
async def cat_receipt_handler(coordinator: Any, kobj: KnowledgeObject):
    """Create CAT receipts for sensor collection (async, best-effort).

    Matches koi_coordinator.py L591-631: imports receipt manager, creates
    collection and forwarding receipts. Failures don't stop the pipeline.
    """
    if not (kobj.manifest and kobj.rid):
        return None

    try:
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), '../../../koi-processor/src'))
        from cat.coordinator_receipt_integration import CoordinatorReceiptManager

        receipt_manager = CoordinatorReceiptManager()

        sensor_name = kobj.source or "unknown"
        content_hash = kobj.manifest.content_hash if kobj.manifest else ""
        metadata = kobj.manifest.metadata if kobj.manifest and isinstance(kobj.manifest.metadata, dict) else {}

        collection_receipt = await receipt_manager.create_sensor_collection_receipt(
            sensor_name=sensor_name,
            rid=kobj.rid,
            sha256_hash=content_hash,
            source_url=metadata.get("url"),
            document_count=1,
            metadata=metadata,
        )

        forwarding_receipt = await receipt_manager.create_coordinator_forwarding_receipt(
            input_rid=kobj.rid,
            output_rid=kobj.rid,
            target_service="event-bridge",
            sensor_name=sensor_name,
            event_type=kobj.event_type,
            metadata={"collection_receipt": collection_receipt},
        )

        coordinator.logger.info(
            f"Created CAT receipts - collection: {collection_receipt}, forwarding: {forwarding_receipt}"
        )

        await receipt_manager.close()

    except Exception as e:
        coordinator.logger.warning(f"Could not create CAT receipts: {e}")

    return None


# ===========================================================================
# Network Phase Handlers
# ===========================================================================

@KnowledgeHandler.create(HandlerType.Network)
async def event_emission_handler(coordinator: Any, kobj: KnowledgeObject):
    """Build KOIEvent from canonical kobj fields and emit via handle_event + broadcast_event.

    Single emission path — builds KOIEvent from kobj.rid, kobj.manifest, kobj.contents,
    kobj.event_type, kobj.source (NOT from raw_event_data). This ensures mutations from
    earlier handlers (bundle normalization) are captured.

    Matches koi_coordinator.py L634-638.
    """
    from ..core.bundle_system import KOIEvent

    event_data = {
        "event_type": kobj.event_type or "NEW",
        "rid": kobj.rid,
        "timestamp": kobj.manifest.timestamp if kobj.manifest else datetime.now(timezone.utc).isoformat(),
        "source_node": kobj.source or "unknown",
    }
    if kobj.manifest and kobj.contents:
        event_data["bundle"] = {
            "rid": kobj.rid,
            "manifest": kobj.manifest.to_dict(),
            "contents": kobj.contents,
        }

    event = KOIEvent.from_dict(event_data)
    await coordinator.koi_node.handle_event(event)
    await coordinator.koi_node.broadcast_event(event)

    kobj.result_status = "success"
    return kobj
