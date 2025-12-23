"""
KOI Protocol - Persistent Bundle Cache (P2a)

Disk-backed cache using rid_lib.ext.Cache for durable state transfer.
Persists strict rid-lib Bundle format for KOI-net interoperability.
Internal manifest extras (size_bytes, content_type, metadata) are reconstructed on read.

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .bundle_system import Bundle, Manifest, _legacy_hash_content

# Import rid_lib for persistent cache
try:
    from rid_lib.ext import Cache as RidLibCache
    from rid_lib.ext import Bundle as RidLibBundle
    from rid_lib.ext import Manifest as RidLibManifest
    from rid_lib.core import ORN
    RID_LIB_CACHE_AVAILABLE = True
except ImportError:
    RID_LIB_CACHE_AVAILABLE = False
    RidLibCache = None
    RidLibBundle = None
    RidLibManifest = None
    ORN = None


logger = logging.getLogger("koi.persistent_cache")


def _internal_to_ridlib_bundle(bundle: Bundle) -> "RidLibBundle":
    """
    Convert internal Bundle to rid_lib Bundle for disk persistence.

    Only stores KOI-net strict format: {manifest: {rid, timestamp, sha256_hash}, contents}.
    Internal extras (size_bytes, content_type, metadata, legacy_content_hash) are NOT persisted.
    """
    if not RID_LIB_CACHE_AVAILABLE:
        raise RuntimeError("rid_lib not available for cache persistence")

    # Use Bundle.generate to create a proper rid_lib Bundle with JCS hashing
    rid = ORN.from_string(bundle.rid)
    return RidLibBundle.generate(rid, bundle.contents)


def _ridlib_to_internal_bundle(ridlib_bundle: "RidLibBundle") -> Bundle:
    """
    Convert rid_lib Bundle back to internal Bundle.

    Reconstructs internal extras from contents:
    - size_bytes: computed from contents
    - content_type: defaults to "application/json"
    - legacy_content_hash: recomputed from contents
    - metadata: empty dict (not persisted, internal-only)
    """
    contents = ridlib_bundle.contents
    rid_str = str(ridlib_bundle.manifest.rid)

    # Recompute internal extras
    legacy_hash, content_bytes = _legacy_hash_content(contents)

    # Get timestamp as ISO string
    ts = ridlib_bundle.manifest.timestamp
    if hasattr(ts, 'isoformat'):
        timestamp_str = ts.isoformat()
    else:
        timestamp_str = str(ts)

    # Ensure Z suffix for KOI-net wire format
    if timestamp_str.endswith('+00:00'):
        timestamp_str = timestamp_str.replace('+00:00', 'Z')

    manifest = Manifest(
        rid=rid_str,
        timestamp=timestamp_str,
        sha256_hash=ridlib_bundle.manifest.sha256_hash,
        size_bytes=len(content_bytes),
        content_type="application/json",
        version="1.0",
        metadata={},
        legacy_content_hash=legacy_hash
    )

    return Bundle(
        rid=rid_str,
        manifest=manifest,
        contents=contents
    )


class PersistentBundleCache:
    """
    Disk-backed bundle cache using rid_lib.ext.Cache.

    Provides memory cache + disk persistence with write-through semantics.
    Bundles are stored in strict KOI-net format for interoperability.

    Usage:
        cache = PersistentBundleCache("/path/to/cache")
        cache.write(bundle)
        bundle = cache.read(rid)
        rids = cache.list_rids()
    """

    def __init__(self, directory_path: str):
        """
        Initialize persistent cache.

        Args:
            directory_path: Path to cache directory (created if not exists)
        """
        if not RID_LIB_CACHE_AVAILABLE:
            raise RuntimeError("rid_lib not available - cannot create persistent cache")

        self.directory_path = Path(directory_path)
        self.directory_path.mkdir(parents=True, exist_ok=True)

        self._disk_cache = RidLibCache(str(self.directory_path))
        self._memory_cache: Dict[str, Bundle] = {}

        logger.info(f"Initialized persistent cache at {self.directory_path}")

    def load_all(self) -> int:
        """
        Load all bundles from disk into memory cache.

        Returns:
            Number of bundles loaded
        """
        count = 0
        try:
            rids = self._disk_cache.list_rids()
            for rid in rids:
                try:
                    ridlib_bundle = self._disk_cache.read(rid)
                    if ridlib_bundle:
                        internal_bundle = _ridlib_to_internal_bundle(ridlib_bundle)
                        self._memory_cache[str(rid)] = internal_bundle
                        count += 1
                except Exception as e:
                    logger.warning(f"Failed to load bundle {rid}: {e}")

            logger.info(f"Loaded {count} bundles from persistent cache")
        except Exception as e:
            logger.error(f"Failed to load bundles from cache: {e}")

        return count

    def write(self, bundle: Bundle) -> None:
        """
        Write bundle to both memory and disk cache.

        Args:
            bundle: Internal Bundle to persist
        """
        rid_str = bundle.rid

        # Write to memory cache
        self._memory_cache[rid_str] = bundle

        # Write to disk cache (KOI-net strict format)
        try:
            ridlib_bundle = _internal_to_ridlib_bundle(bundle)
            self._disk_cache.write(ridlib_bundle)
            logger.debug(f"Persisted bundle to disk: {rid_str}")
        except Exception as e:
            logger.error(f"Failed to persist bundle {rid_str}: {e}")
            # Memory cache still updated - disk will be inconsistent

    def read(self, rid: str) -> Optional[Bundle]:
        """
        Read bundle from cache (memory first, then disk).

        Args:
            rid: RID string to look up

        Returns:
            Bundle if found, None otherwise
        """
        # Check memory cache first
        if rid in self._memory_cache:
            return self._memory_cache[rid]

        # Try disk cache
        try:
            rid_obj = ORN.from_string(rid)
            ridlib_bundle = self._disk_cache.read(rid_obj)
            if ridlib_bundle:
                internal_bundle = _ridlib_to_internal_bundle(ridlib_bundle)
                # Populate memory cache
                self._memory_cache[rid] = internal_bundle
                return internal_bundle
        except Exception as e:
            logger.debug(f"Bundle not found on disk: {rid} ({e})")

        return None

    def exists(self, rid: str) -> bool:
        """
        Check if bundle exists in cache.

        Args:
            rid: RID string to check

        Returns:
            True if bundle exists
        """
        if rid in self._memory_cache:
            return True

        try:
            rid_obj = ORN.from_string(rid)
            return self._disk_cache.exists(rid_obj)
        except Exception:
            return False

    def delete(self, rid: str) -> bool:
        """
        Delete bundle from both memory and disk cache.

        Args:
            rid: RID string to delete

        Returns:
            True if bundle was deleted
        """
        deleted = False

        # Delete from memory
        if rid in self._memory_cache:
            del self._memory_cache[rid]
            deleted = True

        # Delete from disk
        try:
            rid_obj = ORN.from_string(rid)
            if self._disk_cache.exists(rid_obj):
                self._disk_cache.delete(rid_obj)
                deleted = True
                logger.debug(f"Deleted bundle from disk: {rid}")
        except Exception as e:
            logger.warning(f"Failed to delete bundle from disk {rid}: {e}")

        return deleted

    def list_rids(self) -> List[str]:
        """
        List all RIDs in cache (from memory, which is loaded from disk on startup).

        Returns:
            List of RID strings
        """
        return list(self._memory_cache.keys())

    def size(self) -> int:
        """
        Get number of bundles in cache.

        Returns:
            Number of cached bundles
        """
        return len(self._memory_cache)

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        return {
            "directory": str(self.directory_path),
            "memory_size": len(self._memory_cache),
            "disk_available": RID_LIB_CACHE_AVAILABLE
        }
