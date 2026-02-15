#!/usr/bin/env python3
"""
TDD Tests for P1a KOI-net Strict Surface (Level 2 Interop)

These tests verify:
1. /koi-net/events/poll returns JCS-recomputed sha256_hash
2. Wire timestamps use Z suffix (not +00:00)
3. Wire format is schema-exact (no extra fields)
4. Internal /events/poll remains unchanged
5. Queue is read-only for /koi-net/* pollers

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
P1a Acceptance Criteria documented there.
"""

import sys
from pathlib import Path

# Add koi-sensors to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json
import hashlib
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

# Import the transformation functions and models
from koi_protocol.coordinator.koi_coordinator import (
    _timestamp_to_z_format,
    _to_koi_net_wire_event,
    KoiNetWireEvent,
    KoiNetWireManifest,
    KoiNetPollEventsRequest,
    KoiNetEventsPayloadResponse,
)
from koi_protocol.core.bundle_system import Bundle, KOIEvent, Manifest
from koi_protocol.core.rid_system import GenericRID


class TestTimestampZFormat:
    """Test timestamp conversion to Z suffix format."""

    def test_converts_plus_00_00_to_z(self):
        """Timestamps ending with +00:00 should be converted to Z."""
        ts = "2025-12-23T12:00:00+00:00"
        result = _timestamp_to_z_format(ts)
        assert result == "2025-12-23T12:00:00Z"

    def test_preserves_existing_z_suffix(self):
        """Timestamps already ending with Z should be preserved."""
        ts = "2025-12-23T12:00:00Z"
        result = _timestamp_to_z_format(ts)
        assert result == "2025-12-23T12:00:00Z"

    def test_handles_empty_string(self):
        """Empty strings should be returned as-is."""
        assert _timestamp_to_z_format("") == ""

    def test_handles_none(self):
        """None values should be returned as-is (falsy check)."""
        assert _timestamp_to_z_format(None) is None

    def test_handles_embedded_plus_00_00(self):
        """Embedded +00:00 in timestamp should be replaced."""
        ts = "2025-12-23T12:00:00.123456+00:00"
        result = _timestamp_to_z_format(ts)
        assert result == "2025-12-23T12:00:00.123456Z"


