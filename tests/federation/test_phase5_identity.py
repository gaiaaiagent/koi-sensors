"""
Phase 5 — Federation Identity & Health Tests

Tests key-derived node RID, hash-length aliasing, /koi-net/health endpoint,
signed handshake with approval, and identity migration.

Requires Python 3.12+ (koi-net 1.2.4 uses PEP 695 type aliases).
"""

import sys
from pathlib import Path

import pytest
if sys.version_info < (3, 12):
    pytest.skip("koi-net requires Python 3.12+", allow_module_level=True)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import hashlib
import json
from base64 import b64encode
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

from koi_net.protocol.node import NodeProfile as KoiNetNodeProfile, NodeType, NodeProvides
from rid_lib.ext import Manifest as RidLibManifest

from shared.koi_envelope import (
    derive_node_rid,
    generate_keypair,
    generate_and_save_keypair,
    node_rid_matches_public_key,
    public_key_to_b64der,
    public_key_from_b64der,
    sign_envelope,
    _derive_hash_from_public_key,
)

from .conftest import payload_to_dict

pytestmark = [pytest.mark.anyio, pytest.mark.federation]


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


# ---------------------------------------------------------------------------
# Test: Key-derived node RID format
# ---------------------------------------------------------------------------

def test_key_derived_node_rid_format():
    """RID matches orn:koi-net.node:{name}+{64char_hash}."""
    _, pub = generate_keypair()
    rid = derive_node_rid("test-node", pub)

    assert rid.startswith("orn:koi-net.node:test-node+")
    suffix = rid.split("+", 1)[1]
    assert len(suffix) == 64
    # Verify it's valid hex
    int(suffix, 16)


def test_node_rid_derives_from_keypair():
    """Same key always produces same RID (deterministic)."""
    priv, pub = generate_keypair()
    rid1 = derive_node_rid("stable", pub)
    rid2 = derive_node_rid("stable", pub)
    assert rid1 == rid2


def test_node_rid_different_keys_different_rids():
    """Different keys produce different RIDs."""
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    rid1 = derive_node_rid("node", pub1)
    rid2 = derive_node_rid("node", pub2)
    assert rid1 != rid2


def test_derive_node_rid_matches_blockscience_pattern():
    """Hash derivation matches BlockScience's sha256(base64(DER)) pattern."""
    _, pub = generate_keypair()
    rid = derive_node_rid("test", pub)
    suffix = rid.split("+")[1]

    # Manually compute the same hash
    der = pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    expected = hashlib.sha256(b64encode(der)).hexdigest()
    assert suffix == expected


def test_config_and_koi_node_derive_same_rid(tmp_path):
    """Both config.py and koi_node.py use derive_node_rid — single source of truth."""
    # Generate a key and save it
    priv, pub = generate_keypair()
    key_path = str(tmp_path / "node_private_key.pem")
    from shared.koi_envelope import save_private_key
    save_private_key(priv, key_path)

    # Derive via shared function
    rid_shared = derive_node_rid("test-node", pub)

    # Derive via generate_and_save_keypair (what koi_node.py uses)
    loaded_priv, loaded_pub = generate_and_save_keypair(key_path)
    rid_loaded = derive_node_rid("test-node", loaded_pub)

    assert rid_shared == rid_loaded


# ---------------------------------------------------------------------------
# Test: node_rid_matches_public_key
# ---------------------------------------------------------------------------

def test_node_rid_matches_64char():
    """64-char hash matches with allow_der64=True."""
    _, pub = generate_keypair()
    rid = derive_node_rid("test", pub)
    assert node_rid_matches_public_key(rid, pub)


def test_node_rid_matches_16char_legacy():
    """16-char truncated hash matches with allow_legacy16=True."""
    _, pub = generate_keypair()
    full_hash = _derive_hash_from_public_key(pub)
    legacy_rid = f"orn:koi-net.node:test+{full_hash[:16]}"
    assert node_rid_matches_public_key(legacy_rid, pub)


def test_node_rid_mismatch():
    """Wrong key doesn't match."""
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    rid = derive_node_rid("test", pub1)
    assert not node_rid_matches_public_key(rid, pub2)


# ---------------------------------------------------------------------------
# Test: public_key_to_b64der / public_key_from_b64der roundtrip
# ---------------------------------------------------------------------------

