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


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestEventSemanticsPersistence:
    """Test FORGET and UPDATE event semantics with persistent cache."""

    def test_forget_event_deletes_from_disk(self, temp_cache_dir, sample_bundle):
        """FORGET event deletes bundle from persistent cache."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent
        import asyncio

        node = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)

        # First cache the bundle
        node.cache_bundle(sample_bundle)
        assert node.has_cached_bundle(sample_bundle.rid)
        assert len(list(Path(temp_cache_dir).glob("*.json"))) == 1

        # Create and handle FORGET event (use RID object, not string)
        rid = RID.parse(sample_bundle.rid)
        forget_event = KOIEvent.forget_event(rid, "test-node", "test deletion")
        asyncio.get_event_loop().run_until_complete(node.handle_event(forget_event))

        # Verify deleted from memory and disk
        assert not node.has_cached_bundle(sample_bundle.rid)
        assert len(list(Path(temp_cache_dir).glob("*.json"))) == 0

    def test_forget_persists_across_restart(self, temp_cache_dir, sample_bundle):
        """FORGET deletion persists across node restart."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent
        import asyncio

        # First node: cache then forget
        node1 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        node1.cache_bundle(sample_bundle)

        rid = RID.parse(sample_bundle.rid)
        forget_event = KOIEvent.forget_event(rid, "test-node", "test deletion")
        asyncio.get_event_loop().run_until_complete(node1.handle_event(forget_event))

        # Second node: verify bundle is gone
        node2 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        asyncio.get_event_loop().run_until_complete(node2.start())
        asyncio.get_event_loop().run_until_complete(node2.stop())

        assert not node2.has_cached_bundle(sample_bundle.rid)

    def test_update_overwrites_same_rid(self, temp_cache_dir, sample_bundle):
        """UPDATE event overwrites existing bundle with same RID."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent, Bundle
        from koi_protocol.core.rid_system import RID
        import asyncio

        node = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)

        # Cache original bundle
        node.cache_bundle(sample_bundle)
        original_hash = sample_bundle.manifest.sha256_hash

        # Create updated bundle with same RID but different contents
        rid = RID.parse(sample_bundle.rid)
        updated_contents = {"title": "Updated Bundle", "data": {"value": 999}}
        updated_bundle = Bundle.generate(rid, updated_contents)

        # Handle UPDATE event
        update_event = KOIEvent.update_event(updated_bundle, "test-node")
        asyncio.get_event_loop().run_until_complete(node.handle_event(update_event))

        # Verify bundle was updated
        read_bundle = node.get_cached_bundle(sample_bundle.rid)
        assert read_bundle.contents == updated_contents
        assert read_bundle.manifest.sha256_hash != original_hash

        # Verify only one file on disk (overwritten, not duplicated)
        assert len(list(Path(temp_cache_dir).glob("*.json"))) == 1

    def test_update_persists_across_restart(self, temp_cache_dir, sample_bundle):
        """Updated bundle persists with new contents across restart."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent, Bundle
        from koi_protocol.core.rid_system import RID
        import asyncio

        # First node: cache then update
        node1 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        node1.cache_bundle(sample_bundle)

        rid = RID.parse(sample_bundle.rid)
        updated_contents = {"title": "Persisted Update", "version": 2}
        updated_bundle = Bundle.generate(rid, updated_contents)

        update_event = KOIEvent.update_event(updated_bundle, "test-node")
        asyncio.get_event_loop().run_until_complete(node1.handle_event(update_event))

        # Second node: verify updated contents
        node2 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        asyncio.get_event_loop().run_until_complete(node2.start())
        asyncio.get_event_loop().run_until_complete(node2.stop())

        read_bundle = node2.get_cached_bundle(sample_bundle.rid)
        assert read_bundle.contents == updated_contents


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestSeedScriptIdempotency:
    """Test seed script idempotency."""

    def test_seed_twice_no_duplicates(self, temp_cache_dir, sample_bundle):
        """Running seed twice doesn't create duplicate entries."""
        cache = PersistentBundleCache(temp_cache_dir)

        # Seed first time
        cache.write(sample_bundle)
        assert cache.size() == 1
        files_after_first = list(Path(temp_cache_dir).glob("*.json"))

        # Seed second time (same bundle)
        cache.write(sample_bundle)
        assert cache.size() == 1  # Still 1, not 2
        files_after_second = list(Path(temp_cache_dir).glob("*.json"))

        # Same file, same count
        assert len(files_after_first) == len(files_after_second) == 1
        assert files_after_first[0].name == files_after_second[0].name

    def test_seed_overwrites_deterministically(self, temp_cache_dir, sample_bundle):
        """Seeding same RID with different contents overwrites."""
        from koi_protocol.core.bundle_system import Bundle
        from koi_protocol.core.rid_system import RID

        cache = PersistentBundleCache(temp_cache_dir)

        # First seed
        cache.write(sample_bundle)
        first_hash = cache.read(sample_bundle.rid).manifest.sha256_hash

        # Create new bundle with same RID but different contents
        rid = RID.parse(sample_bundle.rid)
        new_contents = {"completely": "different", "data": 123}
        new_bundle = Bundle.generate(rid, new_contents)

        # Second seed with different contents
        cache.write(new_bundle)

        # Verify overwritten
        read_bundle = cache.read(sample_bundle.rid)
        assert read_bundle.contents == new_contents
        assert read_bundle.manifest.sha256_hash != first_hash
        assert cache.size() == 1


