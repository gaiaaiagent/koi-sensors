#!/usr/bin/env python3
"""
Phase 3 Session 3.2: Default Handler Tests

Tests for each Regen-specific handler extracted from coordinator inline logic.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json
import hashlib
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from koi_protocol.processor import (
    HandlerType,
    KnowledgeHandler,
    KnowledgeObject,
    PipelineStop,
    STOP_CHAIN,
)
from koi_protocol.processor.handler import StopChain
from koi_protocol.processor.default_handlers import (
    heartbeat_handler,
    bundle_normalization_handler,
    sensor_tracking_handler,
    dedup_handler,
    cat_receipt_handler,
    event_emission_handler,
)
from koi_protocol.core.bundle_system import Manifest

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


@pytest.fixture
def mock_coordinator():
    coord = MagicMock()
    coord.sensor_monitoring = {}
    coord.broadcast_sensors = {}
    coord._save_sensor_registry = MagicMock()
    coord._check_duplicate_content = MagicMock(return_value=False)
    coord.koi_node = MagicMock()
    coord.koi_node.handle_event = AsyncMock()
    coord.koi_node.broadcast_event = AsyncMock()
    coord.logger = MagicMock()
    return coord


# ===========================================================================
# heartbeat_handler
# ===========================================================================

class TestHeartbeatHandler:
    def test_detects_sensor_heartbeat(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:hb",
            raw_event_data={
                "data": {
                    "type": "sensor_heartbeat",
                    "sensor_id": "website-sensor",
                    "monitoring": [{"url": "https://example.com"}],
                },
            },
        )
        result = heartbeat_handler.func(coordinator=mock_coordinator, kobj=kobj)
        # Heartbeat updates monitoring but does NOT stop chain (current behavior)
        assert result is None
        assert "website-sensor" in mock_coordinator.sensor_monitoring
        assert mock_coordinator.sensor_monitoring["website-sensor"] == [{"url": "https://example.com"}]

    def test_passes_through_no_data(self, mock_coordinator):
        kobj = KnowledgeObject(rid="orn:test:x")
        result = heartbeat_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is None
        assert mock_coordinator.sensor_monitoring == {}

    def test_passes_through_wrong_type(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:x",
            raw_event_data={"data": {"type": "not_heartbeat"}},
        )
        result = heartbeat_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is None

    def test_updates_monitoring_correctly(self, mock_coordinator):
        items = [{"url": "https://a.com"}, {"url": "https://b.com"}]
        kobj = KnowledgeObject(
            rid="orn:test:hb2",
            raw_event_data={
                "data": {
                    "type": "sensor_heartbeat",
                    "sensor_id": "discourse-sensor",
                    "monitoring": items,
                },
            },
        )
        heartbeat_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert mock_coordinator.sensor_monitoring["discourse-sensor"] == items


# ===========================================================================
# bundle_normalization_handler
# ===========================================================================

class TestBundleNormalizationHandler:
    def test_creates_bundle_from_data(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:bn1",
            raw_event_data={
                "rid": "orn:test:bn1",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": {"text": "sensor payload", "metric": 42},
            },
        )
        result = bundle_normalization_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is not None
        assert result.manifest is not None
        assert result.contents == {"text": "sensor payload", "metric": 42}

    def test_passes_through_pre_bundled(self, mock_coordinator):
        manifest = Manifest(
            rid="orn:test:bn2", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="abc", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:bn2",
            manifest=manifest,
            contents={"existing": True},
        )
        result = bundle_normalization_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is None  # pass through

    def test_updates_kobj_manifest_and_contents(self, mock_coordinator):
        sensor_data = {"key": "value"}
        kobj = KnowledgeObject(
            rid="orn:test:bn3",
            raw_event_data={
                "rid": "orn:test:bn3",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": sensor_data,
            },
        )
        result = bundle_normalization_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result.manifest.rid == "orn:test:bn3"
        expected_hash = hashlib.sha256(json.dumps(sensor_data, sort_keys=True).encode()).hexdigest()
        assert result.manifest.sha256_hash == expected_hash


# ===========================================================================
# sensor_tracking_handler
# ===========================================================================

class TestSensorTrackingHandler:
    def test_updates_broadcast_sensors(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:st1",
            source="website-sensor-abc123",
            event_type="NEW",
        )
        sensor_tracking_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert "website-sensor" in mock_coordinator.broadcast_sensors
        entry = mock_coordinator.broadcast_sensors["website-sensor"]
        assert entry["node_id"] == "website-sensor-abc123"
        assert entry["event_count"] == 1

    def test_handles_multi_word_sensors(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:st2",
            source="github-activity-sensor-xyz",
            event_type="NEW",
        )
        sensor_tracking_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert "github-activity-sensor" in mock_coordinator.broadcast_sensors

    def test_saves_registry_on_new_sensor(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:st3",
            source="new-sensor-001",
            event_type="NEW",
        )
        sensor_tracking_handler.func(coordinator=mock_coordinator, kobj=kobj)
        mock_coordinator._save_sensor_registry.assert_called_once()

    def test_increments_existing_sensor(self, mock_coordinator):
        mock_coordinator.broadcast_sensors["test-sensor"] = {
            "node_id": "test-sensor-001",
            "sensor_type": "test-sensor",
            "last_event": "2026-01-01T00:00:00Z",
            "event_count": 5,
            "status": "active",
        }
        kobj = KnowledgeObject(
            rid="orn:test:st4",
            source="test-sensor-002",
        )
        sensor_tracking_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert mock_coordinator.broadcast_sensors["test-sensor"]["event_count"] == 6
        assert mock_coordinator.broadcast_sensors["test-sensor"]["node_id"] == "test-sensor-002"


# ===========================================================================
# dedup_handler
# ===========================================================================

class TestDedupHandler:
    def test_returns_stop_chain_for_duplicate(self, mock_coordinator):
        mock_coordinator._check_duplicate_content.return_value = True
        manifest = Manifest(
            rid="orn:test:dd1", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="abc", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:dd1",
            manifest=manifest,
            contents={"text": "dup"},
        )
        result = dedup_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert isinstance(result, StopChain)
        assert kobj.result_status == "skipped_duplicate"

    def test_returns_none_for_new_content(self, mock_coordinator):
        mock_coordinator._check_duplicate_content.return_value = False
        manifest = Manifest(
            rid="orn:test:dd2", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="def", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:dd2",
            manifest=manifest,
            contents={"text": "new"},
        )
        result = dedup_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is None


# ===========================================================================
# cat_receipt_handler
# ===========================================================================

class TestCatReceiptHandler:
    async def test_doesnt_fail_pipeline_on_import_error(self, mock_coordinator):
        """CAT receipt handler should not fail the pipeline if imports fail."""
        manifest = Manifest(
            rid="orn:test:cat1", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="abc", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:cat1",
            manifest=manifest,
            contents={"text": "cat"},
            source="test-sensor-001",
        )
        # This will likely fail to import CoordinatorReceiptManager — that's fine
        result = await cat_receipt_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result is None  # handler returns None regardless of error


# ===========================================================================
# event_emission_handler
# ===========================================================================

class TestEventEmissionHandler:
    async def test_builds_event_from_canonical_fields(self, mock_coordinator):
        manifest = Manifest(
            rid="orn:test:emit1", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="abc", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:emit1",
            manifest=manifest,
            contents={"text": "emit"},
            event_type="NEW",
            source="test-sensor-001",
        )
        result = await event_emission_handler.func(coordinator=mock_coordinator, kobj=kobj)

        mock_coordinator.koi_node.handle_event.assert_called_once()
        mock_coordinator.koi_node.broadcast_event.assert_called_once()

        # Verify KOIEvent was built from canonical fields
        event = mock_coordinator.koi_node.handle_event.call_args[0][0]
        assert event.rid == "orn:test:emit1"
        assert event.event_type == "NEW"
        assert event.source_node == "test-sensor-001"

    async def test_calls_both_handle_and_broadcast(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:emit2",
            event_type="NEW",
            source="s1",
        )
        await event_emission_handler.func(coordinator=mock_coordinator, kobj=kobj)
        mock_coordinator.koi_node.handle_event.assert_called_once()
        mock_coordinator.koi_node.broadcast_event.assert_called_once()

    async def test_captures_bundle_normalization(self, mock_coordinator):
        """Event emission uses kobj.manifest/contents (not raw_event_data)."""
        manifest = Manifest(
            rid="orn:test:emit3", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="normalized_hash", size_bytes=20,
            content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:emit3",
            manifest=manifest,
            contents={"normalized": True},
            event_type="NEW",
            source="test-sensor",
            raw_event_data={"data": {"original": True}},
        )
        result = await event_emission_handler.func(coordinator=mock_coordinator, kobj=kobj)
        event = mock_coordinator.koi_node.handle_event.call_args[0][0]
        assert event.bundle is not None
        assert event.bundle.contents == {"normalized": True}

    async def test_sets_result_status_success(self, mock_coordinator):
        kobj = KnowledgeObject(
            rid="orn:test:emit4",
            event_type="NEW",
            source="s1",
        )
        result = await event_emission_handler.func(coordinator=mock_coordinator, kobj=kobj)
        assert result.result_status == "success"
