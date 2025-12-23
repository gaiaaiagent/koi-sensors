"""
P2a Persistent Cache Tests

Tests for disk-backed bundle cache using rid_lib.ext.Cache.
Verifies bundles survive restart and maintain JCS hash parity.
"""

import json
import tempfile
import pytest
from pathlib import Path

from koi_protocol.core.bundle_system import Bundle, Manifest
from koi_protocol.core.rid_system import RID, GenericRID
from koi_protocol.core.persistent_cache import (
    PersistentBundleCache,
    RID_LIB_CACHE_AVAILABLE,
    _internal_to_ridlib_bundle,
    _ridlib_to_internal_bundle,
)


@pytest.fixture
def temp_cache_dir():
    """Create a temporary cache directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_bundle():
    """Create a sample bundle for testing."""
    rid = RID.parse("orn:test:sample-bundle-123")
    contents = {"title": "Test Bundle", "data": {"value": 42, "nested": [1, 2, 3]}}
    return Bundle.generate(rid, contents)


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestPersistentBundleCache:
    """Test PersistentBundleCache operations."""

    def test_cache_init_creates_directory(self, temp_cache_dir):
        """Cache initializes and creates directory."""
        cache_path = Path(temp_cache_dir) / "subdir" / "cache"
        cache = PersistentBundleCache(str(cache_path))
        assert cache_path.exists()

    def test_write_and_read_roundtrip(self, temp_cache_dir, sample_bundle):
        """Write bundle to cache and read it back."""
        cache = PersistentBundleCache(temp_cache_dir)
        cache.write(sample_bundle)

        # Read back
        read_bundle = cache.read(sample_bundle.rid)
        assert read_bundle is not None
        assert read_bundle.rid == sample_bundle.rid
        assert read_bundle.contents == sample_bundle.contents
        assert read_bundle.manifest.sha256_hash == sample_bundle.manifest.sha256_hash

    def test_exists_check(self, temp_cache_dir, sample_bundle):
        """Check if bundle exists in cache."""
        cache = PersistentBundleCache(temp_cache_dir)

        assert not cache.exists(sample_bundle.rid)
        cache.write(sample_bundle)
        assert cache.exists(sample_bundle.rid)

    def test_delete_bundle(self, temp_cache_dir, sample_bundle):
        """Delete bundle from cache."""
        cache = PersistentBundleCache(temp_cache_dir)
        cache.write(sample_bundle)
        assert cache.exists(sample_bundle.rid)

        deleted = cache.delete(sample_bundle.rid)
        assert deleted is True
        assert not cache.exists(sample_bundle.rid)

    def test_list_rids(self, temp_cache_dir, sample_bundle):
        """List all RIDs in cache."""
        cache = PersistentBundleCache(temp_cache_dir)
        assert cache.list_rids() == []

        cache.write(sample_bundle)
        rids = cache.list_rids()
        assert sample_bundle.rid in rids

    def test_persistence_across_instances(self, temp_cache_dir, sample_bundle):
        """Bundle persists when cache is recreated (simulating restart)."""
        # Write with first cache instance
        cache1 = PersistentBundleCache(temp_cache_dir)
        cache1.write(sample_bundle)

        # Create new instance (simulating restart)
        cache2 = PersistentBundleCache(temp_cache_dir)
        cache2.load_all()

        # Verify bundle is still there
        read_bundle = cache2.read(sample_bundle.rid)
        assert read_bundle is not None
        assert read_bundle.rid == sample_bundle.rid
        assert read_bundle.contents == sample_bundle.contents

    def test_load_all_populates_memory_cache(self, temp_cache_dir, sample_bundle):
        """load_all() populates memory cache from disk."""
        cache1 = PersistentBundleCache(temp_cache_dir)
        cache1.write(sample_bundle)

        # New instance, memory cache should be empty initially
        cache2 = PersistentBundleCache(temp_cache_dir)
        assert cache2.size() == 0

        # After load_all, memory cache should be populated
        loaded = cache2.load_all()
        assert loaded == 1
        assert cache2.size() == 1
        assert sample_bundle.rid in cache2.list_rids()

    def test_stats(self, temp_cache_dir, sample_bundle):
        """Cache stats are reported correctly."""
        cache = PersistentBundleCache(temp_cache_dir)
        cache.write(sample_bundle)

        stats = cache.stats()
        assert stats["memory_size"] == 1
        assert stats["disk_available"] is True
        assert temp_cache_dir in stats["directory"]


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestBundleConversion:
    """Test conversion between internal and rid_lib Bundle types."""

    def test_internal_to_ridlib_bundle(self, sample_bundle):
        """Convert internal Bundle to rid_lib Bundle."""
        ridlib_bundle = _internal_to_ridlib_bundle(sample_bundle)

        # Verify structure
        assert str(ridlib_bundle.manifest.rid) == sample_bundle.rid
        assert ridlib_bundle.contents == sample_bundle.contents
        # JCS hash should match
        assert ridlib_bundle.manifest.sha256_hash == sample_bundle.manifest.sha256_hash

    def test_ridlib_to_internal_bundle(self, sample_bundle):
        """Convert rid_lib Bundle back to internal Bundle."""
        ridlib_bundle = _internal_to_ridlib_bundle(sample_bundle)
        internal_bundle = _ridlib_to_internal_bundle(ridlib_bundle)

        # Verify structure
        assert internal_bundle.rid == sample_bundle.rid
        assert internal_bundle.contents == sample_bundle.contents
        # JCS hash should match
        assert internal_bundle.manifest.sha256_hash == sample_bundle.manifest.sha256_hash

    def test_conversion_preserves_jcs_hash(self, sample_bundle):
        """JCS hash is preserved through conversion roundtrip."""
        original_hash = sample_bundle.manifest.sha256_hash

        ridlib_bundle = _internal_to_ridlib_bundle(sample_bundle)
        assert ridlib_bundle.manifest.sha256_hash == original_hash

        internal_bundle = _ridlib_to_internal_bundle(ridlib_bundle)
        assert internal_bundle.manifest.sha256_hash == original_hash

    def test_conversion_reconstructs_internal_extras(self, sample_bundle):
        """Internal extras are reconstructed on read."""
        ridlib_bundle = _internal_to_ridlib_bundle(sample_bundle)
        internal_bundle = _ridlib_to_internal_bundle(ridlib_bundle)

        # Internal extras should be reconstructed
        assert internal_bundle.manifest.size_bytes > 0
        assert internal_bundle.manifest.content_type == "application/json"
        assert internal_bundle.manifest.legacy_content_hash is not None
        # Metadata is empty (not persisted)
        assert internal_bundle.manifest.metadata == {}


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestKOINodeBasePersistence:
    """Test KOINodeBase cache integration with persistent cache."""

    def test_koi_node_with_cache_dir(self, temp_cache_dir, sample_bundle):
        """KOI node uses persistent cache when cache_dir is provided."""
        from koi_protocol.nodes.koi_node import KOIFullNode

        node = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)

        # Cache bundle
        node.cache_bundle(sample_bundle)

        # Verify in memory and on disk
        assert node.has_cached_bundle(sample_bundle.rid)

        # Check disk has the file
        files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(files) == 1

    def test_koi_node_persistence_across_restart(self, temp_cache_dir, sample_bundle):
        """Bundles persist across node restart."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        import asyncio

        # First node instance - write bundle
        node1 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        node1.cache_bundle(sample_bundle)

        # Second node instance (simulating restart)
        node2 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)

        # Run start() to load bundles from disk
        asyncio.get_event_loop().run_until_complete(node2.start())
        asyncio.get_event_loop().run_until_complete(node2.stop())

        # Bundle should be available
        read_bundle = node2.get_cached_bundle(sample_bundle.rid)
        assert read_bundle is not None
        assert read_bundle.rid == sample_bundle.rid
        assert read_bundle.contents == sample_bundle.contents

    def test_koi_node_remove_bundle_from_disk(self, temp_cache_dir, sample_bundle):
        """Removing bundle deletes from both memory and disk."""
        from koi_protocol.nodes.koi_node import KOIFullNode

        node = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        node.cache_bundle(sample_bundle)

        # Verify file exists
        files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(files) == 1

        # Remove bundle
        deleted = node.remove_cached_bundle(sample_bundle.rid)
        assert deleted is True

        # Verify removed from both
        assert not node.has_cached_bundle(sample_bundle.rid)
        files = list(Path(temp_cache_dir).glob("*.json"))
        assert len(files) == 0


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestJCSHashParity:
    """Test JCS hash parity with rid_lib."""

    def test_hash_matches_ridlib_generate(self, sample_bundle):
        """Our sha256_hash matches rid_lib's Manifest.generate()."""
        from rid_lib.ext import Manifest as RidLibManifest

        # Generate using rid_lib directly
        ridlib_manifest = RidLibManifest.generate(sample_bundle.rid, sample_bundle.contents)

        # Should match our hash
        assert sample_bundle.manifest.sha256_hash == ridlib_manifest.sha256_hash

    def test_persisted_bundle_hash_parity(self, temp_cache_dir, sample_bundle):
        """Persisted bundle maintains hash parity with rid_lib."""
        from rid_lib.ext import Cache as RidLibCache, Manifest as RidLibManifest
        from rid_lib.core import ORN

        cache = PersistentBundleCache(temp_cache_dir)
        cache.write(sample_bundle)

        # Read directly with rid_lib cache
        ridlib_cache = RidLibCache(temp_cache_dir)
        rid_obj = ORN.from_string(sample_bundle.rid)
        ridlib_bundle = ridlib_cache.read(rid_obj)

        # Hash should match
        assert ridlib_bundle.manifest.sha256_hash == sample_bundle.manifest.sha256_hash

        # Recompute hash from contents and verify
        recomputed = RidLibManifest.generate(sample_bundle.rid, sample_bundle.contents)
        assert recomputed.sha256_hash == sample_bundle.manifest.sha256_hash


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestTimestampZSuffix:
    """Test timestamp Z suffix handling."""

    def test_persisted_bundle_has_z_suffix(self, temp_cache_dir, sample_bundle):
        """Bundles read from disk have Z suffix timestamps."""
        cache = PersistentBundleCache(temp_cache_dir)
        cache.write(sample_bundle)

        # Create new cache instance and load
        cache2 = PersistentBundleCache(temp_cache_dir)
        cache2.load_all()

        read_bundle = cache2.read(sample_bundle.rid)

        # Timestamp should end with Z
        ts = read_bundle.manifest.timestamp
        assert ts.endswith("Z") or "+" in ts, f"Timestamp should have timezone: {ts}"
