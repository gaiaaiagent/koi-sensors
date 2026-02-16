"""
Phase 4: Federation Test Fixtures

Shared fixtures for testing Regen ↔ BlockScience koi-net interoperability.
All fixtures enforce KOI_NET_REQUIRE_SIGNED=true to test true federation posture.

Requires Python 3.12+ and koi-net==1.2.4 (install via venv-federation).
"""

import sys
from pathlib import Path

# Add koi-sensors to path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import json
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

# Only use asyncio backend
pytestmark = pytest.mark.anyio


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# -----------------------------------------------------------------------
# Import guard: skip all tests if koi-net is unavailable or incompatible
# -----------------------------------------------------------------------
# koi-net 1.2.4 uses PEP 695 type aliases which require Python 3.12+.
# On Python <3.12, importing koi_net raises SyntaxError (not ImportError).

try:
    from koi_net.protocol.api_models import (
        EventsPayload, PollEvents, FetchRids, FetchManifests, FetchBundles,
        RidsPayload, ManifestsPayload, BundlesPayload, Event,
    )
    from koi_net.protocol.event import EventType
    from koi_net.protocol.node import NodeProfile as KoiNetNodeProfile, NodeType, NodeProvides
    from koi_net.protocol.edge import EdgeProfile as KoiNetEdgeProfile, EdgeType as KoiNetEdgeType
    from koi_net.protocol.envelope import SignedEnvelope as KoiNetSignedEnvelope, UnsignedEnvelope as KoiNetUnsignedEnvelope
    from koi_net.protocol.secure import PrivateKey as KoiNetPrivateKey, PublicKey as KoiNetPublicKey
    from koi_net.protocol.consts import BROADCAST_EVENTS_PATH, POLL_EVENTS_PATH
    from rid_lib.ext import Manifest as RidLibManifest, Bundle as RidLibBundle
    from rid_lib.types import KoiNetNode
    KOI_NET_AVAILABLE = True
except (ImportError, SyntaxError):
    KOI_NET_AVAILABLE = False


federation = pytest.mark.federation
skip_no_koi_net = pytest.mark.skipif(
    not KOI_NET_AVAILABLE,
    reason="koi-net not installed (use venv-federation)"
)


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "federation: Phase 4 federation tests (require koi-net)")


def pytest_collection_modifyitems(config, items):
    """Auto-apply skip marker to federation tests if koi-net unavailable."""
    if not KOI_NET_AVAILABLE:
        federation_dir = str(Path(__file__).parent)
        for item in items:
            if str(item.fspath).startswith(federation_dir):
                item.add_marker(skip_no_koi_net)


# -----------------------------------------------------------------------
# Cryptographic fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def regen_keypair():
    """Generate ECDSA P-256 keypair for the Regen node."""
    priv = KoiNetPrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


@pytest.fixture
def blockscience_keypair():
    """Generate ECDSA P-256 keypair for the BlockScience node."""
    priv = KoiNetPrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


@pytest.fixture
def regen_node_rid(regen_keypair):
    """Stable test node RID for Regen."""
    _, pub = regen_keypair
    return pub.to_node_rid("regen-test")


@pytest.fixture
def blockscience_node_rid(blockscience_keypair):
    """Stable test node RID for BlockScience."""
    _, pub = blockscience_keypair
    return pub.to_node_rid("blockscience-test")


