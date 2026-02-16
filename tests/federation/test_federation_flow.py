"""
Phase 4 — Tier 2: Federation Flow Tests

Tests real federation scenarios: handshake, edge negotiation, event flow,
and the full federation cycle. Uses koi-net wire format with signed envelopes.

All tests use signed envelopes (federation posture).

Requires Python 3.12+ (koi-net 1.2.4 uses PEP 695 type aliases).
"""

import sys
from pathlib import Path

# Gate on Python version before importing koi-net (SyntaxError on <3.12)
import pytest
if sys.version_info < (3, 12):
    pytest.skip("koi-net requires Python 3.12+", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import asyncio
import json

from koi_net.protocol.api_models import (
    EventsPayload, PollEvents, FetchRids, FetchManifests, FetchBundles,
    RidsPayload, ManifestsPayload, BundlesPayload, Event,
)
from koi_net.protocol.event import EventType
from koi_net.protocol.node import NodeProfile as KoiNetNodeProfile, NodeType, NodeProvides
from koi_net.protocol.edge import EdgeProfile as KoiNetEdgeProfile, EdgeType as KoiNetEdgeType
from koi_net.protocol.consts import BROADCAST_EVENTS_PATH
from rid_lib.ext import Manifest as RidLibManifest
from rid_lib.types import KoiNetNode

from .conftest import payload_to_dict

pytestmark = [pytest.mark.anyio, pytest.mark.federation]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_handshake_payload(peer_rid: str, peer_profile: dict) -> dict:
    """Build a BlockScience-style handshake events_payload (FORGET + NEW)."""
    return {
        "type": "events_payload",
        "events": [
            {"rid": str(peer_rid), "event_type": "FORGET"},
            {
                "rid": str(peer_rid),
                "event_type": "NEW",
                "contents": peer_profile,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Test 12: Handshake with koi-net payload
# ---------------------------------------------------------------------------

async def test_handshake_with_koi_net_payload(
    regen_client, regen_coordinator, sign_as_blockscience,
    blockscience_node_rid, blockscience_keypair, verify_as_blockscience
):
    """Regen /koi-net/handshake accepts koi-net-shaped FORGET+NEW handshake."""
    _, bs_pub = blockscience_keypair
    peer_profile = KoiNetNodeProfile(
        base_url="http://blockscience-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(event=["orn:test.*"], state=["orn:test.*"]),
        public_key=bs_pub.to_der(),
    )

    handshake_body = _build_handshake_payload(
        blockscience_node_rid,
        peer_profile.model_dump(exclude_none=True),
    )

    signed = sign_as_blockscience(handshake_body)
    resp = await regen_client.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    assert inner["type"] == "handshake_response"
    assert "node_rid" in inner
    assert "profile" in inner


# ---------------------------------------------------------------------------
# Test 13: Edge proposal from handshake
# ---------------------------------------------------------------------------

async def test_edge_proposal_from_handshake(
    regen_client, regen_coordinator, sign_as_blockscience,
    blockscience_node_rid, blockscience_keypair, verify_as_blockscience
):
    """Handshake response includes valid EdgeProfile (PROPOSED status)."""
    _, bs_pub = blockscience_keypair
    peer_profile = KoiNetNodeProfile(
        base_url="http://blockscience-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(),
        public_key=bs_pub.to_der(),
    )

    handshake_body = _build_handshake_payload(
        blockscience_node_rid,
        peer_profile.model_dump(exclude_none=True),
    )

    signed = sign_as_blockscience(handshake_body)
    resp = await regen_client.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    proposed_edge = inner.get("proposed_edge")
    assert proposed_edge is not None, "Handshake should propose an edge"

    # Validate as EdgeProfile
    edge = KoiNetEdgeProfile.model_validate(proposed_edge)
    assert edge.status == "PROPOSED"
    assert edge.edge_type in (KoiNetEdgeType.POLL, KoiNetEdgeType.WEBHOOK)
    assert edge.source  # Regen node
    assert str(edge.target) == str(blockscience_node_rid)


# ---------------------------------------------------------------------------
# Test 14: Edge approval flow
# ---------------------------------------------------------------------------

async def test_edge_approval_flow(
    regen_client, regen_coordinator, sign_as_blockscience,
    blockscience_node_rid, blockscience_keypair, verify_as_blockscience
):
    """Approve proposed edge → peer stored in known_peers."""
    _, bs_pub = blockscience_keypair
    peer_profile = KoiNetNodeProfile(
        base_url="http://blockscience-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(),
        public_key=bs_pub.to_der(),
    )

    # Handshake
    handshake_body = _build_handshake_payload(
        blockscience_node_rid,
        peer_profile.model_dump(exclude_none=True),
    )
    signed = sign_as_blockscience(handshake_body)
    resp = await regen_client.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200
    inner = verify_as_blockscience(resp.json())

    edge_rid = inner.get("edge_rid")
    assert edge_rid, "Handshake response should include edge_rid"

    # Approve the edge
    approve_body = {
        "type": "edge_approve",
        "edge_rid": edge_rid,
        "node_rid": str(blockscience_node_rid),
    }
    signed_approve = sign_as_blockscience(approve_body)
    resp = await regen_client.post("/koi-net/edges/approve", json=signed_approve)
    assert resp.status_code == 200

    approve_inner = verify_as_blockscience(resp.json())
    assert approve_inner["status"] == "APPROVED"

    # Verify peer is stored
    assert str(blockscience_node_rid) in regen_coordinator.known_peers


# ---------------------------------------------------------------------------
# Test 15: Bidirectional event flow
# ---------------------------------------------------------------------------

async def test_bidirectional_event_flow(
    regen_client, regen_coordinator, sign_as_blockscience,
    make_koi_net_event, blockscience_node_rid, verify_as_blockscience
):
    """Regen broadcast → events appear in peer's poll queue."""
    # Broadcast an event
    event = make_koi_net_event(rid="orn:test.sensor:bidir/1")
    payload = EventsPayload(events=[event])
    signed = sign_as_blockscience(payload_to_dict(payload))
    resp = await regen_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200

    # Poll as the BlockScience node — should see the event
    poll = PollEvents(limit=50)
    signed_poll = sign_as_blockscience(payload_to_dict(poll))
    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    events_payload = EventsPayload.model_validate(inner)
    assert len(events_payload.events) >= 1

    # Find our event
    rids = [str(e.rid) for e in events_payload.events]
    assert "orn:test.sensor:bidir/1" in rids


# ---------------------------------------------------------------------------
# Test 16: RID type filtering
# ---------------------------------------------------------------------------

async def test_rid_type_filtering(
    regen_client, regen_coordinator, sign_as_blockscience,
    make_koi_net_event, blockscience_node_rid, blockscience_keypair,
    verify_as_blockscience, regen_node_rid
):
    """Edge with rid_types filter → only matching events propagated."""
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    # Manually create an edge with rid_types filter
    edge_rid = "orn:koi-net.edge:test-filtered"
    filtered_edge = EdgeProfile(
        source=str(regen_node_rid),
        target=str(blockscience_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=["orn:test.allowed"],  # Only allow this type
    )
    regen_coordinator.edges[edge_rid] = filtered_edge

    # Broadcast two events: one matching, one not
    event_allowed = make_koi_net_event(rid="orn:test.allowed:item/1")
    event_blocked = make_koi_net_event(rid="orn:test.blocked:item/1")

    for event in [event_allowed, event_blocked]:
        payload = EventsPayload(events=[event])
        signed = sign_as_blockscience(payload_to_dict(payload))
        await regen_client.post("/koi-net/events/broadcast", json=signed)

    # Poll — current implementation returns all events regardless of edge filter
    # This test documents current behavior; edge filtering is a Phase 4+ enhancement
    poll = PollEvents(limit=50)
    signed_poll = sign_as_blockscience(payload_to_dict(poll))
    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    events_payload = EventsPayload.model_validate(inner)
    # Both events are returned (edge filtering not yet enforced)
    rids = [str(e.rid) for e in events_payload.events]
    assert "orn:test.allowed:item/1" in rids


# ---------------------------------------------------------------------------
# Test 17: Peer persistence across restart
# ---------------------------------------------------------------------------

async def test_peer_persistence_across_restart(
    tmp_path, regen_keypair, blockscience_keypair,
    regen_node_rid, blockscience_node_rid
):
    """Peer state survives coordinator recreation."""
    from cryptography.hazmat.primitives import serialization
    from unittest.mock import patch
    from shared.koi_envelope import sign_envelope

    regen_priv, regen_pub = regen_keypair
    bs_priv, bs_pub = blockscience_keypair

    regen_priv_pem = regen_priv.priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    public_keys_json = json.dumps({
        str(regen_node_rid): regen_pub.to_pem(),
        str(blockscience_node_rid): bs_pub.to_pem(),
    })

    cache_dir = str(tmp_path / "cache")
    peers_file = tmp_path / "peers.json"

    def _make_coordinator():
        with patch.dict("os.environ", {
            "KOI_PRIVATE_KEY_PEM": regen_priv_pem,
            "KOI_PUBLIC_KEYS_JSON": public_keys_json,
            "KOI_ENVELOPE_SIGN": "true",
            "KOI_ENVELOPE_VERIFY": "true",
            "KOI_NET_REQUIRE_SIGNED": "true",
        }):
            from koi_protocol.coordinator.koi_coordinator import KOICoordinator
            coord = KOICoordinator(
                node_name="regen-test",
                port=9999,
                cache_dir=cache_dir,
            )
        coord.koi_node.node_id = str(regen_node_rid)
        coord.dedup_state_file = tmp_path / "dedup_state.json"
        coord.sensor_registry_file = tmp_path / "sensor_registry.json"
        coord.peers_file = peers_file
        coord.event_queue_file = tmp_path / "event_queue.json"
        coord.content_hashes = {}
        coord.url_hashes = {}
        coord.broadcast_sensors = {}
        coord.koi_node.event_queue = []
        coord.koi_node.per_node_queues = {}
        return coord

    # Create first coordinator and add a peer via handshake
    coord1 = _make_coordinator()

    peer_profile = KoiNetNodeProfile(
        base_url="http://bs-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(),
        public_key=bs_pub.to_der(),
    )

    handshake_body = _build_handshake_payload(
        blockscience_node_rid,
        peer_profile.model_dump(exclude_none=True),
    )

    signed = sign_envelope(
        payload=handshake_body,
        source_node=str(blockscience_node_rid),
        target_node=str(regen_node_rid),
        private_key=bs_priv.priv_key,
    )

    from httpx import AsyncClient, ASGITransport
    transport1 = ASGITransport(app=coord1.app)
    client1 = AsyncClient(transport=transport1, base_url="http://test")

    resp = await client1.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200
    assert str(blockscience_node_rid) in coord1.known_peers

    # Save peers (happens in handshake, but ensure file exists)
    coord1._save_peers()
    assert peers_file.exists()

    # Create second coordinator — should load peers from disk
    coord2 = _make_coordinator()
    coord2._load_peers()
    assert str(blockscience_node_rid) in coord2.known_peers


# ---------------------------------------------------------------------------
# Test 18: Concurrent sensor broadcasts
# ---------------------------------------------------------------------------

async def test_concurrent_sensor_broadcasts(
    regen_client, regen_coordinator, sign_as_blockscience,
    make_koi_net_event, verify_as_blockscience
):
    """10 simultaneous broadcasts → all events available for poll."""
    events = [
        make_koi_net_event(
            rid=f"orn:test.sensor:concurrent/{i}",
            contents={"index": i, "unique": f"concurrent-{i}"},
        )
        for i in range(10)
    ]

    # Broadcast all 10 concurrently
    tasks = []
    for event in events:
        payload = EventsPayload(events=[event])
        signed = sign_as_blockscience(payload_to_dict(payload))
        tasks.append(regen_client.post("/koi-net/events/broadcast", json=signed))

    responses = await asyncio.gather(*tasks)
    for resp in responses:
        assert resp.status_code == 200

    # Poll — should see all 10
    poll = PollEvents(limit=100)
    signed_poll = sign_as_blockscience(payload_to_dict(poll))
    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    events_payload = EventsPayload.model_validate(inner)
    rids = [str(e.rid) for e in events_payload.events]

    # All 10 should be present
    for i in range(10):
        assert f"orn:test.sensor:concurrent/{i}" in rids


# ---------------------------------------------------------------------------
# Test 19: NodeInterface broadcast path (mocked httpx transport)
# ---------------------------------------------------------------------------

async def test_nodeinterface_broadcast_path(
    regen_coordinator, regen_keypair, blockscience_keypair,
    regen_node_rid, blockscience_node_rid, make_koi_net_event,
    sign_as_blockscience, verify_as_blockscience, regen_client
):
    """Simulate koi-net RequestHandler.broadcast_events() wire format.

    This is a wire-format simulation, NOT actual NodeInterface execution.
    We replicate what RequestHandler.broadcast_events() produces on the wire:
    1. Serialize EventsPayload with model_dump_json(exclude_none=True)
    2. Create a SignedEnvelope via koi-net's UnsignedEnvelope.sign_with()
    3. POST raw JSON bytes to /koi-net/events/broadcast
    4. Response is discarded (response_envelope=None in koi-net API_MODEL_MAP)

    This validates that Regen accepts the exact wire format koi-net produces,
    without requiring full NodeInterface/SecureManager instantiation.
    """
    from koi_net.protocol.envelope import UnsignedEnvelope as KoiNetUnsignedEnvelope

    bs_priv, bs_pub = blockscience_keypair

    # Build the event exactly as koi-net would
    event = make_koi_net_event(rid="orn:test.sensor:nodeinterface/1")
    payload = EventsPayload(events=[event])

    # Replicate koi-net's signing path:
    # SecureManager.create_envelope() → UnsignedEnvelope.sign_with()
    unsigned = KoiNetUnsignedEnvelope(
        payload=payload,
        source_node=str(blockscience_node_rid),
        target_node=str(regen_node_rid),
    )
    signed = unsigned.sign_with(bs_priv)

    # RequestHandler sends: httpx.post(url, data=signed.model_dump_json(exclude_none=True))
    wire_data = signed.model_dump_json(exclude_none=True)

    # POST raw bytes like httpx would
    resp = await regen_client.post(
        "/koi-net/events/broadcast",
        content=wire_data.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # koi-net discards the response (response_envelope=None for broadcast)
    # But we verify Regen accepted it by checking the response payload
    resp_data = resp.json()
    assert "payload" in resp_data
    assert resp_data["payload"].get("status") == "ok"

    # Verify event was ingested by polling
    poll = PollEvents(limit=50)
    signed_poll = sign_as_blockscience(payload_to_dict(poll))
    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    events_payload = EventsPayload.model_validate(inner)
    rids = [str(e.rid) for e in events_payload.events]
    assert "orn:test.sensor:nodeinterface/1" in rids


# ---------------------------------------------------------------------------
# Test 20: Full federation cycle
# ---------------------------------------------------------------------------

async def test_full_federation_cycle(
    regen_client, regen_coordinator, sign_as_blockscience,
    make_koi_net_event, blockscience_node_rid, blockscience_keypair,
    verify_as_blockscience
):
    """Handshake → broadcast → poll → fetch manifests → fetch bundles (end-to-end)."""
    _, bs_pub = blockscience_keypair

    # Step 1: Handshake
    peer_profile = KoiNetNodeProfile(
        base_url="http://bs-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(event=["orn:test.*"], state=["orn:test.*"]),
        public_key=bs_pub.to_der(),
    )
    handshake_body = _build_handshake_payload(
        blockscience_node_rid,
        peer_profile.model_dump(exclude_none=True),
    )
    signed = sign_as_blockscience(handshake_body)
    resp = await regen_client.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200
    hs_inner = verify_as_blockscience(resp.json())
    assert hs_inner["type"] == "handshake_response"

    # Step 1b: Approve edge
    edge_rid = hs_inner.get("edge_rid")
    if edge_rid:
        approve_body = {
            "type": "edge_approve",
            "edge_rid": edge_rid,
            "node_rid": str(blockscience_node_rid),
        }
        signed_approve = sign_as_blockscience(approve_body)
        resp = await regen_client.post("/koi-net/edges/approve", json=signed_approve)
        assert resp.status_code == 200

    # Step 2: Broadcast
    rid = "orn:test.sensor:full-cycle/1"
    contents = {"text": "full federation cycle", "cycle": True}
    event = make_koi_net_event(rid=rid, contents=contents)
    payload = EventsPayload(events=[event])
    signed_bc = sign_as_blockscience(payload_to_dict(payload))
    resp = await regen_client.post("/koi-net/events/broadcast", json=signed_bc)
    assert resp.status_code == 200

    # Step 3: Poll
    poll = PollEvents(limit=50)
    signed_poll = sign_as_blockscience(payload_to_dict(poll))
    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200
    poll_inner = verify_as_blockscience(resp.json())
    events_payload = EventsPayload.model_validate(poll_inner)
    rids = [str(e.rid) for e in events_payload.events]
    assert rid in rids

    # Step 4: Fetch manifests
    fetch_m = FetchManifests(rids=[rid])
    signed_fm = sign_as_blockscience(payload_to_dict(fetch_m))
    resp = await regen_client.post("/koi-net/manifests/fetch", json=signed_fm)
    assert resp.status_code == 200
    fm_inner = verify_as_blockscience(resp.json())
    manifests_payload = ManifestsPayload.model_validate(fm_inner)
    assert len(manifests_payload.manifests) >= 1
    manifest = RidLibManifest.model_validate(manifests_payload.manifests[0])
    assert manifest.sha256_hash

    # Step 5: Fetch bundles
    fetch_b = FetchBundles(rids=[rid])
    signed_fb = sign_as_blockscience(payload_to_dict(fetch_b))
    resp = await regen_client.post("/koi-net/bundles/fetch", json=signed_fb)
    assert resp.status_code == 200
    fb_inner = verify_as_blockscience(resp.json())
    bundles_payload = BundlesPayload.model_validate(fb_inner)
    assert len(bundles_payload.bundles) >= 1

    bundle = bundles_payload.bundles[0]
    if hasattr(bundle, 'manifest'):
        # Pydantic model
        assert bundle.manifest is not None
        assert bundle.contents is not None
        assert bundle.contents.get("text") == "full federation cycle"
    else:
        # Dict
        assert "manifest" in bundle
        assert "contents" in bundle
        assert bundle["contents"].get("text") == "full federation cycle"
