#!/usr/bin/env python3
"""
TDD Tests for KOI Protocol Alignment Phase 0 (Foundation)

These tests verify:
1. Hash parity with rid-lib (JCS canonicalization)
2. RID parsing for ORNs with multiple colons
3. RID parsing for URIs with ports
4. Dual-hash manifest support (legacy_content_hash + sha256_hash)

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

import sys
from pathlib import Path

# Add koi-sensors to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import hashlib
import json
import pytest
from datetime import datetime, timezone


class TestHashParityWithRidLib:
    """Test that our hashing matches rid-lib for identical content."""

    def test_hash_parity_simple_dict(self):
        """Simple dict should produce identical hash to rid-lib."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value", "nested": {"a": 1}}
        rid = GenericRID("test", "content")

        # Generate manifest with our code (should use rid-lib internally)
        manifest = Manifest.generate(rid, content)

        # Generate hash directly with rid-lib
        ridlib_hash = sha256_hash_json(content)

        # The sha256_hash field should match rid-lib
        assert manifest.sha256_hash == ridlib_hash, \
            f"Hash mismatch: manifest.sha256_hash={manifest.sha256_hash}, rid-lib={ridlib_hash}"

    def test_hash_parity_numeric_normalization(self):
        """JCS normalizes 1.0 -> 1; this is the critical case from spike results."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        # This is the exact case that caused 8.79% mismatch in spike
        content = {"value": 1.0, "nested": {"float": 2.0}}
        rid = GenericRID("test", "numeric")

        manifest = Manifest.generate(rid, content)
        ridlib_hash = sha256_hash_json(content)

        assert manifest.sha256_hash == ridlib_hash, \
            "Numeric normalization (1.0 -> 1) not handled correctly"

    def test_hash_parity_unicode_content(self):
        """Unicode content should produce identical hash."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"title": "Regenerative Economics", "author": "Gregory Landua"}
        rid = GenericRID("test", "unicode")

        manifest = Manifest.generate(rid, content)
        ridlib_hash = sha256_hash_json(content)

        assert manifest.sha256_hash == ridlib_hash

    def test_hash_parity_empty_objects(self):
        """Empty objects should produce identical hash."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        for content in [{}, {"nested": {}}, {"list": []}]:
            rid = GenericRID("test", "empty")
            manifest = Manifest.generate(rid, content)
            ridlib_hash = sha256_hash_json(content)
            assert manifest.sha256_hash == ridlib_hash

    def test_hash_parity_sorted_keys(self):
        """Key ordering should match JCS (UTF-16BE sort)."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        # Keys that sort differently in ASCII vs UTF-16BE
        content = {"z": 1, "a": 2, "B": 3}
        rid = GenericRID("test", "sorted")

        manifest = Manifest.generate(rid, content)
        ridlib_hash = sha256_hash_json(content)

        assert manifest.sha256_hash == ridlib_hash


class TestRIDParsingORN:
    """Test that ORNs with multiple colons parse correctly."""

    def test_parse_slack_message_orn(self):
        """orn:slack.message:T123/C456/1234.5678 should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "orn:slack.message:T123/C456/1234.5678"
        rid = RID.parse(rid_string)

        # Should not raise an error
        assert rid is not None
        # The string representation should match
        assert rid.to_string() == rid_string

    def test_parse_twitter_tweet_orn(self):
        """orn:twitter.tweet:user_id/tweet_id should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "orn:twitter.tweet:12345/67890"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_discourse_post_orn(self):
        """orn:discourse.post:forum.regen.network/123/4 should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "orn:discourse.post:forum.regen.network/123/4"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_notion_page_orn(self):
        """orn:notion.page:workspace/page_id should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "orn:notion.page:regen/abc123def456"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_complex_orn_with_many_colons(self):
        """ORN reference can contain multiple colons (e.g., timestamps)."""
        from koi_protocol.core.rid_system import RID

        # Timestamps in references should work
        rid_string = "orn:event.timestamp:2024-12-22T10:30:45Z"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string


class TestRIDParsingURIWithPort:
    """Test that URIs with ports parse correctly."""

    def test_parse_https_with_port(self):
        """https://example.com:8080/path should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "https://example.com:8080/path"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_http_with_port(self):
        """http://localhost:3000/api/v1 should parse correctly."""
        from koi_protocol.core.rid_system import RID

        rid_string = "http://localhost:3000/api/v1"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_standard_url_no_port(self):
        """Standard URLs without ports should still work."""
        from koi_protocol.core.rid_system import RID

        rid_string = "https://github.com/BlockScience/koi-net"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string

    def test_parse_url_with_query_params(self):
        """URLs with query params containing special chars."""
        from koi_protocol.core.rid_system import RID

        rid_string = "https://api.example.com/search?q=test&limit=10"
        rid = RID.parse(rid_string)

        assert rid is not None
        assert rid.to_string() == rid_string


