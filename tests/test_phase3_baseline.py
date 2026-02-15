#!/usr/bin/env python3
"""
Phase 3 Session 3.0: Baseline Golden Tests

Captures exact current behavior of BOTH broadcast endpoints BEFORE refactoring.
These tests document the behavioral contract that must be preserved (or intentionally
evolved, as noted in the plan for the strict endpoint).

Legacy endpoint: POST /events/broadcast
Strict endpoint: POST /koi-net/events/broadcast
"""

import sys
from pathlib import Path

# Add koi-sensors to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json
import hashlib
import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock
from httpx import AsyncClient, ASGITransport

# Only use asyncio backend (trio doesn't support asyncio.create_task)
pytestmark = pytest.mark.anyio

@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param

from koi_protocol.coordinator.koi_coordinator import KOICoordinator
from koi_protocol.core.bundle_system import Bundle, KOIEvent, Manifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def coordinator(tmp_path):
    """Create a KOICoordinator with mocked dependencies and isolated state."""
    cache_dir = str(tmp_path / "cache")
    with patch.dict("os.environ", {
        "KOI_ENVELOPE_SIGN": "false",
        "KOI_ENVELOPE_VERIFY": "false",
        "KOI_NET_REQUIRE_SIGNED": "false",
    }):
        coord = KOICoordinator(
            node_name="test-coordinator",
            port=9999,
            cache_dir=cache_dir,
        )
    # Isolate persistent state files to tmp_path
    coord.dedup_state_file = tmp_path / "dedup_state.json"
    coord.sensor_registry_file = tmp_path / "sensor_registry.json"
    coord.content_hashes = {}
    coord.url_hashes = {}
    coord.broadcast_sensors = {}
    return coord


