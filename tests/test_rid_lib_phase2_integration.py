"""
Phase 2 Integration Tests

Verifies:
1. Sensors creating RIDs produce correct formats via shared/rid_types/
2. NodeProvides contains all sensor RID type namespaces
3. Bundle system works with rid-lib types (no fallback paths)
4. Persistent cache works with rid-lib types
5. Full regression across P0 → P2
"""

import hashlib
import pytest
import tempfile
import os
from pathlib import Path


class TestSensorRidCreation:
    """Verify sensors create RIDs that match expected formats."""

    def test_twitter_sensor_rid(self):
        from shared.rid_types.social_media import TwitterTweet
        rid = TwitterTweet("user123", "tweet456")
        assert str(rid) == "orn:twitter.tweet:user123/tweet456"
        assert rid.namespace == "twitter.tweet"

    def test_discourse_sensor_rid(self):
        from shared.rid_types.web_content import DiscoursePost
        rid = DiscoursePost("forum.regen.network", "42", "1")
        assert str(rid) == "orn:discourse.post:forum.regen.network/42/1"
        assert rid.namespace == "discourse.post"

    def test_website_sensor_rid(self):
        from shared.rid_types.web_content import WebPage
        url = "https://regen.network/about"
        rid = WebPage("regen.network", url)
        expected_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        assert str(rid) == f"orn:web.page:regen.network/{expected_hash}"
        assert rid.namespace == "web.page"

    def test_notion_sensor_rid(self):
        from shared.rid_types.productivity import NotionPage
        rid = NotionPage("regen", "page-id-123")
        assert str(rid) == "orn:notion.page:regen/page-id-123"
        assert rid.namespace == "notion.page"

    def test_github_sensor_rid(self):
        from shared.rid_types.dev_tools import GitHubFile
        rid = GitHubFile("regen-network", "regen-ledger", "main", "x/ecocredit/module.go")
        expected_hash = hashlib.sha256("x/ecocredit/module.go".encode()).hexdigest()[:16]
        assert str(rid) == f"orn:github.file:regen-network/regen-ledger/main/{expected_hash}"
        assert rid.namespace == "github.file"

    def test_youtube_sensor_rid(self):
        from shared.rid_types.social_media import YouTubeVideo
        rid = YouTubeVideo("UCchannel", "dQw4w9WgXcQ")
        assert str(rid) == "orn:youtube.video:UCchannel/dQw4w9WgXcQ"
        assert rid.namespace == "youtube.video"

    def test_gmail_sensor_rid(self):
        from shared.rid_types.communication import GmailMessage
        rid = GmailMessage("<abc123@mail.gmail.com>")
        expected_hash = hashlib.sha256("<abc123@mail.gmail.com>".encode()).hexdigest()[:16]
        assert str(rid) == f"orn:gmail.message:{expected_hash}"
        assert rid.namespace == "gmail.message"


class TestNodeProvidesPopulated:
    """Verify NodeProvides contains all sensor RID type namespaces."""

    def test_full_node_provides_event_types(self):
        from koi_protocol.nodes.koi_node import KOIFullNode
        node = KOIFullNode("test-node", port=9999)
        profile = node.to_koi_net_profile()

        expected_event_types = [
            "orn:twitter.tweet",
            "orn:discourse.post",
            "orn:web.page",
            "orn:notion.page",
            "orn:github.file",
            "orn:youtube.video",
            "orn:gmail.message",
            "orn:gmail.attachment",
        ]

        for event_type in expected_event_types:
            assert event_type in profile.provides.event, \
                f"Missing event type: {event_type}"

    def test_full_node_provides_state_types(self):
        from koi_protocol.nodes.koi_node import KOIFullNode
        node = KOIFullNode("test-node", port=9999)
        profile = node.to_koi_net_profile()

        assert "orn:koi-net.node" in profile.provides.state
        assert "orn:koi-net.edge" in profile.provides.state

    def test_partial_node_also_has_provides(self):
        from koi_protocol.nodes.koi_node import KOIPartialNode
        from koi_protocol.protocol.node import NodeType
        node = KOIPartialNode("test-sensor", "http://localhost:8005")
        profile = node.to_koi_net_profile()

        assert len(profile.provides.event) > 0
        assert profile.node_type == NodeType.PARTIAL