@pytest.mark.skipif(not RID_LIB_CACHE_AVAILABLE, reason="rid_lib not available")
class TestSignedPersistenceIntegration:
    """Test SignedEnvelope + persistence integration."""

    def test_signed_broadcast_persist_signed_fetch(self, temp_cache_dir, sample_bundle):
        """Signed broadcast → persist → restart → signed fetch verifies."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        from koi_protocol.core.bundle_system import KOIEvent
        from shared.koi_envelope import sign_envelope, verify_envelope_with_key
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        import asyncio

        # Generate keypairs for test
        node_private = ec.generate_private_key(ec.SECP256R1(), default_backend())
        node_public = node_private.public_key()
        coordinator_private = ec.generate_private_key(ec.SECP256R1(), default_backend())
        coordinator_public = coordinator_private.public_key()

        node_id = "orn:koi-net.node:test-node+abc123"
        coordinator_id = "orn:koi-net.node:test-coordinator+def456"

        # First node instance: receive signed broadcast and persist
        node1 = KOIFullNode("test-coordinator", port=8000, cache_dir=temp_cache_dir)
        node1.node_id = coordinator_id

        # Simulate signed broadcast
        broadcast_payload = {
            "type": "events_payload",
            "events": [{
                "rid": sample_bundle.rid,
                "event_type": "NEW",
                "manifest": {
                    "rid": sample_bundle.rid,
                    "timestamp": sample_bundle.manifest.timestamp,
                    "sha256_hash": sample_bundle.manifest.sha256_hash
                },
                "contents": sample_bundle.contents
            }]
        }
        signed_broadcast = sign_envelope(
            broadcast_payload, node_id, coordinator_id, node_private
        )

        # Verify incoming signature
        assert verify_envelope_with_key(signed_broadcast, node_public)

        # Cache the bundle (simulating coordinator processing broadcast)
        node1.cache_bundle(sample_bundle)

        # Restart: create new node instance
        node2 = KOIFullNode("test-coordinator", port=8000, cache_dir=temp_cache_dir)
        node2.node_id = coordinator_id
        asyncio.get_event_loop().run_until_complete(node2.start())
        asyncio.get_event_loop().run_until_complete(node2.stop())

        # Verify bundle persisted
        read_bundle = node2.get_cached_bundle(sample_bundle.rid)
        assert read_bundle is not None

        # Sign fetch response
        fetch_response = {
            "type": "bundles_payload",
            "bundles": [{
                "manifest": {
                    "rid": read_bundle.rid,
                    "timestamp": read_bundle.manifest.timestamp,
                    "sha256_hash": read_bundle.manifest.sha256_hash
                },
                "contents": read_bundle.contents
            }]
        }
        signed_response = sign_envelope(
            fetch_response, coordinator_id, node_id, coordinator_private
        )

        # Verify signed response
        assert verify_envelope_with_key(signed_response, coordinator_public)

        # Verify contents match original
        response_bundle = signed_response["payload"]["bundles"][0]
        assert response_bundle["contents"] == sample_bundle.contents
        assert response_bundle["manifest"]["sha256_hash"] == sample_bundle.manifest.sha256_hash

    def test_persisted_hash_matches_original(self, temp_cache_dir, sample_bundle):
        """JCS hash is preserved exactly through persistence cycle."""
        from koi_protocol.nodes.koi_node import KOIFullNode
        import asyncio

        original_hash = sample_bundle.manifest.sha256_hash

        # First node: persist
        node1 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        node1.cache_bundle(sample_bundle)

        # Second node: read back
        node2 = KOIFullNode("test-node", port=8000, cache_dir=temp_cache_dir)
        asyncio.get_event_loop().run_until_complete(node2.start())
        asyncio.get_event_loop().run_until_complete(node2.stop())

        read_bundle = node2.get_cached_bundle(sample_bundle.rid)

        # Hash must match exactly (no serialization drift)
        assert read_bundle.manifest.sha256_hash == original_hash