@pytest.fixture
def client(coordinator):
    """Create an async test client for the coordinator's FastAPI app."""
    transport = ASGITransport(app=coordinator.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_event_data(rid="orn:test.sensor:item/1", event_type="NEW", source_node="test-sensor-001",
                     contents=None, include_bundle=True):
    """Helper to build event data dict."""
    ts = datetime.now(timezone.utc).isoformat()
    contents = contents or {"text": "hello world", "unique": rid}
    content_str = json.dumps(contents, sort_keys=True)
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()

    event = {
        "event_type": event_type,
        "rid": rid,
        "timestamp": ts,
        "source_node": source_node,
    }
    if include_bundle:
        event["bundle"] = {
            "rid": rid,
            "manifest": {
                "rid": rid,
                "timestamp": ts,
                "sha256_hash": content_hash,
                "content_hash": content_hash,
                "size_bytes": len(content_str.encode()),
                "content_type": "application/json",
                "version": "1.0",
                "metadata": {},
            },
            "contents": contents,
        }
    return event


# ===========================================================================
# Legacy endpoint: POST /events/broadcast
# ===========================================================================

class TestLegacyBroadcastBaseline:
    """Golden tests for POST /events/broadcast current behavior."""

    async def test_normal_event_returns_success(self, client, coordinator):
        """Normal event with bundle → {"status": "success", "event_id": ...}"""
        event = _make_event_data()
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["event_id"] == event["rid"]

    async def test_heartbeat_event(self, client, coordinator):
        """Heartbeat event → updates sensor_monitoring, returns success."""
        event = {
            "event_type": "HEARTBEAT",
            "rid": "orn:sensor.heartbeat:hb/1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_node": "test-sensor-001",
            "data": {
                "type": "sensor_heartbeat",
                "sensor_id": "website-sensor",
                "monitoring": [
                    {"url": "https://example.com", "status": "ok"},
                ],
            },
            "bundle": {
                "rid": "orn:sensor.heartbeat:hb/1",
                "manifest": {
                    "rid": "orn:sensor.heartbeat:hb/1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sha256_hash": "abc123",
                    "content_hash": "abc123",
                    "size_bytes": 10,
                    "content_type": "application/json",
                    "version": "1.0",
                    "metadata": {},
                },
                "contents": {"type": "heartbeat"},
            },
        }
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        body = resp.json()
        # Heartbeat still processes normally (it doesn't stop event processing in current code)
        # The heartbeat detection is additive — it updates monitoring AND continues
        assert body["status"] in ("success", "skipped_duplicate")
        assert "website-sensor" in coordinator.sensor_monitoring

    async def test_duplicate_event_returns_skipped(self, client, coordinator):
        """Duplicate event → {"status": "skipped_duplicate", "reason": "duplicate_content"}"""
        event = _make_event_data(rid="orn:test.dup:item/dup1")
        # First send — should succeed
        resp1 = await client.post("/events/broadcast", json=event)
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "success"

        # Second send — same content hash → duplicate
        resp2 = await client.post("/events/broadcast", json=event)
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["status"] == "skipped_duplicate"
        assert body2["event_id"] == event["rid"]
        assert body2["reason"] == "duplicate_content"

    async def test_single_event_flat_response(self, client, coordinator):
        """Single event → response is flat dict (not wrapped in array)."""
        event = _make_event_data(rid="orn:test.flat:item/flat1")
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        body = resp.json()
        # Flat dict, not {"results": [...]}
        assert "results" not in body
        assert "status" in body

    async def test_multi_events_wrapped_response(self, client, coordinator):
        """Multiple events → {"status": "success", "event_count": N, "results": [...]}"""
        events = {
            "events": [
                _make_event_data(rid="orn:test.multi:item/a", contents={"text": "aaa"}),
                _make_event_data(rid="orn:test.multi:item/b", contents={"text": "bbb"}),
            ]
        }
        resp = await client.post("/events/broadcast", json=events)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["event_count"] == 2
        assert len(body["results"]) == 2

    async def test_bundle_created_from_data_field(self, client, coordinator):
        """Event with data field (no bundle) → bundle created from sensor data."""
        event = {
            "event_type": "NEW",
            "rid": "orn:test.data:item/d1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_node": "test-sensor-001",
            "data": {
                "text": "sensor payload",
                "metric": 42,
            },
        }
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

    async def test_sensor_tracking_updated(self, client, coordinator):
        """broadcast_sensors updated with sensor_type key."""
        event = _make_event_data(
            rid="orn:test.track:item/t1",
            source_node="website-sensor-abc123",
        )
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        assert "website-sensor" in coordinator.broadcast_sensors
        sensor = coordinator.broadcast_sensors["website-sensor"]
        assert sensor["node_id"] == "website-sensor-abc123"
        assert sensor["event_count"] >= 1

    async def test_events_appear_in_poll_queue(self, client, coordinator):
        """Events are available via poll queue for downstream consumers."""
        event = _make_event_data(rid="orn:test.queue:item/q1")
        await client.post("/events/broadcast", json=event)

        # Poll for events
        poll_resp = await client.get(
            "/events/poll",
            params={"node_id": "test-consumer"},
        )
        assert poll_resp.status_code == 200
        poll_body = poll_resp.json()
        assert len(poll_body["events"]) > 0
        rids = [e["rid"] for e in poll_body["events"]]
        assert "orn:test.queue:item/q1" in rids


# ===========================================================================
# Strict endpoint: POST /koi-net/events/broadcast
# ===========================================================================

class TestStrictBroadcastBaseline:
    """Golden tests for POST /koi-net/events/broadcast current behavior."""

    async def test_normal_event_returns_ok(self, client, coordinator):
        """Normal event → {"status": "ok", "processed": N}"""
        payload = {
            "type": "events_payload",
            "events": [
                {
                    "rid": "orn:test.strict:item/s1",
                    "event_type": "NEW",
                    "manifest": {
                        "rid": "orn:test.strict:item/s1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sha256_hash": "abc123",
                    },
                    "contents": {"text": "strict event"},
                }
            ],
        }
        resp = await client.post("/koi-net/events/broadcast", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["processed"] == 1

    async def test_invalid_type_returns_error(self, client, coordinator):
        """Invalid type field → ErrorResponse."""
        payload = {"type": "wrong_type", "events": []}
        resp = await client.post("/koi-net/events/broadcast", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body

    async def test_unified_calls_handle_and_broadcast(self, client, coordinator):
        """Phase 3 unified: strict path now calls BOTH handle_event AND broadcast_event.

        INTENTIONAL CONTRACT EVOLUTION: Before Phase 3, strict path only called
        handle_event (cache only). After unification, events follow the full pipeline
        including broadcast_event (queuing for poll consumers).
        """
        payload = {
            "type": "events_payload",
            "events": [
                {
                    "rid": "orn:test.strict:item/h1",
                    "event_type": "NEW",
                    "manifest": {
                        "rid": "orn:test.strict:item/h1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sha256_hash": "def456",
                    },
                    "contents": {"text": "handle only"},
                }
            ],
        }
        with patch.object(coordinator.koi_node, "handle_event", new_callable=AsyncMock) as mock_handle, \
             patch.object(coordinator.koi_node, "broadcast_event", new_callable=AsyncMock) as mock_broadcast:
            resp = await client.post("/koi-net/events/broadcast", json=payload)
            assert resp.status_code == 200
            mock_handle.assert_called()
            # Post-Phase 3: strict path now calls broadcast_event too (unified pipeline)
            mock_broadcast.assert_called()

    async def test_events_appear_in_poll_queue_strict(self, client, coordinator):
        """Phase 3 unified: strict events now appear in poll queue.

        INTENTIONAL CONTRACT EVOLUTION: Before Phase 3, strict events were
        invisible to poll consumers. After unification, all events follow
        the same pipeline including broadcast_event.
        """
        payload = {
            "type": "events_payload",
            "events": [
                {
                    "rid": "orn:test.strict:item/pollyes",
                    "event_type": "NEW",
                    "manifest": {
                        "rid": "orn:test.strict:item/pollyes",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sha256_hash": "ghi789",
                    },
                    "contents": {"text": "now polled"},
                }
            ],
        }
        await client.post("/koi-net/events/broadcast", json=payload)

        poll_resp = await client.get(
            "/events/poll",
            params={"node_id": "strict-consumer"},
        )
        poll_body = poll_resp.json()
        strict_rids = [e["rid"] for e in poll_body["events"]]
        # Post-Phase 3: strict events ARE now queued (unified pipeline)
        assert "orn:test.strict:item/pollyes" in strict_rids


# ===========================================================================
# Signed envelope tests
# ===========================================================================

class TestSignedEnvelopeBaseline:
    """Golden tests for signed envelope wrapping on both endpoints."""

    @pytest.fixture
    def signed_coordinator(self, tmp_path):
        """Coordinator with signing enabled."""
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()

        cache_dir = str(tmp_path / "signed_cache")
        with patch.dict("os.environ", {
            "KOI_ENVELOPE_SIGN": "true",
            "KOI_ENVELOPE_VERIFY": "true",
            "KOI_NET_REQUIRE_SIGNED": "false",
        }):
            coord = KOICoordinator(
                node_name="test-signed-coordinator",
                port=9998,
                cache_dir=cache_dir,
            )
        coord.envelope_private_key = private_key
        coord.envelope_public_keys = {
            "orn:koi-net.node:test-sender+abc": public_key,
        }
        coord.envelope_sign = True
        coord.envelope_verify = True
        return coord, private_key, public_key

    async def test_legacy_signed_request_signed_response(self, signed_coordinator, tmp_path):
        """Legacy endpoint: signed request → signed response via _wrap_response."""
        from shared.koi_envelope import sign_envelope

        coord, private_key, public_key = signed_coordinator
        transport = ASGITransport(app=coord.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            event = _make_event_data(rid="orn:test.signed:item/leg1")
            signed_req = sign_envelope(
                payload=event,
                source_node="orn:koi-net.node:test-sender+abc",
                target_node=coord.koi_node.node_id,
                private_key=private_key,
            )
            resp = await client.post("/events/broadcast", json=signed_req)
            assert resp.status_code == 200
            body = resp.json()
            # Signed response has envelope structure
            assert "payload" in body
            assert "source_node" in body
            assert "signature" in body

    async def test_strict_signed_request_signed_response(self, signed_coordinator, tmp_path):
        """Strict endpoint: signed request → signed response via _handle_koi_net_envelope."""
        from shared.koi_envelope import sign_envelope

        coord, private_key, public_key = signed_coordinator
        transport = ASGITransport(app=coord.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "type": "events_payload",
                "events": [
                    {
                        "rid": "orn:test.signed:item/strict1",
                        "event_type": "NEW",
                        "manifest": {
                            "rid": "orn:test.signed:item/strict1",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "sha256_hash": "abc123",
                        },
                        "contents": {"text": "signed strict"},
                    }
                ],
            }
            signed_req = sign_envelope(
                payload=payload,
                source_node="orn:koi-net.node:test-sender+abc",
                target_node=coord.koi_node.node_id,
                private_key=private_key,
            )
            resp = await client.post("/koi-net/events/broadcast", json=signed_req)
            assert resp.status_code == 200
            body = resp.json()
            # Signed response
            assert "payload" in body
            assert "signature" in body
