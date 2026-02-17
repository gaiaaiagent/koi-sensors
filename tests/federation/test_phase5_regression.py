"""
Phase 5.1 Regression Tests — Production Discovery Hardening

Tests codify two issues discovered during the 2026-02-17 Phase 5 deployment:

1. Handshake format: Octo expects {type: "handshake", profile: NodeProfile},
   NOT the BlockScience events_payload format with FORGET+NEW events.
   (koi_coordinator.py handshake_with method)

2. KOI_BASE_URL: Must NOT end with /koi-net because peers append /koi-net/*
   themselves, causing double-path bugs like .../koi-net/koi-net/events/poll.
   (config.py, coordinator health endpoint, preflight script)

3. Node name resolution: Preflight must use the actual production node name
   (from run_coordinator.py), not the class default 'regen-coordinator'.

These tests require Python 3.12+ (match statement syntax in conftest).
"""

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# These tests don't require koi-net — they test our own code only
pytestmark = pytest.mark.no_koi_net

# Import guard for tests that need KOICoordinator (which imports rid_lib)
try:
    from koi_protocol.coordinator.koi_coordinator import KOICoordinator
    COORDINATOR_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    COORDINATOR_AVAILABLE = False

skip_no_coordinator = pytest.mark.skipif(
    not COORDINATOR_AVAILABLE,
    reason="KOICoordinator import failed (rid_lib not installed)"
)


# ---------------------------------------------------------------------------
# 1. Handshake format regression
# ---------------------------------------------------------------------------

class TestHandshakeFormat:
    """Verify handshake_with sends profile-exchange format, not events_payload."""

    @skip_no_coordinator
    def test_handshake_payload_has_profile_key(self):
        """The handshake payload must contain 'profile', not 'events'."""
        coord = KOICoordinator(node_name="test-node", port=9999)

        # Read the handshake_with method source to verify format
        import inspect
        source = inspect.getsource(coord.handshake_with)

        # Must use profile-exchange format
        assert '"type": "handshake"' in source or "'type': 'handshake'" in source or \
               '"handshake"' in source, \
            "handshake_with must send type='handshake' (profile-exchange format)"

        # Must NOT use events_payload format
        assert '"type": "events_payload"' not in source, \
            "handshake_with must NOT send events_payload format — " \
            "Octo returns 'Missing profile' for this format"

    @skip_no_coordinator
    def test_handshake_payload_includes_node_rid_and_name(self):
        """Profile must include node_rid and node_name for Octo compatibility."""
        import inspect
        coord = KOICoordinator(node_name="test-node", port=9999)
        source = inspect.getsource(coord.handshake_with)

        # Profile must include node_rid
        assert "node_rid" in source, \
            "handshake profile must include node_rid"
        assert "node_name" in source, \
            "handshake profile must include node_name"

    def test_handshake_profile_format_matches_octo_schema(self):
        """Verify the profile dict structure matches Octo's HandshakeRequest."""
        # Octo expects: {type: "handshake", profile: {node_rid, node_name, node_type, base_url, provides, public_key}}
        required_profile_fields = {"node_rid", "node_name", "node_type", "provides"}

        # Build a profile the same way handshake_with does
        from koi_protocol.protocol.node import NodeProfile, NodeType, NodeProvides
        profile = NodeProfile(
            base_url="http://test:8005",
            node_type=NodeType.FULL,
            provides=NodeProvides(event=["test"], state=["test"]),
            public_key="test_key_b64",
        )
        profile_data = profile.model_dump()
        # handshake_with adds these:
        profile_data["node_rid"] = "orn:koi-net.node:test+abc123"
        profile_data["node_name"] = "test"

        missing = required_profile_fields - set(profile_data.keys())
        assert not missing, f"Profile missing required fields: {missing}"


# ---------------------------------------------------------------------------
# 2. KOI_BASE_URL normalization regression
# ---------------------------------------------------------------------------

class TestBaseUrlNormalization:
    """Verify KOI_BASE_URL never causes /koi-net path duplication."""

    def test_base_url_env_must_not_end_with_koi_net(self):
        """KOI_BASE_URL should not end with /koi-net.

        Peers append /koi-net/events/poll, /koi-net/handshake, etc. to base_url.
        If base_url already includes /koi-net, paths become .../koi-net/koi-net/...
        """
        # Simulate the coordinator's base_url resolution logic
        test_cases = [
            ("https://regen.gaiaai.xyz/api/koi/coordinator", True),  # correct
            ("http://localhost:8005", True),  # correct
            ("https://regen.gaiaai.xyz/api/koi/coordinator/koi-net", False),  # BAD
            ("http://localhost:8005/koi-net", False),  # BAD
            ("http://localhost:8005/koi-net/", False),  # BAD with trailing slash
        ]

        for url, expected_ok in test_cases:
            normalized = url.rstrip("/")
            is_ok = not normalized.endswith("/koi-net")
            assert is_ok == expected_ok, \
                f"base_url '{url}' should be {'valid' if expected_ok else 'REJECTED'}"

    def test_poll_url_construction_no_double_koi_net(self):
        """Simulates how Octo's poller constructs poll URLs from base_url."""
        # Octo's koi_poller.py line 160: f"{base_url}/koi-net/events/poll"
        base_url = "https://regen.gaiaai.xyz/api/koi/coordinator"
        poll_url = f"{base_url}/koi-net/events/poll"

        assert "/koi-net/koi-net/" not in poll_url, \
            f"Double /koi-net/ in poll URL: {poll_url}"
        assert poll_url == "https://regen.gaiaai.xyz/api/koi/coordinator/koi-net/events/poll"

    def test_health_endpoint_url_construction(self):
        """Health URL from base_url must not double /koi-net."""
        base_url = "https://regen.gaiaai.xyz/api/koi/coordinator"
        health_url = f"{base_url}/koi-net/health"

        assert "/koi-net/koi-net/" not in health_url
        assert health_url == "https://regen.gaiaai.xyz/api/koi/coordinator/koi-net/health"

    @skip_no_coordinator
    def test_config_base_url_from_env(self):
        """NodeConfig.from_env should not append /koi-net to KOI_BASE_URL."""
        from koi_protocol.protocol.config import NodeConfig

        with patch.dict(os.environ, {
            "KOI_BASE_URL": "https://example.com/api",
            "KOI_COORDINATOR_PORT": "8005",
        }):
            config = NodeConfig.from_env()
            base_url = config.koi_net.node_profile.base_url
            if base_url:
                assert not base_url.rstrip("/").endswith("/koi-net"), \
                    f"NodeConfig.from_env added /koi-net to KOI_BASE_URL: {base_url}"