class TestDualHashManifest:
    """Test that manifests include both legacy_content_hash and sha256_hash."""

    def test_manifest_has_both_hashes(self):
        """Manifest should have both legacy_content_hash and sha256_hash."""
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value"}
        rid = GenericRID("test", "dual-hash")

        manifest = Manifest.generate(rid, content)

        # Both fields should exist
        assert hasattr(manifest, 'sha256_hash'), "Missing sha256_hash field"
        assert hasattr(manifest, 'legacy_content_hash'), "Missing legacy_content_hash field"

        # Both should be valid hex strings
        assert len(manifest.sha256_hash) == 64
        assert len(manifest.legacy_content_hash) == 64

    def test_legacy_hash_matches_old_behavior(self):
        """legacy_content_hash should match json.dumps(sort_keys=True) hashing."""
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value", "nested": {"a": 1}}
        rid = GenericRID("test", "legacy")

        # Compute old-style hash
        content_bytes = json.dumps(content, sort_keys=True).encode('utf-8')
        expected_legacy_hash = hashlib.sha256(content_bytes).hexdigest()

        manifest = Manifest.generate(rid, content)

        assert manifest.legacy_content_hash == expected_legacy_hash, \
            "legacy_content_hash should match old json.dumps(sort_keys=True) behavior"

    def test_sha256_hash_matches_ridlib(self):
        """sha256_hash should match rid-lib JCS hashing."""
        from rid_lib.ext.utils import sha256_hash_json
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value", "nested": {"a": 1}}
        rid = GenericRID("test", "ridlib")

        manifest = Manifest.generate(rid, content)
        ridlib_hash = sha256_hash_json(content)

        assert manifest.sha256_hash == ridlib_hash

    def test_hashes_differ_for_numeric_content(self):
        """For content with floats, legacy and sha256 hashes should differ (1.0 vs 1)."""
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"value": 1.0}  # JCS normalizes to 1
        rid = GenericRID("test", "numeric-diff")

        manifest = Manifest.generate(rid, content)

        # These should be DIFFERENT due to JCS numeric normalization
        assert manifest.sha256_hash != manifest.legacy_content_hash, \
            "Hashes should differ for content with float values"

    def test_to_dict_includes_both_hashes(self):
        """to_dict() should include both hash fields."""
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value"}
        rid = GenericRID("test", "dict")

        manifest = Manifest.generate(rid, content)
        manifest_dict = manifest.to_dict()

        assert 'sha256_hash' in manifest_dict
        assert 'legacy_content_hash' in manifest_dict

    def test_content_hash_alias_returns_sha256(self):
        """content_hash property should return sha256_hash for new code paths."""
        from koi_protocol.core.bundle_system import Manifest
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value"}
        rid = GenericRID("test", "alias")

        manifest = Manifest.generate(rid, content)

        # content_hash should be an alias for sha256_hash (backward compat)
        assert manifest.content_hash == manifest.sha256_hash


class TestBundleIntegrity:
    """Test bundle integrity verification with dual hashes."""

    def test_bundle_verify_integrity_uses_sha256(self):
        """Bundle.verify_integrity() should use sha256_hash (rid-lib)."""
        from koi_protocol.core.bundle_system import Bundle
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value"}
        rid = GenericRID("test", "integrity")

        bundle = Bundle.generate(rid, content)

        # Should verify using sha256_hash
        assert bundle.verify_integrity() is True

    def test_bundle_verify_legacy_integrity(self):
        """Bundle should provide method to verify against legacy hash."""
        from koi_protocol.core.bundle_system import Bundle
        from koi_protocol.core.rid_system import GenericRID

        content = {"key": "value"}
        rid = GenericRID("test", "legacy-verify")

        bundle = Bundle.generate(rid, content)

        # Should have method to verify against legacy hash
        assert bundle.verify_legacy_integrity() is True


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_manifest_from_dict_with_legacy_hash_only(self):
        """Manifests with only content_hash (legacy) should still work."""
        from koi_protocol.core.bundle_system import Manifest

        # Old-style manifest dict with only content_hash
        legacy_dict = {
            "rid": "test:legacy",
            "timestamp": "2024-12-22T10:00:00Z",
            "content_hash": "abc123" * 11,  # 66 chars, truncated for test
            "size_bytes": 100,
            "content_type": "application/json",
            "version": "1.0",
            "metadata": {}
        }

        manifest = Manifest.from_dict(legacy_dict)

        # Should work without sha256_hash
        assert manifest.content_hash == legacy_dict["content_hash"]

    def test_existing_bundle_format_still_works(self):
        """Existing bundle format with content_hash should still be parseable."""
        from koi_protocol.core.bundle_system import Bundle

        # Old-style bundle dict
        legacy_bundle = {
            "rid": "test:legacy-bundle",
            "manifest": {
                "rid": "test:legacy-bundle",
                "timestamp": "2024-12-22T10:00:00Z",
                "content_hash": "abc123def456" * 5 + "abcd",  # 64 chars
                "size_bytes": 50,
                "content_type": "application/json",
                "version": "1.0",
                "metadata": {}
            },
            "contents": {"test": "data"}
        }

        bundle = Bundle.from_dict(legacy_bundle)

        assert bundle.rid == legacy_bundle["rid"]
        assert bundle.manifest.content_hash == legacy_bundle["manifest"]["content_hash"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
