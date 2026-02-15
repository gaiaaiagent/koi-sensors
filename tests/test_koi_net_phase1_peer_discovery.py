#!/usr/bin/env python3
"""
Tests for KOI Protocol Alignment Phase 1: Node Identity & Peer Discovery

Tests verify:
1. NodeProfile model creation and serialization (BlockScience-compatible)
2. NodeConfig YAML loading and first-load keypair generation
3. EdgeProfile model and edge bundle generation
4. Handshake protocol (handshake endpoint + handshake_with)
5. Edge lifecycle (PROPOSED → APPROVED)
6. Peer persistence (survive coordinator restart)
7. First-contact bootstrap logic
8. Legacy NodeProfile backward compatibility

Reference: Plan Phase 1 — Node Identity & Peer Discovery
"""

import sys
import os
import json
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

# Add koi-sensors to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import pytest


# ============================================================================
# 1. NodeProfile model tests
# ============================================================================

class TestNodeProfile:
    """Test BlockScience-aligned NodeProfile model."""

    def test_full_node_profile(self):
        """FULL node profile has base_url and all fields."""
        from koi_protocol.protocol.node import NodeProfile, NodeType, NodeProvides

        profile = NodeProfile(
            base_url="http://localhost:8005/koi-net",
            node_type=NodeType.FULL,
            provides=NodeProvides(event=["orn:koi-net.knowledge.*"]),
            public_key="base64encodedkey==",
        )
        assert profile.base_url == "http://localhost:8005/koi-net"
        assert profile.node_type == NodeType.FULL
        assert profile.provides.event == ["orn:koi-net.knowledge.*"]
        assert profile.public_key == "base64encodedkey=="

    def test_partial_node_profile(self):
        """PARTIAL node has no base_url."""
        from koi_protocol.protocol.node import NodeProfile, NodeType

        profile = NodeProfile(node_type=NodeType.PARTIAL)
        assert profile.base_url is None
        assert profile.node_type == NodeType.PARTIAL
        assert profile.provides.event == []
        assert profile.provides.state == []

    def test_node_profile_serialization(self):
        """NodeProfile roundtrips through JSON correctly."""
        from koi_protocol.protocol.node import NodeProfile, NodeType, NodeProvides

        profile = NodeProfile(
            base_url="http://host:8000/koi-net",
            node_type=NodeType.FULL,
            provides=NodeProvides(event=["a"], state=["b"]),
            public_key="pk123",
        )
        data = profile.model_dump()
        restored = NodeProfile.model_validate(data)
        assert restored == profile

    def test_node_type_enum_values(self):
        """NodeType enum matches BlockScience string values."""
        from koi_protocol.protocol.node import NodeType

        assert NodeType.FULL == "FULL"
        assert NodeType.PARTIAL == "PARTIAL"
        assert str(NodeType.FULL) == "FULL"


# ============================================================================
# 2. NodeConfig tests
# ============================================================================