# -----------------------------------------------------------------------
# Coordinator fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def regen_coordinator(tmp_path, regen_keypair, blockscience_keypair, regen_node_rid, blockscience_node_rid):
    """Create a KOICoordinator with signed-only mode for federation testing.

    - KOI_NET_REQUIRE_SIGNED=true (reject unsigned requests on /koi-net/*)
    - Keys configured for both Regen and BlockScience nodes
    - Isolated state in tmp_path
    """
    from cryptography.hazmat.primitives import serialization

    regen_priv, regen_pub = regen_keypair
    bs_priv, bs_pub = blockscience_keypair

    # Build PEM strings for environment
    regen_priv_pem = regen_priv.priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()

    # Public keys JSON: maps node_rid -> PEM
    regen_pub_pem = regen_pub.to_pem()
    bs_pub_pem = bs_pub.to_pem()

    public_keys_json = json.dumps({
        str(regen_node_rid): regen_pub_pem,
        str(blockscience_node_rid): bs_pub_pem,
    })

    cache_dir = str(tmp_path / "cache")

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

    # Override the node_id to match the generated RID
    coord.koi_node.node_id = str(regen_node_rid)

    # Isolate persistent state
    coord.dedup_state_file = tmp_path / "dedup_state.json"
    coord.sensor_registry_file = tmp_path / "sensor_registry.json"
    coord.peers_file = tmp_path / "peers.json"
    coord.event_queue_file = tmp_path / "event_queue.json"
    coord.content_hashes = {}
    coord.url_hashes = {}
    coord.broadcast_sensors = {}

    # Clear event queue (may have loaded from production state before path override)
    coord.koi_node.event_queue = []
    coord.koi_node.per_node_queues = {}

    return coord


@pytest.fixture
def regen_client(regen_coordinator):
    """Async test client for the Regen coordinator's FastAPI app."""
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=regen_coordinator.app)
    return AsyncClient(transport=transport, base_url="http://test")


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

@pytest.fixture
def sign_as_blockscience(blockscience_keypair, blockscience_node_rid, regen_node_rid):
    """Helper to sign a payload as the BlockScience node targeting Regen.

    Uses Regen's envelope signing (shared.koi_envelope) which is wire-compatible
    with koi-net's signing. This avoids datetime serialization issues from
    model_dump() since we sign raw dicts.
    """
    from shared.koi_envelope import sign_envelope
    bs_priv, _ = blockscience_keypair

    def _sign(payload: dict) -> dict:
        return sign_envelope(
            payload=payload,
            source_node=str(blockscience_node_rid),
            target_node=str(regen_node_rid),
            private_key=bs_priv.priv_key,
        )

    return _sign


@pytest.fixture
def verify_as_blockscience(regen_keypair):
    """Helper to verify a signed response from Regen using Regen's public key.

    Uses Regen's verify_envelope_with_key which handles any payload type
    (not just koi-net typed payloads). Returns the inner payload dict.
    """
    _, regen_pub = regen_keypair

    def _verify(response_body: dict):
        from shared.koi_envelope import verify_envelope_with_key
        verify_envelope_with_key(response_body, regen_pub.pub_key)
        return response_body["payload"]

    return _verify


@pytest.fixture
def make_koi_net_event():
    """Helper to build a koi-net Event dict with proper manifest."""
    def _make(rid="orn:test.sensor:item/1", event_type="NEW", contents=None):
        contents = contents or {"text": "hello world", "unique": rid}
        manifest = RidLibManifest.generate(rid, contents)
        event = Event(
            rid=rid,
            event_type=EventType(event_type),
            manifest=manifest,
            contents=contents,
        )
        return event

    return _make


@pytest.fixture
def make_events_payload(make_koi_net_event):
    """Helper to build an EventsPayload with one or more events.

    Returns a tuple of (EventsPayload model, JSON-safe dict) for flexibility.
    Use the model for type-safe operations, the dict for signing/posting.
    """
    def _make(events=None, rid="orn:test.sensor:item/1", event_type="NEW", contents=None):
        if events is None:
            events = [make_koi_net_event(rid=rid, event_type=event_type, contents=contents)]
        return EventsPayload(events=events)

    return _make


def payload_to_dict(payload) -> dict:
    """Convert a Pydantic model to a JSON-safe dict (handles datetime etc).

    Uses model_dump_json → json.loads roundtrip to ensure all types are
    JSON-serializable (datetimes become strings, enums become values, etc).
    """
    return json.loads(payload.model_dump_json(exclude_none=True))