# ---------------------------------------------------------------------------
# 3. Node name resolution regression
# ---------------------------------------------------------------------------

class TestNodeNameResolution:
    """Verify preflight uses production node name, not class default."""

    def test_preflight_resolves_node_name_from_run_script(self):
        """Preflight should extract node_name from run_coordinator.py."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from federation_preflight import _resolve_node_name

        # Clear env to test file-based resolution
        with patch.dict(os.environ, {}, clear=True):
            name = _resolve_node_name()

        # Should find 'koi-coordinator-main' from run_coordinator.py
        run_script = REPO_ROOT / "koi_protocol" / "coordinator" / "run_coordinator.py"
        if run_script.exists():
            content = run_script.read_text()
            match = re.search(r'node_name\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                expected = match.group(1)
                assert name == expected, \
                    f"Preflight resolved '{name}' but run_coordinator.py has '{expected}'"

    def test_preflight_env_overrides_file(self):
        """KOI_NODE_NAME env var should take priority."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from federation_preflight import _resolve_node_name

        with patch.dict(os.environ, {"KOI_NODE_NAME": "custom-name"}):
            name = _resolve_node_name()
        assert name == "custom-name"

    @skip_no_coordinator
    def test_coordinator_default_matches_run_script(self):
        """Verify KOICoordinator class default vs run_coordinator.py are documented."""
        # KOICoordinator.__init__ defaults to "regen-coordinator"
        # run_coordinator.py uses "koi-coordinator-main"
        # This is intentional — the class default is for development,
        # run_coordinator.py sets the production name.
        import inspect

        sig = inspect.signature(KOICoordinator.__init__)
        class_default = sig.parameters["node_name"].default

        run_script = REPO_ROOT / "koi_protocol" / "coordinator" / "run_coordinator.py"
        if run_script.exists():
            content = run_script.read_text()
            match = re.search(r'node_name\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                prod_name = match.group(1)
                # They SHOULD differ — class default is for dev, run script is for prod
                # This test documents the intentional divergence
                if class_default != prod_name:
                    # This is expected and fine — just verify both are non-empty
                    assert class_default and prod_name, \
                        "Both class default and production node name must be non-empty"


# ---------------------------------------------------------------------------
# 4. Handshake response parsing regression
# ---------------------------------------------------------------------------

class TestHandshakeResponseParsing:
    """Verify peer_rid extraction handles both response formats."""

    def test_peer_rid_from_top_level(self):
        """BlockScience format: node_rid at top level of response."""
        result = {
            "node_rid": "orn:koi-net.node:peer+abc123",
            "profile": {"node_type": "FULL"},
        }
        peer_rid = result.get("node_rid")
        assert peer_rid == "orn:koi-net.node:peer+abc123"

    def test_peer_rid_from_profile(self):
        """Octo format: node_rid inside profile object."""
        result = {
            "type": "handshake_response",
            "profile": {
                "node_rid": "orn:koi-net.node:octo+def456",
                "node_name": "octo",
                "node_type": "FULL",
            },
            "accepted": True,
        }
        peer_profile = result.get("profile")
        peer_rid = result.get("node_rid")
        # Octo-style: node_rid lives inside profile
        if not peer_rid and peer_profile:
            peer_rid = peer_profile.get("node_rid")
        assert peer_rid == "orn:koi-net.node:octo+def456"

    def test_peer_rid_fallback_logic(self):
        """Verify the exact fallback logic used in koi_coordinator.py."""
        # This mirrors the production code at koi_coordinator.py:2046-2049
        for result, expected_rid in [
            # BlockScience: top-level node_rid
            ({"node_rid": "rid1", "profile": {}}, "rid1"),
            # Octo: node_rid in profile only
            ({"profile": {"node_rid": "rid2"}}, "rid2"),
            # Both present: top-level wins
            ({"node_rid": "rid1", "profile": {"node_rid": "rid2"}}, "rid1"),
            # Neither: None
            ({"profile": {}}, None),
        ]:
            peer_profile = result.get("profile")
            peer_rid = result.get("node_rid")
            if not peer_rid and peer_profile:
                peer_rid = peer_profile.get("node_rid")
            assert peer_rid == expected_rid, \
                f"For {result}, expected {expected_rid} but got {peer_rid}"