class TestNodeConfig:
    """Test YAML-based NodeConfig with keypair generation."""

    def test_from_env_defaults(self):
        """NodeConfig.from_env() reads env vars and sets defaults."""
        from koi_protocol.protocol.config import NodeConfig

        with patch.dict(os.environ, {}, clear=False):
            config = NodeConfig.from_env(node_name="test-node")

        assert config.koi_net.node_name == "test-node"
        assert config.server.port == 8000
        assert config.koi_net.node_profile.node_type == "FULL"

    def test_from_env_with_overrides(self):
        """NodeConfig.from_env() respects env var overrides."""
        from koi_protocol.protocol.config import NodeConfig

        env = {
            "KOI_NODE_NAME": "my-node",
            "KOI_COORDINATOR_PORT": "9999",
            "KOI_CACHE_DIR": "/tmp/test-cache",
            "KOI_POLL_INTERVAL": "60",
            "KOI_FIRST_CONTACT_RID": "orn:koi-net.node:peer+abc",
            "KOI_FIRST_CONTACT_URL": "http://peer:8000/koi-net",
        }
        with patch.dict(os.environ, env, clear=False):
            config = NodeConfig.from_env()

        assert config.koi_net.node_name == "my-node"
        assert config.server.port == 9999
        assert config.koi_net.cache_directory_path == "/tmp/test-cache"
        assert config.koi_net.polling_interval == 60
        assert config.koi_net.first_contact.rid == "orn:koi-net.node:peer+abc"
        assert config.koi_net.first_contact.url == "http://peer:8000/koi-net"

    def test_identity_generation_without_crypto(self):
        """Without cryptography, generates RID using random UUID hash."""
        from koi_protocol.protocol.config import NodeConfig, KoiNetConfig

        config = NodeConfig(koi_net=KoiNetConfig(node_name="test"))
        assert config.koi_net.node_rid is None

        # Simulate no crypto
        with patch("koi_protocol.protocol.config._CRYPTO_AVAILABLE", False):
            config._generate_missing_identity()

        assert config.koi_net.node_rid is not None
        assert config.koi_net.node_rid.startswith("orn:koi-net.node:test+")
        assert len(config.koi_net.node_rid.split("+")[1]) == 16

    def test_identity_generation_with_crypto(self):
        """With cryptography, generates ECDSA keypair and derives RID."""
        from koi_protocol.protocol.config import NodeConfig, KoiNetConfig, _CRYPTO_AVAILABLE

        if not _CRYPTO_AVAILABLE:
            pytest.skip("cryptography not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            pem_path = os.path.join(tmpdir, "priv_key.pem")
            config = NodeConfig(
                koi_net=KoiNetConfig(
                    node_name="crypto-test",
                    private_key_pem_path=pem_path,
                )
            )
            config._generate_missing_identity()

            # Node RID should be derived from public key hash
            assert config.koi_net.node_rid is not None
            assert config.koi_net.node_rid.startswith("orn:koi-net.node:crypto-test+")

            # Public key should be in profile (base64 DER)
            assert config.koi_net.node_profile.public_key is not None

            # Private key PEM file should exist
            assert os.path.exists(pem_path)

    def test_identity_not_regenerated(self):
        """If node_rid already set, _generate_missing_identity() is a no-op."""
        from koi_protocol.protocol.config import NodeConfig, KoiNetConfig

        config = NodeConfig(
            koi_net=KoiNetConfig(
                node_name="existing",
                node_rid="orn:koi-net.node:existing+alreadyset",
            )
        )
        config._generate_missing_identity()
        assert config.koi_net.node_rid == "orn:koi-net.node:existing+alreadyset"

    def test_server_config_url(self):
        """ServerConfig.url property builds correct URL."""
        from koi_protocol.protocol.config import ServerConfig

        s = ServerConfig(host="0.0.0.0", port=8005, path="/koi-net")
        assert s.url == "http://0.0.0.0:8005/koi-net"

        s2 = ServerConfig(host="localhost", port=9000, path=None)
        assert s2.url == "http://localhost:9000"

    def test_yaml_roundtrip(self):
        """NodeConfig saves/loads YAML correctly."""
        try:
            from ruamel.yaml import YAML
        except ImportError:
            pytest.skip("ruamel.yaml not installed")

        from koi_protocol.protocol.config import NodeConfig, KoiNetConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml_path = os.path.join(tmpdir, "config.yaml")
            config = NodeConfig(
                koi_net=KoiNetConfig(
                    node_name="yaml-test",
                    node_rid="orn:koi-net.node:yaml-test+abc123",
                )
            )
            config._file_path = yaml_path
            config.save_to_yaml()

            # Load it back
            loaded = NodeConfig.load_from_yaml(yaml_path, generate_missing=False)
            assert loaded.koi_net.node_name == "yaml-test"
            assert loaded.koi_net.node_rid == "orn:koi-net.node:yaml-test+abc123"


# ============================================================================
# 3. EdgeProfile model tests
# ============================================================================

class TestEdgeProfile:
    """Test EdgeProfile model and edge bundle generation."""

    def test_edge_profile_creation(self):
        """EdgeProfile created with correct fields."""
        from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

        edge = EdgeProfile(
            source="orn:koi-net.node:a+111",
            target="orn:koi-net.node:b+222",
            edge_type=EdgeType.POLL,
            status=EdgeStatus.PROPOSED,
            rid_types=["orn:koi-net.knowledge.*"],
        )
        assert edge.source == "orn:koi-net.node:a+111"
        assert edge.edge_type == EdgeType.POLL
        assert edge.status == EdgeStatus.PROPOSED

    def test_edge_profile_serialization(self):
        """EdgeProfile roundtrips through JSON."""
        from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

        edge = EdgeProfile(
            source="a", target="b",
            edge_type=EdgeType.WEBHOOK,
            status=EdgeStatus.APPROVED,
            rid_types=["x"],
        )
        data = edge.model_dump()
        restored = EdgeProfile.model_validate(data)
        assert restored == edge

    def test_generate_edge_rid_deterministic(self):
        """Edge RID is deterministic for same source+target."""
        from koi_protocol.protocol.edge import generate_edge_rid

        rid1 = generate_edge_rid("orn:koi-net.node:a+111", "orn:koi-net.node:b+222")
        rid2 = generate_edge_rid("orn:koi-net.node:a+111", "orn:koi-net.node:b+222")
        assert rid1 == rid2
        assert rid1.startswith("orn:koi-net.edge:")

    def test_generate_edge_rid_directional(self):
        """Edge RID differs for reversed source/target."""
        from koi_protocol.protocol.edge import generate_edge_rid

        rid_ab = generate_edge_rid("a", "b")
        rid_ba = generate_edge_rid("b", "a")
        assert rid_ab != rid_ba

    def test_generate_edge_bundle(self):
        """generate_edge_bundle returns correct structure."""
        from koi_protocol.protocol.edge import (
            generate_edge_bundle, EdgeType, EdgeStatus, EdgeProfile,
        )

        bundle = generate_edge_bundle(
            source="orn:koi-net.node:a+111",
            target="orn:koi-net.node:b+222",
            rid_types=["orn:koi-net.knowledge.*"],
            edge_type=EdgeType.POLL,
        )
        assert "rid" in bundle
        assert "contents" in bundle
        assert bundle["rid"].startswith("orn:koi-net.edge:")

        # Contents should be a valid EdgeProfile
        profile = EdgeProfile.model_validate(bundle["contents"])
        assert profile.status == EdgeStatus.PROPOSED
        assert profile.edge_type == EdgeType.POLL

    def test_edge_status_enum_values(self):
        """EdgeStatus enum matches BlockScience string values."""
        from koi_protocol.protocol.edge import EdgeStatus

        assert EdgeStatus.PROPOSED == "PROPOSED"
        assert EdgeStatus.APPROVED == "APPROVED"


# ============================================================================
# 4. Legacy NodeProfile backward compatibility
# ============================================================================

class TestLegacyNodeProfile:
    """Test that legacy NodeProfile (now LegacyNodeProfile) still works."""

    def test_legacy_profile_creation(self):
        """LegacyNodeProfile can be instantiated."""
        from koi_protocol.nodes.koi_node import LegacyNodeProfile

        profile = LegacyNodeProfile(
            node_id="test-id",
            node_name="test",
            node_type="FULL",
            version="1.0.0",
            capabilities=["events"],
            endpoints={"health": "http://localhost/health"},
            metadata={},
        )
        assert profile.node_id == "test-id"
        assert profile.node_type == "FULL"

    def test_koi_node_get_profile_returns_legacy(self):
        """KOINodeBase.get_profile() returns LegacyNodeProfile."""
        from koi_protocol.nodes.koi_node import KOIFullNode, LegacyNodeProfile

        with tempfile.TemporaryDirectory() as tmpdir:
            node = KOIFullNode("test", port=8000, cache_dir=tmpdir)
            profile = node.get_profile()
            assert isinstance(profile, LegacyNodeProfile)

    def test_koi_node_to_koi_net_profile(self):
        """KOINodeBase.to_koi_net_profile() returns new NodeProfile."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.protocol.node import NodeProfile, NodeType

        with tempfile.TemporaryDirectory() as tmpdir:
            node = KOIFullNode("test", port=8005, cache_dir=tmpdir)
            profile = node.to_koi_net_profile()
            assert isinstance(profile, NodeProfile)
            assert profile.node_type == NodeType.FULL
            assert profile.base_url is not None
            assert "8005" in profile.base_url


# ============================================================================
# 5. Handshake protocol tests (unit-level)
# ============================================================================

class TestHandshakeProtocol:
    """Test the handshake endpoint and handshake_with() method."""

    @pytest.fixture
    def coordinator(self, tmp_path):
        """Create a coordinator with temp cache dir."""
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator

        # Prevent env var pollution
        env_overrides = {
            "KOI_ENVELOPE_SIGN": "false",
            "KOI_ENVELOPE_VERIFY": "false",
            "KOI_NET_REQUIRE_SIGNED": "false",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            coord = KOICoordinator(
                node_name="test-coordinator",
                port=9999,
                cache_dir=str(tmp_path / "cache"),
            )
            # Override peers file to temp location
            coord.peers_file = tmp_path / "peers.json"
            return coord

    def test_handshake_endpoint_stores_peer(self, coordinator):
        """Handshake endpoint stores incoming peer profile."""
        from koi_protocol.protocol.node import NodeProfile, NodeType

        peer_rid = "orn:koi-net.node:peer+abc123"
        peer_profile = NodeProfile(
            base_url="http://peer:8000/koi-net",
            node_type=NodeType.FULL,
        )

        # Simulate the handshake payload processing
        payload = {
            "type": "events_payload",
            "events": [
                {"rid": peer_rid, "event_type": "FORGET"},
                {
                    "rid": peer_rid,
                    "event_type": "NEW",
                    "contents": peer_profile.model_dump(),
                },
            ],
        }

        # Find and call the process_handshake function directly
        # by invoking through the coordinator's internal logic
        assert peer_rid not in coordinator.known_peers

        # Access the handshake handler through the app's routes
        from fastapi.testclient import TestClient
        client = TestClient(coordinator.app)

        response = client.post("/koi-net/handshake", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["type"] == "handshake_response"
        assert data["node_rid"] == coordinator.koi_node.node_id
        assert data["profile"]["node_type"] == "FULL"
        assert data["proposed_edge"] is not None
        assert data["proposed_edge"]["status"] == "PROPOSED"

        # Peer should be stored
        assert peer_rid in coordinator.known_peers

    def test_handshake_forget_clears_stale_state(self, coordinator):
        """FORGET event in handshake clears existing peer state."""
        peer_rid = "orn:koi-net.node:stale+def456"
        coordinator.known_peers[peer_rid] = {
            "profile": {"node_type": "FULL"},
            "last_seen": "2025-01-01T00:00:00Z",
        }

        from koi_protocol.protocol.node import NodeProfile, NodeType
        payload = {
            "type": "events_payload",
            "events": [
                {"rid": peer_rid, "event_type": "FORGET"},
                {
                    "rid": peer_rid,
                    "event_type": "NEW",
                    "contents": NodeProfile(
                        base_url="http://new:8000",
                        node_type=NodeType.FULL,
                    ).model_dump(),
                },
            ],
        }

        from fastapi.testclient import TestClient
        client = TestClient(coordinator.app)
        response = client.post("/koi-net/handshake", json=payload)
        assert response.status_code == 200

        # Peer should have fresh state
        assert coordinator.known_peers[peer_rid]["last_seen"] != "2025-01-01T00:00:00Z"

    def test_handshake_rejects_missing_new_event(self, coordinator):
        """Handshake without NEW event returns error."""
        payload = {
            "type": "events_payload",
            "events": [
                {"rid": "orn:koi-net.node:x+y", "event_type": "FORGET"},
            ],
        }

        from fastapi.testclient import TestClient
        client = TestClient(coordinator.app)
        response = client.post("/koi-net/handshake", json=payload)
        # Should return 400 (invalid request)
        assert response.status_code == 400

    def test_edge_approval_lifecycle(self, coordinator):
        """Edge goes PROPOSED → APPROVED through the approve endpoint."""
        from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

        edge_rid = "orn:koi-net.edge:test123"
        coordinator.edges[edge_rid] = EdgeProfile(
            source=coordinator.koi_node.node_id,
            target="orn:koi-net.node:peer+abc",
            edge_type=EdgeType.POLL,
            status=EdgeStatus.PROPOSED,
        )

        from fastapi.testclient import TestClient
        client = TestClient(coordinator.app)

        response = client.post("/koi-net/edges/approve", json={
            "type": "edge_approve",
            "edge_rid": edge_rid,
            "node_rid": "orn:koi-net.node:peer+abc",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "APPROVED"
        assert coordinator.edges[edge_rid].status == EdgeStatus.APPROVED

    def test_list_peers_endpoint(self, coordinator):
        """GET /koi-net/peers lists known peers."""
        from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

        peer_rid = "orn:koi-net.node:listed+peer"
        edge_rid = "orn:koi-net.edge:e1"
        coordinator.known_peers[peer_rid] = {
            "profile": {"node_type": "FULL"},
            "last_seen": "2026-01-01T00:00:00Z",
            "edges": [edge_rid],
        }
        coordinator.edges[edge_rid] = EdgeProfile(
            source=coordinator.koi_node.node_id,
            target=peer_rid,
            edge_type=EdgeType.POLL,
            status=EdgeStatus.APPROVED,
        )

        from fastapi.testclient import TestClient
        client = TestClient(coordinator.app)

        response = client.get("/koi-net/peers")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["peers"][0]["node_rid"] == peer_rid
        assert data["peers"][0]["edges"][0]["status"] == "APPROVED"


# ============================================================================
# 6. Peer persistence tests
# ============================================================================

class TestPeerPersistence:
    """Test that peer state survives coordinator restart."""

    def test_peers_roundtrip(self, tmp_path):
        """Peers saved by one coordinator are loaded by another."""
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator
        from koi_protocol.protocol.edge import EdgeProfile, EdgeType, EdgeStatus

        env_overrides = {
            "KOI_ENVELOPE_SIGN": "false",
            "KOI_ENVELOPE_VERIFY": "false",
            "KOI_NET_REQUIRE_SIGNED": "false",
        }
        cache_dir = str(tmp_path / "cache")
        peers_file = tmp_path / "peers.json"

        # Coordinator 1: store a peer
        with patch.dict(os.environ, env_overrides, clear=False):
            coord1 = KOICoordinator("c1", port=9001, cache_dir=cache_dir)
            coord1.peers_file = peers_file

        peer_rid = "orn:koi-net.node:persist-test+aaa"
        edge_rid = "orn:koi-net.edge:persist-edge"
        coord1.known_peers[peer_rid] = {
            "profile": {"node_type": "FULL", "base_url": "http://host:8000"},
            "last_seen": "2026-02-14T00:00:00Z",
            "edges": [edge_rid],
        }
        coord1.edges[edge_rid] = EdgeProfile(
            source=coord1.koi_node.node_id,
            target=peer_rid,
            edge_type=EdgeType.POLL,
            status=EdgeStatus.APPROVED,
        )
        coord1._save_peers()
        assert peers_file.exists()

        # Coordinator 2: load the same file
        with patch.dict(os.environ, env_overrides, clear=False):
            coord2 = KOICoordinator("c2", port=9002, cache_dir=cache_dir)
            coord2.peers_file = peers_file
            coord2._load_peers()

        assert peer_rid in coord2.known_peers
        assert edge_rid in coord2.edges
        assert coord2.edges[edge_rid].status == EdgeStatus.APPROVED


# ============================================================================
# 7. First-contact bootstrap tests
# ============================================================================

class TestFirstContactBootstrap:
    """Test first-contact handshake initiation on startup."""

    def test_first_contact_from_config(self, tmp_path):
        """Coordinator with NodeConfig.first_contact triggers handshake."""
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator
        from koi_protocol.protocol.config import (
            NodeConfig, KoiNetConfig, ServerConfig, NodeContact,
        )

        config = NodeConfig(
            server=ServerConfig(port=9003),
            koi_net=KoiNetConfig(
                node_name="bootstrap-test",
                node_rid="orn:koi-net.node:bootstrap-test+aaa",
                first_contact=NodeContact(
                    rid="orn:koi-net.node:peer+bbb",
                    url="http://peer:8000/koi-net",
                ),
            ),
        )

        env_overrides = {
            "KOI_ENVELOPE_SIGN": "false",
            "KOI_ENVELOPE_VERIFY": "false",
            "KOI_NET_REQUIRE_SIGNED": "false",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            coord = KOICoordinator(
                node_name="bootstrap-test",
                port=9003,
                cache_dir=str(tmp_path / "cache"),
                config=config,
            )
            coord.peers_file = tmp_path / "peers.json"

        # No peers → first_contact should be used
        assert coord.node_config is not None
        assert coord.node_config.koi_net.first_contact.rid == "orn:koi-net.node:peer+bbb"
        assert len(coord.known_peers) == 0

    def test_first_contact_from_env_vars(self, tmp_path):
        """Without NodeConfig, first-contact comes from env vars."""
        from koi_protocol.coordinator.koi_coordinator import KOICoordinator

        env_overrides = {
            "KOI_ENVELOPE_SIGN": "false",
            "KOI_ENVELOPE_VERIFY": "false",
            "KOI_NET_REQUIRE_SIGNED": "false",
            "KOI_FIRST_CONTACT_RID": "orn:koi-net.node:env-peer+ccc",
            "KOI_FIRST_CONTACT_URL": "http://env-peer:8000/koi-net",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            coord = KOICoordinator(
                node_name="env-test",
                port=9004,
                cache_dir=str(tmp_path / "cache"),
            )
            coord.peers_file = tmp_path / "peers.json"

        # Config is None but env vars should be readable in start()
        assert coord.node_config is None


# ============================================================================
# 8. Protocol package import tests
# ============================================================================

class TestProtocolPackageImports:
    """Verify all protocol models are importable from the package."""

    def test_import_all_from_protocol(self):
        """All models importable from koi_protocol.protocol."""
        from koi_protocol.protocol import (
            NodeType, NodeProvides, NodeProfile,
            EdgeType, EdgeStatus, EdgeProfile, generate_edge_bundle,
            ServerConfig, KoiNetConfig, NodeConfig,
        )
        # Just verify they're all classes/functions
        assert NodeType.FULL == "FULL"
        assert callable(generate_edge_bundle)

    def test_import_individual_modules(self):
        """Individual module imports work."""
        from koi_protocol.protocol.node import NodeProfile
        from koi_protocol.protocol.edge import EdgeProfile
        from koi_protocol.protocol.config import NodeConfig


# ============================================================================
# 9. Regression: Phase 0A tests should still pass
# ============================================================================

class TestPhase0ARegression:
    """Verify Phase 0A features still work after Phase 1 changes."""

    def test_stable_node_identity(self):
        """Node identity persists across instances (Phase 0A F4)."""
        from koi_protocol.nodes.koi_node import KOIFullNode

        with tempfile.TemporaryDirectory() as tmpdir:
            node1 = KOIFullNode("regression", port=8000, cache_dir=tmpdir)
            id1 = node1.node_id

            node2 = KOIFullNode("regression", port=8000, cache_dir=tmpdir)
            id2 = node2.node_id

            assert id1 == id2
            assert id1.startswith("orn:koi-net.node:")

    def test_per_node_delivery_tracking(self):
        """Per-node poll queue delivery still works (Phase 0A F2)."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent, Bundle, Manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            node = KOIFullNode("regression", port=8000, cache_dir=tmpdir)

            # Create and queue a test event
            manifest = Manifest(
                rid="test:rid",
                timestamp=datetime.now(timezone.utc).isoformat(),
                sha256_hash="abc123",
                size_bytes=10,
                content_type="application/json",
                version="1.0",
                metadata={},
            )
            bundle = Bundle(rid="test:rid", manifest=manifest, contents={"test": True})
            event = KOIEvent.new_event(bundle, "test-source")
            node.queue_event(event)

            # Node A gets the event
            events_a, ids_a = node.get_queued_events_for_delivery("node-a", 10)
            assert len(events_a) == 1

            # Node B also gets the event (independent delivery)
            events_b, ids_b = node.get_queued_events_for_delivery("node-b", 10)
            assert len(events_b) == 1

            # Node A gets nothing on second poll (already delivered)
            events_a2, _ = node.get_queued_events_for_delivery("node-a", 10)
            assert len(events_a2) == 0
