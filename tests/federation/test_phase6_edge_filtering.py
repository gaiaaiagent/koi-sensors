"""
Phase 6 + 6a — Edge RID-Type Filtering Tests

Tests that edge rid_types filtering works correctly when KOI_NET_EDGE_FILTERING
is enabled. Phase 6: 3 core tests. Phase 6a: 6 policy/bug-fix tests.

1. Positive: matching RID type is delivered
2. Negative: non-matching RID type is blocked
3. Backward-compat: empty rid_types delivers all events
4. (6a) Filtered event not marked as delivered — available to second peer
5. (6a) No approved edge returns empty when REQUIRE_APPROVED_EDGE_FOR_POLL=true
6. (6a) Unsigned poll with required edge returns empty
7. (6a) Inbound broadcast denied returns 403
8. (6a) Auto-approve disabled keeps edge PROPOSED
9. (6a) Aliased peer RID (16/64-char) matches edge

Requires Python 3.12+ (koi-net 1.2.4 uses PEP 695 type aliases).
"""

import sys
from pathlib import Path

import pytest
if sys.version_info < (3, 12):
    pytest.skip("koi-net requires Python 3.12+", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import json
from unittest.mock import patch

from koi_net.protocol.api_models import EventsPayload, PollEvents

from .conftest import payload_to_dict

pytestmark = [pytest.mark.anyio, pytest.mark.federation]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# -----------------------------------------------------------------------
# Additional keypair fixture for second-peer tests
# -----------------------------------------------------------------------

@pytest.fixture
def second_peer_keypair():
    """Generate ECDSA P-256 keypair for a second peer node."""
    from koi_net.protocol.secure import PrivateKey as KoiNetPrivateKey
    priv = KoiNetPrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


@pytest.fixture
def second_peer_node_rid(second_peer_keypair):
    """Stable test node RID for second peer."""
    _, pub = second_peer_keypair
    return pub.to_node_rid("second-peer")


@pytest.fixture
def filtering_coordinator(tmp_path, regen_keypair, blockscience_keypair, regen_node_rid, blockscience_node_rid,
                           second_peer_keypair, second_peer_node_rid):
    """Coordinator with KOI_NET_EDGE_FILTERING=true for Phase 6 tests."""
    from cryptography.hazmat.primitives import serialization

    regen_priv, regen_pub = regen_keypair
    bs_priv, bs_pub = blockscience_keypair
    sp_priv, sp_pub = second_peer_keypair

    regen_priv_pem = regen_priv.priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    public_keys_json = json.dumps({
        str(regen_node_rid): regen_pub.to_pem(),
        str(blockscience_node_rid): bs_pub.to_pem(),
        str(second_peer_node_rid): sp_pub.to_pem(),
    })

    cache_dir = str(tmp_path / "cache")

    with patch.dict("os.environ", {
        "KOI_PRIVATE_KEY_PEM": regen_priv_pem,
        "KOI_PUBLIC_KEYS_JSON": public_keys_json,
        "KOI_ENVELOPE_SIGN": "true",
        "KOI_ENVELOPE_VERIFY": "true",
        "KOI_NET_REQUIRE_SIGNED": "true",
        "KOI_NET_EDGE_FILTERING": "true",
    }):
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator
        coord = KOICoordinator(
            node_name="regen-test",
            port=9999,
            cache_dir=cache_dir,
        )

    regen_priv_key = regen_priv.priv_key
    coord.koi_node.node_id = str(regen_node_rid)
    coord.koi_node.private_key = regen_priv_key
    coord.koi_node.public_key = regen_priv_key.public_key()
    coord.envelope_private_key = regen_priv_key
    coord.envelope_public_keys[str(regen_node_rid)] = regen_priv_key.public_key()

    coord.dedup_state_file = tmp_path / "dedup_state.json"
    coord.sensor_registry_file = tmp_path / "sensor_registry.json"
    coord.peers_file = tmp_path / "peers.json"
    coord.event_queue_file = tmp_path / "event_queue.json"
    coord.content_hashes = {}
    coord.url_hashes = {}
    coord.broadcast_sensors = {}

    coord.koi_node.event_queue = []
    coord.koi_node.per_node_queues = {}

    return coord


@pytest.fixture
def filtering_client(filtering_coordinator):
    """Async test client for the filtering coordinator."""
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=filtering_coordinator.app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def sign_as_second_peer(second_peer_keypair, second_peer_node_rid, regen_node_rid):
    """Helper to sign a payload as the second peer node targeting Regen."""
    from shared.koi_envelope import sign_envelope
    sp_priv, _ = second_peer_keypair

    def _sign(payload: dict) -> dict:
        return sign_envelope(
            payload=payload,
            source_node=str(second_peer_node_rid),
            target_node=str(regen_node_rid),
            private_key=sp_priv.priv_key,
        )

    return _sign


@pytest.fixture
def verify_as_second_peer(regen_keypair):
    """Helper to verify a signed response from Regen using Regen's public key."""
    _, regen_pub = regen_keypair

    def _verify(response_body: dict):
        from shared.koi_envelope import verify_envelope_with_key
        verify_envelope_with_key(response_body, regen_pub.pub_key)
        return response_body["payload"]

    return _verify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _broadcast_event(client, sign_fn, make_event_fn, rid):
    """Broadcast a single event with the given RID."""
    event = make_event_fn(rid=rid)
    payload = EventsPayload(events=[event])
    signed = sign_fn(payload_to_dict(payload))
    resp = await client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200
    return resp


async def _poll_events(client, sign_fn, verify_fn, limit=50):
    """Poll and return list of RID strings from the response."""
    poll = PollEvents(limit=limit)
    signed = sign_fn(payload_to_dict(poll))
    resp = await client.post("/koi-net/events/poll", json=signed)
    assert resp.status_code == 200
    inner = verify_fn(resp.json())
    events_payload = EventsPayload.model_validate(inner)
    return [str(e.rid) for e in events_payload.events]


# ---------------------------------------------------------------------------
# Test 1: Positive — matching RID type is delivered
# ---------------------------------------------------------------------------

async def test_matching_rid_type_delivered(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, blockscience_node_rid, regen_node_rid,
    make_koi_net_event
):
    """Events matching edge rid_types are delivered through poll."""
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    # Create edge allowing only test.allowed type
    edge_rid = "orn:koi-net.edge:test-positive"
    filtering_coordinator.edges[edge_rid] = EdgeProfile(
        source=str(regen_node_rid),
        target=str(blockscience_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=["orn:test.allowed"],
    )

    # Broadcast a matching event
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.allowed:item/1"
    )

    # Poll — should receive the matching event
    rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert "orn:test.allowed:item/1" in rids


# ---------------------------------------------------------------------------
# Test 2: Negative — non-matching RID type is blocked
# ---------------------------------------------------------------------------

async def test_nonmatching_rid_type_blocked(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, blockscience_node_rid, regen_node_rid,
    make_koi_net_event
):
    """Events NOT matching edge rid_types are filtered out of poll results."""
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    # Create edge allowing only test.allowed type
    edge_rid = "orn:koi-net.edge:test-negative"
    filtering_coordinator.edges[edge_rid] = EdgeProfile(
        source=str(regen_node_rid),
        target=str(blockscience_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=["orn:test.allowed"],
    )

    # Broadcast a blocked event (not in allowed types)
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.blocked:item/1"
    )

    # Also broadcast a matching event so poll isn't empty due to other reasons
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.allowed:item/2"
    )

    # Poll — should receive allowed but NOT blocked
    rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert "orn:test.allowed:item/2" in rids
    assert "orn:test.blocked:item/1" not in rids