def test_public_key_b64der_roundtrip():
    """Encode → decode roundtrip preserves key."""
    _, pub = generate_keypair()
    b64 = public_key_to_b64der(pub)
    restored = public_key_from_b64der(b64)
    assert public_key_to_b64der(restored) == b64


# ---------------------------------------------------------------------------
# Test: generate_and_save_keypair persistence
# ---------------------------------------------------------------------------

def test_generate_and_save_keypair_persists(tmp_path):
    """Keypair persists across calls — same key loaded each time."""
    key_path = str(tmp_path / "test_key.pem")
    priv1, pub1 = generate_and_save_keypair(key_path)
    priv2, pub2 = generate_and_save_keypair(key_path)
    assert public_key_to_b64der(pub1) == public_key_to_b64der(pub2)


# ---------------------------------------------------------------------------
# Test: /koi-net/health endpoint
# ---------------------------------------------------------------------------

async def test_koi_net_health_endpoint(
    regen_client, regen_coordinator, regen_node_rid
):
    """GET /koi-net/health returns correct node_rid, public_key, protocol."""
    resp = await regen_client.get("/koi-net/health")
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "healthy"
    assert "node" in data
    assert "peers" in data
    assert "protocol" in data
    assert "timestamp" in data

    node = data["node"]
    assert node["node_rid"] == str(regen_node_rid)
    assert node["node_name"] == "regen-test"
    assert "public_key" in node
    assert node["public_key"] is not None

    protocol = data["protocol"]
    assert protocol["require_signed_envelopes"] is True
    assert protocol["envelope_sign"] is True
    assert protocol["envelope_verify"] is True


# ---------------------------------------------------------------------------
# Test: Signed handshake + signed edge approval roundtrip
# ---------------------------------------------------------------------------

async def test_signed_handshake_with_signed_approval(
    regen_client, regen_coordinator, sign_as_blockscience,
    blockscience_node_rid, blockscience_keypair, verify_as_blockscience
):
    """Full handshake → signed edge approval roundtrip."""
    _, bs_pub = blockscience_keypair
    peer_profile = KoiNetNodeProfile(
        base_url="http://blockscience-test:8000/koi-net",
        node_type=NodeType.FULL,
        provides=NodeProvides(event=["orn:test.*"], state=["orn:test.*"]),
        public_key=bs_pub.to_der(),
    )

    handshake_body = {
        "type": "events_payload",
        "events": [
            {"rid": str(blockscience_node_rid), "event_type": "FORGET"},
            {
                "rid": str(blockscience_node_rid),
                "event_type": "NEW",
                "contents": peer_profile.model_dump(exclude_none=True),
            },
        ],
    }

    signed = sign_as_blockscience(handshake_body)
    resp = await regen_client.post("/koi-net/handshake", json=signed)
    assert resp.status_code == 200

    inner = verify_as_blockscience(resp.json())
    edge_rid = inner.get("edge_rid")
    assert edge_rid, "Handshake response should include edge_rid"

    # Send SIGNED edge approval
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


# ---------------------------------------------------------------------------
# Test: Identity migration (old 16-char → new 64-char)
# ---------------------------------------------------------------------------

def test_identity_migration(tmp_path):
    """Old .node_id is backed up during key-derived identity migration."""
    cache_dir = str(tmp_path / "cache")
    Path(cache_dir).mkdir(parents=True)

    # Create old-style .node_id
    old_rid = "orn:koi-net.node:test+abcdef1234567890"
    id_file = Path(cache_dir) / ".node_id"
    id_file.write_text(old_rid)

    # Create node — should generate key and migrate
    with patch.dict("os.environ", {}, clear=False):
        # Remove KOI_NODE_ID to avoid override
        env = dict(os.environ)
        env.pop("KOI_NODE_ID", None)
        with patch.dict("os.environ", env, clear=True):
            from koi_protocol.nodes.koi_node import KOIFullNode
            node = KOIFullNode("test", port=9999, cache_dir=cache_dir)

    # New RID should be 64-char
    suffix = node.node_id.split("+")[1]
    assert len(suffix) == 64

    # Old RID should be backed up
    legacy_file = Path(cache_dir) / ".node_id.legacy"
    assert legacy_file.exists()
    assert legacy_file.read_text().strip() == old_rid

    # Private key should exist
    assert node.private_key is not None
    assert node.public_key is not None


# Need os for test_identity_migration
import os