class TestBundleSystemNoFallback:
    """Verify bundle system uses rid-lib unconditionally."""

    def test_jcs_hash_computed_for_dict(self):
        from koi_protocol.core.bundle_system import _ridlib_hash_content
        content = {"z_key": "value", "a_key": "other"}
        h = _ridlib_hash_content(content)
        assert len(h) == 64  # SHA256 hex

    def test_jcs_hash_deterministic(self):
        from koi_protocol.core.bundle_system import _ridlib_hash_content
        content = {"b": 2, "a": 1}
        h1 = _ridlib_hash_content(content)
        h2 = _ridlib_hash_content(content)
        assert h1 == h2

    def test_bundle_generate_uses_jcs(self):
        from koi_protocol.core.bundle_system import Bundle
        from koi_protocol.core.rid_system import GenericRID
        rid = GenericRID("orn:test.type", "test-ref")
        bundle = Bundle.generate(rid, {"key": "value"})
        assert bundle.manifest.sha256_hash
        assert len(bundle.manifest.sha256_hash) == 64

    def test_no_rid_lib_available_in_bundle_system(self):
        import koi_protocol.core.bundle_system as mod
        assert not hasattr(mod, 'RID_LIB_AVAILABLE')


class TestPersistentCacheNoFallback:
    """Verify persistent cache uses rid-lib unconditionally."""

    def test_cache_available_flag_is_true(self):
        from koi_protocol.core.persistent_cache import RID_LIB_CACHE_AVAILABLE
        assert RID_LIB_CACHE_AVAILABLE is True

    def test_cache_creates_without_guard(self):
        from koi_protocol.core.persistent_cache import PersistentBundleCache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)
            assert cache.size() == 0

    def test_cache_write_read_roundtrip(self):
        from koi_protocol.core.persistent_cache import PersistentBundleCache
        from koi_protocol.core.bundle_system import Bundle
        from koi_protocol.core.rid_system import GenericRID

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)
            rid = GenericRID("orn:test.cache", "roundtrip")
            bundle = Bundle.generate(rid, {"test": "data"})
            cache.write(bundle)

            loaded = cache.read(bundle.rid)
            assert loaded is not None
            assert loaded.contents == {"test": "data"}
            assert loaded.manifest.sha256_hash == bundle.manifest.sha256_hash


class TestCoordinatorNoFallback:
    """Verify coordinator uses rid-lib unconditionally."""

    def test_no_rid_lib_available_in_coordinator(self):
        import koi_protocol.coordinator.koi_coordinator as mod
        assert not hasattr(mod, 'RID_LIB_AVAILABLE')

    def test_ridlib_manifest_imported(self):
        from koi_protocol.coordinator.koi_coordinator import RidLibManifest
        assert RidLibManifest is not None


class TestDocumentToRidWithSharedTypes:
    """Verify document_to_rid creates shared/rid_types instances."""

    def test_twitter_returns_shared_type(self):
        from koi_protocol.core.rid_system import document_to_rid
        from shared.rid_types.social_media import TwitterTweet
        doc = {"source_type": "twitter", "metadata": {"author_id": "u1", "tweet_id": "t1"}}
        rid = document_to_rid(doc)
        assert isinstance(rid, TwitterTweet)

    def test_youtube_returns_shared_type(self):
        from koi_protocol.core.rid_system import document_to_rid
        from shared.rid_types.social_media import YouTubeVideo
        doc = {"source_type": "youtube", "metadata": {"channel_id": "ch1", "video_id": "v1"}}
        rid = document_to_rid(doc)
        assert isinstance(rid, YouTubeVideo)

    def test_notion_returns_shared_type(self):
        from koi_protocol.core.rid_system import document_to_rid
        from shared.rid_types.productivity import NotionPage
        doc = {"source_type": "notion", "metadata": {"page_id": "p1"}}
        rid = document_to_rid(doc)
        assert isinstance(rid, NotionPage)

    def test_web_returns_shared_type(self):
        from koi_protocol.core.rid_system import document_to_rid
        from shared.rid_types.web_content import WebPage
        doc = {"source_type": "web", "url": "https://regen.network"}
        rid = document_to_rid(doc)
        assert isinstance(rid, WebPage)

    def test_github_returns_shared_type(self):
        from koi_protocol.core.rid_system import document_to_rid
        from shared.rid_types.dev_tools import GitHubFile
        doc = {
            "source_type": "github",
            "source": "github:regen/ledger",
            "metadata": {"file_path": "README.md", "branch": "main"},
        }
        rid = document_to_rid(doc)
        assert isinstance(rid, GitHubFile)