# ---------------------------------------------------------------------------
# Test 3: Backward compat — empty rid_types delivers all events
# ---------------------------------------------------------------------------

async def test_empty_rid_types_delivers_all(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, blockscience_node_rid, regen_node_rid,
    make_koi_net_event
):
    """Empty rid_types on edge means allow all (backward compatible)."""
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    # Create edge with empty rid_types (allow all)
    edge_rid = "orn:koi-net.edge:test-compat"
    filtering_coordinator.edges[edge_rid] = EdgeProfile(
        source=str(regen_node_rid),
        target=str(blockscience_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=[],  # Empty = allow all
    )

    # Broadcast events of different types
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.typeA:item/1"
    )
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.typeB:item/1"
    )

    # Poll — should receive ALL events (no filtering applied)
    rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert "orn:test.typeA:item/1" in rids
    assert "orn:test.typeB:item/1" in rids


# ===========================================================================
# Phase 6a Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Test 4: Filtered event NOT marked as delivered — still available to 2nd peer
# ---------------------------------------------------------------------------

async def test_filtered_event_not_marked_delivered(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, sign_as_second_peer, verify_as_second_peer,
    blockscience_node_rid, second_peer_node_rid, regen_node_rid,
    make_koi_net_event
):
    """Events filtered out by rid_types must NOT be marked as delivered.

    Broadcast both allowed and blocked events. Poll as Octo (filtered edge) —
    blocked event not returned. Poll as second peer (allow-all edge) — blocked
    event IS returned because it was never marked delivered.
    """
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    # Edge for blockscience: only allow test.allowed
    filtering_coordinator.edges["orn:koi-net.edge:bs-filtered"] = EdgeProfile(
        source=str(regen_node_rid),
        target=str(blockscience_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=["orn:test.allowed"],
    )
    # Edge for second peer: allow all (empty rid_types)
    filtering_coordinator.edges["orn:koi-net.edge:sp-all"] = EdgeProfile(
        source=str(regen_node_rid),
        target=str(second_peer_node_rid),
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=[],
    )

    # Broadcast a blocked event and an allowed event
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.blocked:item/delivery1"
    )
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.allowed:item/delivery1"
    )

    # Poll as blockscience — should only get allowed event
    bs_rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert "orn:test.allowed:item/delivery1" in bs_rids
    assert "orn:test.blocked:item/delivery1" not in bs_rids

    # Poll as second peer — should get BOTH (blocked event was not marked delivered)
    poll = PollEvents(limit=50)
    signed = sign_as_second_peer(payload_to_dict(poll))
    resp = await filtering_client.post("/koi-net/events/poll", json=signed)
    assert resp.status_code == 200
    inner = verify_as_second_peer(resp.json())
    sp_payload = EventsPayload.model_validate(inner)
    sp_rids = [str(e.rid) for e in sp_payload.events]
    assert "orn:test.blocked:item/delivery1" in sp_rids


