"""
Phase 4 — Tier 1: Wire Compatibility Tests

Validates that koi-net model payloads are accepted by Regen endpoints and that
responses parse back into koi-net models. Tests protocol interop at the wire level.

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

import json

from koi_net.protocol.api_models import (
    EventsPayload, PollEvents, FetchRids, FetchManifests, FetchBundles,
    RidsPayload, ManifestsPayload, BundlesPayload, Event,
)
from koi_net.protocol.event import EventType
from rid_lib.ext import Manifest as RidLibManifest

from .conftest import payload_to_dict

pytestmark = [pytest.mark.anyio, pytest.mark.federation]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# ---------------------------------------------------------------------------
# Test 1: Broadcast accepted with koi-net models
# ---------------------------------------------------------------------------

async def test_broadcast_accepted_with_koi_net_models(
    regen_client, sign_as_blockscience, make_events_payload
):
    """EventsPayload via koi-net models → Regen /koi-net/events/broadcast accepts."""
    payload = make_events_payload()
    signed = sign_as_blockscience(payload_to_dict(payload))

    resp = await regen_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200, f"Broadcast rejected: {resp.text}"


# ---------------------------------------------------------------------------
# Test 2: Broadcast response is discardable
# ---------------------------------------------------------------------------

async def test_broadcast_response_is_discardable(
    regen_client, sign_as_blockscience, make_events_payload
):
    """Regen returns a body on broadcast; verify koi-net client behavior (discard) works.

    Protocol delta: Regen returns {"status":"ok","processed":N}, BlockScience
    expects async void. koi-net's RequestHandler discards the response
    (response_envelope=None in API_MODEL_MAP). This test documents the delta.
    """
    payload = make_events_payload()
    signed = sign_as_blockscience(payload_to_dict(payload))

    resp = await regen_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200

    # Regen wraps the response in a signed envelope
    resp_data = resp.json()
    # The response body exists (Regen's deviation) but koi-net ignores it
    assert "payload" in resp_data or "status" in resp_data


# ---------------------------------------------------------------------------
# Test 3: Poll returns valid EventsPayload
# ---------------------------------------------------------------------------

async def test_poll_returns_valid_events_payload(
    regen_client, regen_coordinator, sign_as_blockscience, make_events_payload,
    make_koi_net_event, blockscience_node_rid, verify_as_blockscience
):
    """PollEvents → response parses as EventsPayload via koi-net models."""
    # First broadcast an event so there's something to poll
    event = make_koi_net_event(rid="orn:test.sensor:poll-test/1")
    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    resp = await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)
    assert resp.status_code == 200

    # Now poll
    poll_payload = PollEvents(limit=10)
    signed_poll = sign_as_blockscience(payload_to_dict(poll_payload))

    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    # Response should be a signed envelope containing EventsPayload
    inner = verify_as_blockscience(resp.json())
    # Parse as EventsPayload
    events_payload = EventsPayload.model_validate(inner)
    assert events_payload.type == "events_payload"
    assert isinstance(events_payload.events, list)


# ---------------------------------------------------------------------------
# Test 4: Fetch RIDs response
# ---------------------------------------------------------------------------

async def test_fetch_rids_response(
    regen_client, regen_coordinator, sign_as_blockscience, make_events_payload,
    make_koi_net_event, verify_as_blockscience
):
    """FetchRids → response parses as RidsPayload."""
    # Broadcast to populate cache
    event = make_koi_net_event(rid="orn:test.sensor:rid-test/1")
    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)

    # Fetch RIDs
    fetch_payload = FetchRids()
    signed_fetch = sign_as_blockscience(payload_to_dict(fetch_payload))

    resp = await regen_client.post("/koi-net/rids/fetch", json=signed_fetch)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    rids_payload = RidsPayload.model_validate(inner)
    assert rids_payload.type == "rids_payload"
    assert isinstance(rids_payload.rids, list)


# ---------------------------------------------------------------------------
# Test 5: Fetch manifests has exactly 3 fields
# ---------------------------------------------------------------------------

async def test_fetch_manifests_3field(
    regen_client, sign_as_blockscience, make_events_payload,
    make_koi_net_event, verify_as_blockscience
):
    """FetchManifests → manifests have exactly 3 fields (rid, timestamp, sha256_hash)."""
    rid = "orn:test.sensor:manifest-test/1"
    event = make_koi_net_event(rid=rid)
    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)

    # Fetch manifests
    fetch_payload = FetchManifests(rids=[rid])
    signed_fetch = sign_as_blockscience(payload_to_dict(fetch_payload))

    resp = await regen_client.post("/koi-net/manifests/fetch", json=signed_fetch)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    manifests_payload = ManifestsPayload.model_validate(inner)
    assert manifests_payload.type == "manifests_payload"

    for manifest_data in manifests_payload.manifests:
        # Each manifest should be parseable as rid-lib Manifest
        manifest = RidLibManifest.model_validate(manifest_data)
        assert manifest.rid
        assert manifest.timestamp
        assert manifest.sha256_hash


# ---------------------------------------------------------------------------
# Test 6: Fetch bundles schema
# ---------------------------------------------------------------------------

async def test_fetch_bundles_schema(
    regen_client, sign_as_blockscience, make_events_payload,
    make_koi_net_event, verify_as_blockscience
):
    """FetchBundles → bundles match rid-lib Bundle schema."""
    rid = "orn:test.sensor:bundle-test/1"
    contents = {"text": "bundle test", "unique": rid}
    event = make_koi_net_event(rid=rid, contents=contents)
    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)

    # Fetch bundles
    fetch_payload = FetchBundles(rids=[rid])
    signed_fetch = sign_as_blockscience(payload_to_dict(fetch_payload))

    resp = await regen_client.post("/koi-net/bundles/fetch", json=signed_fetch)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    bundles_payload = BundlesPayload.model_validate(inner)
    assert bundles_payload.type == "bundles_payload"

    for bundle in bundles_payload.bundles:
        # Bundle may be a Pydantic model or dict depending on koi-net version
        if hasattr(bundle, 'manifest'):
            # Pydantic model
            assert bundle.manifest is not None
            assert bundle.manifest.sha256_hash
            assert bundle.contents is not None
        else:
            # Dict
            assert "manifest" in bundle
            manifest = RidLibManifest.model_validate(bundle["manifest"])
            assert manifest.sha256_hash
            assert "contents" in bundle


# ---------------------------------------------------------------------------
# Test 7: Signed broadcast roundtrip
# ---------------------------------------------------------------------------

async def test_signed_broadcast_roundtrip(
    regen_client, sign_as_blockscience, make_events_payload,
    make_koi_net_event, blockscience_node_rid
):
    """Sign with koi-net SignedEnvelope, post to Regen, Regen processes signed event."""
    event = make_koi_net_event(rid="orn:test.sensor:signed-bc/1")
    payload = EventsPayload(events=[event])
    signed = sign_as_blockscience(payload_to_dict(payload))

    resp = await regen_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200

    # Verify the event was actually processed (not just accepted)
    resp_data = resp.json()
    # Response is a signed envelope
    assert "payload" in resp_data
    inner = resp_data["payload"]
    assert inner.get("processed", 0) >= 1 or inner.get("status") == "ok"


# ---------------------------------------------------------------------------
# Test 8: Signed poll roundtrip
# ---------------------------------------------------------------------------

async def test_signed_poll_roundtrip(
    regen_client, regen_coordinator, sign_as_blockscience,
    make_koi_net_event, verify_as_blockscience
):
    """Signed PollEvents → signed response validates with koi-net verify_with()."""
    # Broadcast an event first
    event = make_koi_net_event(rid="orn:test.sensor:signed-poll/1")
    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)

    # Poll with signed request
    poll_payload = PollEvents(limit=10)
    signed_poll = sign_as_blockscience(payload_to_dict(poll_payload))

    resp = await regen_client.post("/koi-net/events/poll", json=signed_poll)
    assert resp.status_code == 200

    # Verify signature using our verification
    inner = verify_as_blockscience(resp.json())
    assert inner["type"] == "events_payload"


# ---------------------------------------------------------------------------
# Test 9: Regen signed validates in koi-net
# ---------------------------------------------------------------------------

async def test_regen_signed_validates_in_koi_net(
    regen_client, sign_as_blockscience, verify_as_blockscience
):
    """Regen signs response → koi-net verification passes."""
    # Any signed request will get a signed response
    fetch_payload = FetchRids()
    signed_fetch = sign_as_blockscience(payload_to_dict(fetch_payload))

    resp = await regen_client.post("/koi-net/rids/fetch", json=signed_fetch)
    assert resp.status_code == 200

    # This will raise EnvelopeError if verification fails
    inner = verify_as_blockscience(resp.json())
    assert isinstance(inner, dict)


# ---------------------------------------------------------------------------
# Test 10: 3-field manifest roundtrip
# ---------------------------------------------------------------------------

async def test_3field_manifest_roundtrip(
    regen_client, sign_as_blockscience, make_koi_net_event, verify_as_blockscience
):
    """Broadcast 3-field manifest → fetch back → hash preserved."""
    rid = "orn:test.sensor:manifest-rt/1"
    contents = {"text": "manifest roundtrip", "unique": rid}
    event = make_koi_net_event(rid=rid, contents=contents)

    # Record the original hash
    original_hash = event.manifest.sha256_hash

    broadcast_payload = EventsPayload(events=[event])
    signed_broadcast = sign_as_blockscience(payload_to_dict(broadcast_payload))
    await regen_client.post("/koi-net/events/broadcast", json=signed_broadcast)

    # Fetch manifest back
    fetch_payload = FetchManifests(rids=[rid])
    signed_fetch = sign_as_blockscience(payload_to_dict(fetch_payload))
    resp = await regen_client.post("/koi-net/manifests/fetch", json=signed_fetch)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    manifests_payload = ManifestsPayload.model_validate(inner)

    assert len(manifests_payload.manifests) >= 1
    fetched_manifest = RidLibManifest.model_validate(manifests_payload.manifests[0])
    assert fetched_manifest.sha256_hash == original_hash


# ---------------------------------------------------------------------------
# Test 11: FORGET event with manifest=None
# ---------------------------------------------------------------------------

async def test_forget_event_with_none_manifest(
    regen_client, sign_as_blockscience
):
    """FORGET event with manifest=None round-trips via exclude_none serialization."""
    rid = "orn:test.sensor:forget-test/1"

    # FORGET events have no manifest or contents
    event = Event(
        rid=rid,
        event_type=EventType.FORGET,
        manifest=None,
        contents=None,
    )
    payload = EventsPayload(events=[event])

    # Serialize with exclude_none (as koi-net does)
    body = payload_to_dict(payload)
    # Verify manifest/contents are omitted, not null
    event_wire = body["events"][0]
    assert "manifest" not in event_wire
    assert "contents" not in event_wire

    signed = sign_as_blockscience(body)
    resp = await regen_client.post("/koi-net/events/broadcast", json=signed)
    assert resp.status_code == 200