class TestKoiNetWireEventTransformation:
    """Test transformation from internal KOIEvent to strict wire format."""

    def _create_test_event(self, contents: dict, timestamp: str = None) -> KOIEvent:
        """Helper to create a test KOIEvent with bundle."""
        rid = GenericRID("test", "wire-transform")
        bundle = Bundle.generate(rid, contents)

        # Override timestamp if provided
        if timestamp:
            bundle.manifest.timestamp = timestamp

        return KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

    def test_wire_event_has_only_allowed_fields(self):
        """Wire event should have only {rid, event_type, manifest, contents}."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        # Convert to dict and check fields
        wire_dict = wire_event.model_dump()
        allowed_fields = {"rid", "event_type", "manifest", "contents"}
        assert set(wire_dict.keys()) == allowed_fields

    def test_wire_manifest_has_only_allowed_fields(self):
        """Wire manifest should have only {rid, timestamp, sha256_hash}."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        assert wire_event.manifest is not None
        manifest_dict = wire_event.manifest.model_dump()
        allowed_fields = {"rid", "timestamp", "sha256_hash"}
        assert set(manifest_dict.keys()) == allowed_fields

    def test_wire_event_excludes_source_node(self):
        """Wire event should NOT include source_node (it's in envelope)."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        wire_dict = wire_event.model_dump()
        assert "source_node" not in wire_dict

    def test_wire_event_excludes_event_timestamp(self):
        """Wire event should NOT include event-level timestamp (it's in manifest)."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        wire_dict = wire_event.model_dump()
        assert "timestamp" not in wire_dict

    def test_wire_manifest_excludes_size_bytes(self):
        """Wire manifest should NOT include size_bytes."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        manifest_dict = wire_event.manifest.model_dump()
        assert "size_bytes" not in manifest_dict

    def test_wire_manifest_excludes_content_type(self):
        """Wire manifest should NOT include content_type."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        manifest_dict = wire_event.manifest.model_dump()
        assert "content_type" not in manifest_dict

    def test_wire_manifest_excludes_metadata(self):
        """Wire manifest should NOT include metadata."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        manifest_dict = wire_event.manifest.model_dump()
        assert "metadata" not in manifest_dict

    def test_wire_manifest_excludes_legacy_content_hash(self):
        """Wire manifest should NOT include legacy_content_hash."""
        event = self._create_test_event({"key": "value"})
        wire_event = _to_koi_net_wire_event(event)

        manifest_dict = wire_event.manifest.model_dump()
        assert "legacy_content_hash" not in manifest_dict

    def test_wire_timestamp_uses_z_format(self):
        """Wire manifest timestamp should use Z suffix."""
        # Create event with +00:00 timestamp
        event = self._create_test_event(
            {"key": "value"},
            timestamp="2025-12-23T12:00:00+00:00"
        )
        wire_event = _to_koi_net_wire_event(event)

        assert wire_event.manifest.timestamp.endswith("Z")
        assert not wire_event.manifest.timestamp.endswith("+00:00")


class TestKoiNetPollReturnsJCSHash:
    """Test that /koi-net/events/poll returns rid-lib JCS-computed sha256_hash."""

    def test_sha256_hash_matches_ridlib_jcs(self):
        """sha256_hash should match rid-lib JCS computation, not legacy json.dumps."""
        try:
            from rid_lib.ext.utils import sha256_hash_json
        except ImportError:
            pytest.skip("rid-lib not installed")

        contents = {"key": "value", "nested": {"a": 1}}
        rid = GenericRID("test", "jcs-hash")
        bundle = Bundle.generate(rid, contents)

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        wire_event = _to_koi_net_wire_event(event)

        # Compute expected hash using rid-lib JCS
        expected_hash = sha256_hash_json(contents)
        assert wire_event.manifest.sha256_hash == expected_hash

    def test_sha256_hash_differs_from_legacy_for_floats(self):
        """For float values, JCS hash should differ from legacy json.dumps hash."""
        try:
            from rid_lib.ext.utils import sha256_hash_json
        except ImportError:
            pytest.skip("rid-lib not installed")

        # Content with float that JCS normalizes (1.0 -> 1)
        contents = {"value": 1.0}
        rid = GenericRID("test", "float-hash")
        bundle = Bundle.generate(rid, contents)

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        wire_event = _to_koi_net_wire_event(event)

        # Compute legacy hash
        legacy_hash = hashlib.sha256(
            json.dumps(contents, sort_keys=True).encode()
        ).hexdigest()

        # Compute JCS hash
        jcs_hash = sha256_hash_json(contents)

        # Wire event should use JCS hash, not legacy
        assert wire_event.manifest.sha256_hash == jcs_hash
        assert wire_event.manifest.sha256_hash != legacy_hash

    def test_recomputes_hash_even_if_stored_was_legacy(self):
        """Even if stored manifest used legacy hash, wire output recomputes via JCS."""
        try:
            from rid_lib.ext.utils import sha256_hash_json
        except ImportError:
            pytest.skip("rid-lib not installed")

        contents = {"value": 1.0}  # Float that causes hash difference

        # Manually create a manifest with LEGACY hash stored in sha256_hash field
        legacy_hash = hashlib.sha256(
            json.dumps(contents, sort_keys=True).encode()
        ).hexdigest()

        manifest = Manifest(
            rid="test:legacy-stored",
            timestamp="2025-12-23T12:00:00+00:00",
            sha256_hash=legacy_hash,  # Stored legacy hash
            size_bytes=20,
            content_type="application/json",
            legacy_content_hash=legacy_hash
        )

        bundle = Bundle(
            rid="test:legacy-stored",
            manifest=manifest,
            contents=contents
        )

        event = KOIEvent(
            event_type="NEW",
            rid="test:legacy-stored",
            timestamp=manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        wire_event = _to_koi_net_wire_event(event)

        # Wire event should have RECOMPUTED JCS hash, not the stored legacy hash
        expected_jcs_hash = sha256_hash_json(contents)
        assert wire_event.manifest.sha256_hash == expected_jcs_hash
        assert wire_event.manifest.sha256_hash != legacy_hash


class TestInternalPollUnchanged:
    """Test that internal /events/poll remains unchanged for Appendix F clients."""

    def test_internal_event_dict_includes_source_node(self):
        """Internal event dict should include source_node."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        event_dict = event.to_dict()
        assert "source_node" in event_dict
        assert event_dict["source_node"] == "test-sensor"

    def test_internal_event_dict_includes_event_timestamp(self):
        """Internal event dict should include event-level timestamp."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        event_dict = event.to_dict()
        assert "timestamp" in event_dict

    def test_internal_event_dict_includes_bundle(self):
        """Internal event dict should include full bundle."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        event_dict = event.to_dict()
        assert "bundle" in event_dict
        assert "manifest" in event_dict["bundle"]
        assert "contents" in event_dict["bundle"]

    def test_internal_manifest_includes_dual_hashes(self):
        """Internal manifest should include both sha256_hash and legacy_content_hash."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        manifest_dict = bundle.manifest.to_dict()
        assert "sha256_hash" in manifest_dict
        assert "legacy_content_hash" in manifest_dict
        assert "content_hash" in manifest_dict  # Backward compat alias

    def test_internal_manifest_includes_size_bytes(self):
        """Internal manifest should include size_bytes."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        manifest_dict = bundle.manifest.to_dict()
        assert "size_bytes" in manifest_dict

    def test_internal_manifest_includes_content_type(self):
        """Internal manifest should include content_type."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        manifest_dict = bundle.manifest.to_dict()
        assert "content_type" in manifest_dict

    def test_internal_timestamp_may_use_plus_00_00(self):
        """Internal timestamps may use +00:00 format (not normalized to Z)."""
        rid = GenericRID("test", "internal")
        bundle = Bundle.generate(rid, {"key": "value"})

        # Generated timestamps use timezone.utc which produces +00:00
        ts = bundle.manifest.timestamp
        # Either format is acceptable for internal use
        assert "+00:00" in ts or ts.endswith("Z")


class TestKoiNetPollReadOnly:
    """Test that /koi-net/events/poll is read-only and doesn't affect queue."""

    def test_wire_event_preserves_contents(self):
        """Wire event should preserve original contents."""
        contents = {"key": "value", "nested": {"list": [1, 2, 3]}}
        rid = GenericRID("test", "contents")
        bundle = Bundle.generate(rid, contents)

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        wire_event = _to_koi_net_wire_event(event)
        assert wire_event.contents == contents

    def test_wire_event_preserves_rid(self):
        """Wire event should preserve original RID."""
        rid = GenericRID("test", "preserve-rid")
        bundle = Bundle.generate(rid, {"key": "value"})

        event = KOIEvent(
            event_type="NEW",
            rid=rid.to_string(),
            timestamp=bundle.manifest.timestamp,
            source_node="test-sensor",
            bundle=bundle
        )

        wire_event = _to_koi_net_wire_event(event)
        assert wire_event.rid == rid.to_string()

    def test_wire_event_preserves_event_type(self):
        """Wire event should preserve original event_type."""
        rid = GenericRID("test", "event-type")
        bundle = Bundle.generate(rid, {"key": "value"})

        for event_type in ["NEW", "UPDATE", "FORGET"]:
            event = KOIEvent(
                event_type=event_type,
                rid=rid.to_string(),
                timestamp=bundle.manifest.timestamp,
                source_node="test-sensor",
                bundle=bundle if event_type != "FORGET" else None
            )

            wire_event = _to_koi_net_wire_event(event)
            assert wire_event.event_type == event_type


class TestKoiNetPydanticModels:
    """Test KOI-net Pydantic model validation."""

    def test_poll_events_request_defaults(self):
        """PollEvents request should have correct defaults."""
        request = KoiNetPollEventsRequest()
        assert request.type == "poll_events"
        assert request.limit == 0

    def test_poll_events_request_with_limit(self):
        """PollEvents request should accept custom limit."""
        request = KoiNetPollEventsRequest(limit=50)
        assert request.limit == 50

    def test_events_payload_response_type(self):
        """EventsPayload response should have type 'events_payload'."""
        response = KoiNetEventsPayloadResponse(events=[])
        assert response.type == "events_payload"
        assert response.events == []

    def test_wire_manifest_model(self):
        """Wire manifest model should have only required fields."""
        manifest = KoiNetWireManifest(
            rid="test:manifest",
            timestamp="2025-12-23T12:00:00Z",
            sha256_hash="abc123"
        )
        assert manifest.rid == "test:manifest"
        assert manifest.timestamp == "2025-12-23T12:00:00Z"
        assert manifest.sha256_hash == "abc123"

    def test_wire_event_model(self):
        """Wire event model should have only allowed fields."""
        event = KoiNetWireEvent(
            rid="test:event",
            event_type="NEW",
            manifest=KoiNetWireManifest(
                rid="test:event",
                timestamp="2025-12-23T12:00:00Z",
                sha256_hash="abc123"
            ),
            contents={"key": "value"}
        )
        assert event.rid == "test:event"
        assert event.event_type == "NEW"
        assert event.manifest.sha256_hash == "abc123"
        assert event.contents == {"key": "value"}


class TestKoiNetPollPerNodeFlush:
    """Test that /koi-net/events/poll uses per-node flush for signed requests (Finding 2)."""

    def test_get_queued_events_for_delivery_tracks_per_node(self):
        """Two different nodes polling should see independent event streams."""
        from koi_protocol.nodes.koi_node import KOIFullNode

        node = KOIFullNode("test-coordinator", port=9999)

        # Queue 3 events
        for i in range(3):
            rid = GenericRID("test", f"event{i}")
            bundle = Bundle.generate(rid, {"idx": i})
            event = KOIEvent.new_event(bundle, "test-sensor")
            node.queue_event(event)

        # Node A polls - gets all 3
        events_a, ids_a = node.get_queued_events_for_delivery("node-A", max_events=10)
        assert len(events_a) == 3

        # Node A polls again - gets 0 (already delivered)
        events_a2, ids_a2 = node.get_queued_events_for_delivery("node-A", max_events=10)
        assert len(events_a2) == 0

        # Node B polls - gets all 3 (independent tracking)
        events_b, ids_b = node.get_queued_events_for_delivery("node-B", max_events=10)
        assert len(events_b) == 3

    def test_unsigned_poll_is_read_only(self):
        """Unsigned get_queued_events should be read-only (no delivery tracking)."""
        from koi_protocol.nodes.koi_node import KOIFullNode

        node = KOIFullNode("test-coordinator", port=9999)

        rid = GenericRID("test", "readonly")
        bundle = Bundle.generate(rid, {"data": "test"})
        event = KOIEvent.new_event(bundle, "test-sensor")
        node.queue_event(event)

        # Read-only poll multiple times - should always return the event
        events1 = node.get_queued_events(max_events=10)
        events2 = node.get_queued_events(max_events=10)
        assert len(events1) == 1
        assert len(events2) == 1


class TestKoiNetRequireSignedConfig:
    """Test KOI_NET_REQUIRE_SIGNED configuration loading (Finding 3)."""

    def test_require_signed_defaults_to_false(self):
        """KOI_NET_REQUIRE_SIGNED should default to false."""
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator
        import os

        # Ensure env var is not set
        os.environ.pop("KOI_NET_REQUIRE_SIGNED", None)
        coordinator = KOICoordinator(node_name="test", port=19999)
        assert coordinator.koi_net_require_signed is False

    def test_require_signed_reads_env_var(self, monkeypatch):
        """KOI_NET_REQUIRE_SIGNED=true should enable signed-only mode."""
        monkeypatch.setenv("KOI_NET_REQUIRE_SIGNED", "true")
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator

        coordinator = KOICoordinator(node_name="test-signed", port=19998)
        assert coordinator.koi_net_require_signed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