# ---------------------------------------------------------------------------
# Test 5: No approved edge → empty events when REQUIRE_APPROVED_EDGE_FOR_POLL=true
# ---------------------------------------------------------------------------

async def test_no_approved_edge_returns_empty(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, blockscience_node_rid, regen_node_rid,
    make_koi_net_event
):
    """With REQUIRE_APPROVED_EDGE_FOR_POLL=true and no approved edge,
    signed poll returns empty events_payload."""
    # Enable require approved edge
    filtering_coordinator.koi_net_require_approved_edge_for_poll = True

    # Broadcast an event (no edge for blockscience)
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.sensor:no-edge/1"
    )

    # Poll as blockscience — should get empty
    rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert rids == []


# ---------------------------------------------------------------------------
# Test 6: Unsigned poll with REQUIRE_APPROVED_EDGE_FOR_POLL=true → empty
# ---------------------------------------------------------------------------

async def test_unsigned_poll_with_required_edge_returns_empty(
    tmp_path, regen_keypair, blockscience_keypair, regen_node_rid,
    blockscience_node_rid, second_peer_keypair, second_peer_node_rid,
    make_koi_net_event
):
    """With REQUIRE_APPROVED_EDGE_FOR_POLL=true and REQUIRE_SIGNED=false,
    unsigned poll returns empty events_payload."""
    from cryptography.hazmat.primitives import serialization
    from httpx import AsyncClient, ASGITransport

    regen_priv, regen_pub = regen_keypair
    bs_priv, bs_pub = blockscience_keypair
    sp_priv, sp_pub = second_peer_keypair

    regen_priv_pem = regen_priv.priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    public_keys_json = json.dumps({
        str(regen_node_rid): regen_pub.to_pem(),
        str(blockscience_node_rid): bs_pub.to_pem(),
        str(second_peer_node_rid): sp_pub.to_pem(),
    })

    cache_dir = str(tmp_path / "cache_unsigned")

    with patch.dict("os.environ", {
        "KOI_PRIVATE_KEY_PEM": regen_priv_pem,
        "KOI_PUBLIC_KEYS_JSON": public_keys_json,
        "KOI_ENVELOPE_SIGN": "true",
        "KOI_ENVELOPE_VERIFY": "true",
        "KOI_NET_REQUIRE_SIGNED": "false",
        "KOI_NET_EDGE_FILTERING": "true",
        "KOI_NET_REQUIRE_APPROVED_EDGE_FOR_POLL": "true",
    }):
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator
        coord = KOICoordinator(node_name="regen-test", port=9998, cache_dir=cache_dir)

    regen_priv_key = regen_priv.priv_key
    coord.koi_node.node_id = str(regen_node_rid)
    coord.koi_node.private_key = regen_priv_key
    coord.koi_node.public_key = regen_priv_key.public_key()
    coord.envelope_private_key = regen_priv_key
    coord.envelope_public_keys[str(regen_node_rid)] = regen_priv_key.public_key()
    coord.dedup_state_file = tmp_path / "dedup_state.json"
    coord.sensor_registry_file = tmp_path / "sensor_registry.json"
    coord.peers_file = tmp_path / "peers.json"
    coord.event_queue_file = tmp_path / "event_queue.json"
    coord.content_hashes = {}
    coord.url_hashes = {}
    coord.broadcast_sensors = {}
    coord.koi_node.event_queue = []
    coord.koi_node.per_node_queues = {}

    client = AsyncClient(
        transport=ASGITransport(app=coord.app), base_url="http://test"
    )

    # Unsigned poll — should get empty because require_approved_edge=true
    poll_payload = {"type": "poll_events", "limit": 50}
    resp = await client.post("/koi-net/events/poll", json=poll_payload)
    assert resp.status_code == 200
    body = resp.json()
    events = body.get("events", [])
    assert events == []


