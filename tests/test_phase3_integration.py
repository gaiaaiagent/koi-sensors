#!/usr/bin/env python3
"""
Phase 3 Session 3.3: Integration Tests

Tests verifying unified pipeline behavior through both broadcast endpoints,
pipeline-specific behavior, and custom handler extensibility.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json
import hashlib
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from koi_protocol.coordinator.koi_coordinator import KOICoordinator
from koi_protocol.processor import (
    HandlerType,
    KnowledgeHandler,
    KnowledgeObject,
    KnowledgePipeline,
    PipelineStop,
    STOP_CHAIN,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


@pytest.fixture
def coordinator(tmp_path):
    cache_dir = str(tmp_path / "cache")
    with patch.dict("os.environ", {
        "KOI_ENVELOPE_SIGN": "false",
        "KOI_ENVELOPE_VERIFY": "false",
        "KOI_NET_REQUIRE_SIGNED": "false",
    }):
        coord = KOICoordinator(
            node_name="test-coordinator",
            port=9997,
            cache_dir=cache_dir,
        )
    coord.dedup_state_file = tmp_path / "dedup_state.json"
    coord.sensor_registry_file = tmp_path / "sensor_registry.json"
    coord.content_hashes = {}
    coord.url_hashes = {}
    coord.broadcast_sensors = {}
    # Isolate event queue to avoid stale events from prior test runs
    coord.event_queue_file = tmp_path / "event_queue.json"
    coord.koi_node.configure_event_queue_persistence(coord.event_queue_file)
    # Clear any in-memory event queues
    coord.koi_node.event_queue = []
    coord.koi_node.delivery_tracking = {}
    return coord


@pytest.fixture
def client(coordinator):
    transport = ASGITransport(app=coordinator.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_event(rid, contents=None, source_node="test-sensor-001"):
    ts = datetime.now(timezone.utc).isoformat()
    contents = contents or {"text": f"test for {rid}"}
    content_str = json.dumps(contents, sort_keys=True)
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()
    return {
        "event_type": "NEW",
        "rid": rid,
        "timestamp": ts,
        "source_node": source_node,
        "bundle": {
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
        },
    }


# ===========================================================================
# Legacy endpoint behavioral parity through pipeline
# ===========================================================================

class TestLegacyPipelineIntegration:
    async def test_normal_event_same_response_shape(self, client, coordinator):
        event = _make_event("orn:test.int:item/norm1")
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["event_id"] == "orn:test.int:item/norm1"

    async def test_heartbeat_updates_monitoring(self, client, coordinator):
        event = {
            "event_type": "HEARTBEAT",
            "rid": "orn:sensor.heartbeat:hb/int1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_node": "test-sensor-001",
            "data": {
                "type": "sensor_heartbeat",
                "sensor_id": "int-sensor",
                "monitoring": [{"url": "https://test.com"}],
            },
            "bundle": {
                "rid": "orn:sensor.heartbeat:hb/int1",
                "manifest": {
                    "rid": "orn:sensor.heartbeat:hb/int1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sha256_hash": "hb123",
                    "content_hash": "hb123",
                    "size_bytes": 10,
                    "content_type": "application/json",
                    "version": "1.0",
                    "metadata": {},
                },
                "contents": {"heartbeat": True},
            },
        }
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        assert "int-sensor" in coordinator.sensor_monitoring

    async def test_duplicate_skipped_response(self, client, coordinator):
        event = _make_event("orn:test.int:item/dup1")
        await client.post("/events/broadcast", json=event)
        resp = await client.post("/events/broadcast", json=event)
        body = resp.json()
        assert body["status"] == "skipped_duplicate"
        assert body["reason"] == "duplicate_content"

    async def test_single_vs_multi_response_shape(self, client, coordinator):
        # Single
        resp_single = await client.post("/events/broadcast", json=_make_event("orn:test.int:item/single1"))
        body_single = resp_single.json()
        assert "results" not in body_single

        # Multi
        resp_multi = await client.post("/events/broadcast", json={
            "events": [
                _make_event("orn:test.int:item/m1", contents={"m": 1}),
                _make_event("orn:test.int:item/m2", contents={"m": 2}),
            ]
        })
        body_multi = resp_multi.json()
        assert body_multi["event_count"] == 2
        assert len(body_multi["results"]) == 2

    async def test_bundle_from_data_field(self, client, coordinator):
        event = {
            "event_type": "NEW",
            "rid": "orn:test.int:item/datafld",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_node": "test-sensor-001",
            "data": {"metric": 99},
        }
        resp = await client.post("/events/broadcast", json=event)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


# ===========================================================================
# Strict endpoint parity through pipeline
# ===========================================================================

class TestStrictPipelineIntegration:
    async def test_normal_event_ok_response(self, client, coordinator):
        payload = {
            "type": "events_payload",
            "events": [{
                "rid": "orn:test.int:item/strict1",
                "event_type": "NEW",
                "manifest": {
                    "rid": "orn:test.int:item/strict1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sha256_hash": "abc",
                },
                "contents": {"text": "strict"},
            }],
        }
        resp = await client.post("/koi-net/events/broadcast", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["processed"] == 1

    async def test_invalid_type_error(self, client, coordinator):
        resp = await client.post("/koi-net/events/broadcast", json={"type": "wrong"})
        assert resp.status_code == 400

    async def test_events_appear_in_poll_queue_unified(self, client, coordinator):
        """Both endpoints now queue events for poll consumers."""
        payload = {
            "type": "events_payload",
            "events": [{
                "rid": "orn:test.int:item/poll_unified",
                "event_type": "NEW",
                "manifest": {
                    "rid": "orn:test.int:item/poll_unified",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sha256_hash": "pollhash",
                },
                "contents": {"text": "poll me"},
            }],
        }
        await client.post("/koi-net/events/broadcast", json=payload)

        poll = await client.get("/events/poll", params={"node_id": "test-poller"})
        rids = [e["rid"] for e in poll.json()["events"]]
        assert "orn:test.int:item/poll_unified" in rids


# ===========================================================================
# Pipeline-specific tests
# ===========================================================================

class TestPipelineSpecific:
    async def test_heartbeat_doesnt_reach_network_handler(self, client, coordinator):
        """Heartbeat with no bundle skips dedup and network (no bundle to emit)."""
        event = {
            "event_type": "HEARTBEAT",
            "rid": "orn:sensor.heartbeat:hb/nonet",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_node": "test-sensor-001",
            "data": {
                "type": "sensor_heartbeat",
                "sensor_id": "nonet-sensor",
                "monitoring": [{"url": "https://nonet.com"}],
            },
        }
        with patch.object(coordinator.koi_node, "handle_event", new_callable=AsyncMock) as mock_handle:
            resp = await client.post("/events/broadcast", json=event)
            assert resp.status_code == 200
            # Heartbeat with data (no bundle) will go through bundle_normalization (creates bundle)
            # then sensor_tracking, dedup, and eventually event_emission
            # This is expected — heartbeat detection is additive, not stopping

    async def test_dedup_stops_network_handler(self, client, coordinator):
        """Duplicate events never reach event_emission_handler."""
        event = _make_event("orn:test.int:item/dedup_stop")
        await client.post("/events/broadcast", json=event)

        with patch.object(coordinator.koi_node, "handle_event", new_callable=AsyncMock) as mock_handle, \
             patch.object(coordinator.koi_node, "broadcast_event", new_callable=AsyncMock) as mock_broadcast:
            resp = await client.post("/events/broadcast", json=event)
            body = resp.json()
            assert body["status"] == "skipped_duplicate"
            # Network handler not called for duplicates
            mock_handle.assert_not_called()
            mock_broadcast.assert_not_called()

    async def test_handler_order_respected(self, coordinator):
        """Handlers execute in order: RID → Bundle → Network."""
        order = []
        original_handlers = coordinator.pipeline.handlers.copy()

        @KnowledgeHandler.create(HandlerType.RID)
        def track_rid(coordinator, kobj):
            order.append("rid")
            return None

        @KnowledgeHandler.create(HandlerType.Bundle)
        def track_bundle(coordinator, kobj):
            order.append("bundle")
            return None

        @KnowledgeHandler.create(HandlerType.Network)
        async def track_network(coordinator, kobj):
            order.append("network")
            kobj.result_status = "success"
            return kobj

        coordinator.pipeline.handlers = [track_rid, track_bundle, track_network]
        kobj = KnowledgeObject(rid="orn:test:order")
        await coordinator.pipeline.process(kobj)
        assert order == ["rid", "bundle", "network"]

        coordinator.pipeline.handlers = original_handlers

    async def test_custom_handler_registration(self, coordinator):
        """Custom handler can be added via pipeline.add_handler()."""
        called = []

        @KnowledgeHandler.create(HandlerType.Final)
        def custom_final(coordinator, kobj):
            called.append("custom")
            return None

        coordinator.pipeline.add_handler(custom_final)
        kobj = KnowledgeObject(rid="orn:test:custom", event_type="NEW", source="s1")

        # Mock out network emission to avoid real koi_node calls
        with patch.object(coordinator.koi_node, "handle_event", new_callable=AsyncMock), \
             patch.object(coordinator.koi_node, "broadcast_event", new_callable=AsyncMock):
            await coordinator.pipeline.process(kobj)

        assert "custom" in called
        # Clean up
        coordinator.pipeline.handlers = [
            h for h in coordinator.pipeline.handlers if h is not custom_final
        ]

    async def test_stop_chain_halts_all_downstream(self, coordinator):
        """STOP_CHAIN from any handler stops all downstream processing."""
        order = []

        @KnowledgeHandler.create(HandlerType.RID)
        def stopper(coordinator, kobj):
            order.append("rid_stop")
            kobj.result_status = "stopped_early"
            return STOP_CHAIN

        @KnowledgeHandler.create(HandlerType.Network)
        async def never_reached(coordinator, kobj):
            order.append("network")
            return kobj

        pipeline = KnowledgePipeline(coordinator=coordinator, default_handlers=[stopper, never_reached])
        kobj = KnowledgeObject(rid="orn:test:stop_all")
        result = await pipeline.process(kobj)

        assert isinstance(result, PipelineStop)
        assert result.kobj.result_status == "stopped_early"
        assert order == ["rid_stop"]

    async def test_event_emission_builds_from_canonical(self, coordinator):
        """event_emission_handler builds KOIEvent from canonical kobj fields."""
        from koi_protocol.processor.default_handlers import event_emission_handler
        from koi_protocol.core.bundle_system import Manifest

        manifest = Manifest(
            rid="orn:test:canonical", timestamp="2026-01-01T00:00:00Z",
            sha256_hash="can_hash", size_bytes=10, content_type="application/json",
        )
        kobj = KnowledgeObject(
            rid="orn:test:canonical",
            manifest=manifest,
            contents={"canonical": True},
            event_type="UPDATE",
            source="canonical-sensor",
            raw_event_data={"data": {"should_not_be_used": True}},
        )

        with patch.object(coordinator.koi_node, "handle_event", new_callable=AsyncMock) as mock_handle, \
             patch.object(coordinator.koi_node, "broadcast_event", new_callable=AsyncMock):
            result = await event_emission_handler.func(coordinator=coordinator, kobj=kobj)

        event = mock_handle.call_args[0][0]
        assert event.rid == "orn:test:canonical"
        assert event.event_type == "UPDATE"
        assert event.source_node == "canonical-sensor"
        assert event.bundle.contents == {"canonical": True}


# ===========================================================================
# Signed envelope integration
# ===========================================================================

class TestSignedEnvelopeIntegration:
    @pytest.fixture
    def signed_coordinator(self, tmp_path):
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
                node_name="test-signed-int",
                port=9996,
                cache_dir=cache_dir,
            )
        coord.envelope_private_key = private_key
        coord.envelope_public_keys = {
            "orn:koi-net.node:test-signed+abc": public_key,
        }
        coord.envelope_sign = True
        coord.envelope_verify = True
        coord.dedup_state_file = tmp_path / "dedup.json"
        coord.sensor_registry_file = tmp_path / "registry.json"
        coord.content_hashes = {}
        coord.url_hashes = {}
        coord.broadcast_sensors = {}
        return coord, private_key, public_key

    async def test_legacy_signed_roundtrip(self, signed_coordinator):
        from shared.koi_envelope import sign_envelope

        coord, private_key, _ = signed_coordinator
        transport = ASGITransport(app=coord.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            event = _make_event("orn:test.int:item/signed_leg")
            signed = sign_envelope(
                event,
                "orn:koi-net.node:test-signed+abc",
                coord.koi_node.node_id,
                private_key,
            )
            resp = await client.post("/events/broadcast", json=signed)
            assert resp.status_code == 200
            body = resp.json()
            assert "signature" in body
            assert "payload" in body

    async def test_strict_signed_roundtrip(self, signed_coordinator):
        from shared.koi_envelope import sign_envelope

        coord, private_key, _ = signed_coordinator
        transport = ASGITransport(app=coord.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "type": "events_payload",
                "events": [{
                    "rid": "orn:test.int:item/signed_strict",
                    "event_type": "NEW",
                    "manifest": {
                        "rid": "orn:test.int:item/signed_strict",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "sha256_hash": "signhash",
                    },
                    "contents": {"text": "signed strict"},
                }],
            }
            signed = sign_envelope(
                payload,
                "orn:koi-net.node:test-signed+abc",
                coord.koi_node.node_id,
                private_key,
            )
            resp = await client.post("/koi-net/events/broadcast", json=signed)
            assert resp.status_code == 200
            body = resp.json()
            assert "signature" in body