# ---------------------------------------------------------------------------
# Test 7: Inbound broadcast denied → 403
# ---------------------------------------------------------------------------

async def test_inbound_broadcast_denied_returns_403(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    blockscience_node_rid, make_koi_net_event
):
    """With KOI_NET_INBOUND_BROADCAST=deny, broadcast returns 403 and
    event is not queued."""
    filtering_coordinator.koi_net_inbound_broadcast = "deny"

    event = make_koi_net_event(rid="orn:test.sensor:denied/1")
    payload = EventsPayload(events=[event])
    signed = sign_as_blockscience(payload_to_dict(payload))

    resp = await filtering_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 403

    # Verify event was not queued
    assert len(filtering_coordinator.koi_node.event_queue) == 0


# ---------------------------------------------------------------------------
# Test 8: Auto-approve disabled → edge stays PROPOSED
# ---------------------------------------------------------------------------

async def test_auto_approve_disabled_edge_stays_proposed(
    filtering_coordinator, blockscience_node_rid, regen_node_rid
):
    """With KOI_NET_AUTO_APPROVE_EDGES=false, handshake_with() leaves
    the proposed edge as PROPOSED (does not auto-approve)."""
    from koi_protocol.protocol.edge import EdgeStatus

    filtering_coordinator.koi_net_auto_approve_edges = False

    # Simulate what handshake_with() does: it calls a remote endpoint.
    # Instead of a full handshake, we test the edge logic directly by
    # simulating the handshake response scenario.
    # We mock the remote server to return a proposed edge.
    import httpx
    from unittest.mock import AsyncMock

    peer_rid = str(blockscience_node_rid)
    edge_rid = f"orn:koi-net.edge:auto-approve-test"

    mock_handshake_response = {
        "node_rid": peer_rid,
        "profile": {
            "node_rid": peer_rid,
            "node_name": "blockscience-test",
            "base_url": "http://localhost:9998/koi-net",
            "node_type": "full",
            "provides": [],
        },
        "proposed_edge": {
            "source": peer_rid,
            "target": str(regen_node_rid),
            "edge_type": "POLL",
            "status": "PROPOSED",
            "rid_types": [],
        },
        "edge_rid": edge_rid,
    }

    mock_health_response = httpx.Response(
        200, json={"status": "ok", "node_id": peer_rid}
    )
    mock_hs_response = httpx.Response(200, json=mock_handshake_response)

    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_health_response)
        mock_client.post = AsyncMock(return_value=mock_hs_response)

        result = await filtering_coordinator.handshake_with(
            peer_rid, "http://localhost:9998/koi-net"
        )

    assert result is True
    # Edge should be PROPOSED, not APPROVED
    assert edge_rid in filtering_coordinator.edges
    assert filtering_coordinator.edges[edge_rid].status == EdgeStatus.PROPOSED


# ---------------------------------------------------------------------------
# Test 9: Aliased peer RID (16/64-char hash) matches edge
# ---------------------------------------------------------------------------

async def test_aliased_peer_rid_matches_edge(
    filtering_client, filtering_coordinator, sign_as_blockscience,
    verify_as_blockscience, blockscience_node_rid, regen_node_rid,
    make_koi_net_event
):
    """Edge target with 64-char hash matches polling source with 16-char hash
    (or vice versa) — events still delivered through the alias-aware match."""
    from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

    bs_rid = str(blockscience_node_rid)
    # Extract prefix and create a 16-char alias
    prefix, full_hash = bs_rid.rsplit("+", 1)
    short_hash = full_hash[:16]
    short_rid = f"{prefix}+{short_hash}"

    # Create edge using the SHORT (16-char) RID as target
    filtering_coordinator.edges["orn:koi-net.edge:alias-test"] = EdgeProfile(
        source=str(regen_node_rid),
        target=short_rid,  # 16-char alias
        edge_type=EdgeType.POLL,
        status=EdgeStatus.APPROVED,
        rid_types=["orn:test.aliased"],
    )

    # Broadcast a matching event
    await _broadcast_event(
        filtering_client, sign_as_blockscience, make_koi_net_event,
        rid="orn:test.aliased:item/1"
    )

    # Poll as blockscience (whose source_node is the 64-char RID) —
    # alias-aware matching should find the edge with the 16-char target
    rids = await _poll_events(
        filtering_client, sign_as_blockscience, verify_as_blockscience
    )
    assert "orn:test.aliased:item/1" in rids
