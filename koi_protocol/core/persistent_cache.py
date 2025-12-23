"""
KOI Protocol - Persistent Bundle Cache (P2a + P2b)

Disk-backed cache using rid_lib.ext.Cache for durable state transfer.
Persists strict rid-lib Bundle format for KOI-net interoperability.
Internal manifest extras (size_bytes, content_type, metadata) are reconstructed on read.

P2b adds retention policy with:
- Max-size / max-age pruning
- Protected bundles (NodeProfile, identity bundles)
- Metrics and monitoring
- Scheduled pruning support

Environment variables:
- KOI_CACHE_MAX_SIZE_MB: Max cache size in MB (default: 500)
- KOI_CACHE_MAX_AGE_DAYS: Max bundle age in days (default: 30)
- KOI_CACHE_DISK_ALERT_PERCENT: Alert threshold (default: 80)

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .bundle_system import Bundle, Manifest, _legacy_hash_content

# Retention policy defaults (conservative)
DEFAULT_MAX_SIZE_MB = 500
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_DISK_ALERT_PERCENT = 80

# Protected bundle patterns - never pruned
# These match RID prefixes for identity/profile bundles
PROTECTED_RID_PATTERNS = [
    r"^orn:koi\.node_profile:",     # KOI-net node profiles
    r"^orn:koi\.identity:",          # Node identity bundles
    r"^orn:koi\.config:",            # Configuration bundles
]

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


def _is_protected_rid(rid: str) -> bool:
    """
    Check if a RID matches protected patterns (should never be pruned).

    Protected bundles include:
    - Node profiles (orn:koi.node_profile:*)
    - Identity bundles (orn:koi.identity:*)
    - Configuration bundles (orn:koi.config:*)
    """
    for pattern in PROTECTED_RID_PATTERNS:
        if re.match(pattern, rid):
            return True
    return False


def _get_retention_config() -> Dict[str, Any]:
    """
    Get retention policy configuration from environment variables.

    Returns:
        Dict with max_size_mb, max_age_days, disk_alert_percent
    """
    return {
        "max_size_mb": int(os.getenv("KOI_CACHE_MAX_SIZE_MB", DEFAULT_MAX_SIZE_MB)),
        "max_age_days": int(os.getenv("KOI_CACHE_MAX_AGE_DAYS", DEFAULT_MAX_AGE_DAYS)),
        "disk_alert_percent": int(os.getenv("KOI_CACHE_DISK_ALERT_PERCENT", DEFAULT_DISK_ALERT_PERCENT)),
    }


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

    # =========================================================================
    # P2b: Retention Policy Methods
    # =========================================================================

    def get_disk_usage_bytes(self) -> int:
        """
        Calculate total disk usage of the cache directory.

        Returns:
            Total bytes used by cache files
        """
        total = 0
        try:
            for file_path in self.directory_path.glob("*.json"):
                total += file_path.stat().st_size
        except Exception as e:
            logger.warning(f"Error calculating disk usage: {e}")
        return total

    def get_disk_usage_mb(self) -> float:
        """
        Calculate total disk usage in megabytes.

        Returns:
            Total MB used by cache files
        """
        return self.get_disk_usage_bytes() / (1024 * 1024)

    def get_bundle_ages(self) -> List[Tuple[str, datetime, bool]]:
        """
        Get all bundles with their timestamps and protection status.

        Returns:
            List of (rid, timestamp, is_protected) tuples, sorted oldest first
        """
        bundles_with_age = []
        for rid, bundle in self._memory_cache.items():
            try:
                ts_str = bundle.manifest.timestamp
                # Parse timestamp (handle both Z and +00:00 formats)
                if ts_str.endswith('Z'):
                    ts_str = ts_str[:-1] + '+00:00'
                ts = datetime.fromisoformat(ts_str)
                is_protected = _is_protected_rid(rid)
                bundles_with_age.append((rid, ts, is_protected))
            except Exception as e:
                logger.warning(f"Failed to parse timestamp for {rid}: {e}")
                # Use epoch as fallback (will be pruned first)
                bundles_with_age.append((rid, datetime(1970, 1, 1, tzinfo=timezone.utc), _is_protected_rid(rid)))

        # Sort by timestamp (oldest first)
        bundles_with_age.sort(key=lambda x: x[1])
        return bundles_with_age

    def prune_by_age(self, max_age_days: int = None) -> Dict[str, Any]:
        """
        Prune bundles older than max_age_days.

        Args:
            max_age_days: Maximum age in days (uses env config if not specified)

        Returns:
            Dict with pruning stats: pruned_count, pruned_rids, protected_skipped
        """
        if max_age_days is None:
            max_age_days = _get_retention_config()["max_age_days"]

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        bundles = self.get_bundle_ages()

        pruned_rids = []
        protected_skipped = 0

        for rid, ts, is_protected in bundles:
            if ts < cutoff:
                if is_protected:
                    protected_skipped += 1
                    logger.debug(f"Skipping protected bundle: {rid}")
                else:
                    self.delete(rid)
                    pruned_rids.append(rid)
                    logger.info(f"Pruned by age: {rid} (age: {(datetime.now(timezone.utc) - ts).days} days)")

        result = {
            "pruned_count": len(pruned_rids),
            "pruned_rids": pruned_rids,
            "protected_skipped": protected_skipped,
            "cutoff_date": cutoff.isoformat(),
            "max_age_days": max_age_days,
        }

        if pruned_rids:
            logger.info(f"Age-based pruning: {len(pruned_rids)} bundles pruned, {protected_skipped} protected skipped")

        return result

    def prune_by_size(self, max_size_mb: float = None) -> Dict[str, Any]:
        """
        Prune oldest bundles until cache is under max_size_mb.

        Args:
            max_size_mb: Maximum size in MB (uses env config if not specified)

        Returns:
            Dict with pruning stats: pruned_count, pruned_rids, protected_skipped, final_size_mb
        """
        if max_size_mb is None:
            max_size_mb = _get_retention_config()["max_size_mb"]

        initial_size = self.get_disk_usage_mb()
        if initial_size <= max_size_mb:
            return {
                "pruned_count": 0,
                "pruned_rids": [],
                "protected_skipped": 0,
                "initial_size_mb": initial_size,
                "final_size_mb": initial_size,
                "max_size_mb": max_size_mb,
            }

        bundles = self.get_bundle_ages()  # Sorted oldest first
        pruned_rids = []
        protected_skipped = 0

        for rid, ts, is_protected in bundles:
            current_size = self.get_disk_usage_mb()
            if current_size <= max_size_mb:
                break

            if is_protected:
                protected_skipped += 1
                logger.debug(f"Skipping protected bundle: {rid}")
            else:
                self.delete(rid)
                pruned_rids.append(rid)
                logger.info(f"Pruned by size: {rid} (reclaiming space)")

        final_size = self.get_disk_usage_mb()
        result = {
            "pruned_count": len(pruned_rids),
            "pruned_rids": pruned_rids,
            "protected_skipped": protected_skipped,
            "initial_size_mb": initial_size,
            "final_size_mb": final_size,
            "max_size_mb": max_size_mb,
        }

        if pruned_rids:
            logger.info(f"Size-based pruning: {len(pruned_rids)} bundles pruned, "
                       f"{initial_size:.2f}MB -> {final_size:.2f}MB (max: {max_size_mb}MB)")

        return result

    def prune(self, max_age_days: int = None, max_size_mb: float = None) -> Dict[str, Any]:
        """
        Run full retention policy: prune by age, then by size.

        Args:
            max_age_days: Maximum age in days (uses env config if not specified)
            max_size_mb: Maximum size in MB (uses env config if not specified)

        Returns:
            Dict with combined pruning stats
        """
        logger.info("Starting retention policy prune cycle")

        # Get config
        config = _get_retention_config()
        if max_age_days is None:
            max_age_days = config["max_age_days"]
        if max_size_mb is None:
            max_size_mb = config["max_size_mb"]

        # Record initial state
        initial_count = self.size()
        initial_size_mb = self.get_disk_usage_mb()

        # Prune by age first
        age_result = self.prune_by_age(max_age_days)

        # Then prune by size
        size_result = self.prune_by_size(max_size_mb)

        # Combined results
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "initial_count": initial_count,
            "initial_size_mb": initial_size_mb,
            "final_count": self.size(),
            "final_size_mb": self.get_disk_usage_mb(),
            "age_pruned": age_result["pruned_count"],
            "size_pruned": size_result["pruned_count"],
            "total_pruned": age_result["pruned_count"] + size_result["pruned_count"],
            "protected_skipped": age_result["protected_skipped"] + size_result["protected_skipped"],
            "config": {
                "max_age_days": max_age_days,
                "max_size_mb": max_size_mb,
            }
        }

        logger.info(f"Prune cycle complete: {result['total_pruned']} bundles pruned, "
                   f"{result['initial_count']} -> {result['final_count']} bundles, "
                   f"{result['initial_size_mb']:.2f}MB -> {result['final_size_mb']:.2f}MB")

        return result

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get comprehensive cache metrics for monitoring.

        Returns:
            Dict with metrics: bundle_count, disk_usage_bytes, disk_usage_mb,
                             protected_count, config, alerts
        """
        config = _get_retention_config()

        # Count protected bundles
        protected_count = sum(1 for rid in self._memory_cache if _is_protected_rid(rid))

        disk_usage_mb = self.get_disk_usage_mb()
        disk_usage_bytes = self.get_disk_usage_bytes()

        # Check for alert conditions
        alerts = []
        if disk_usage_mb > config["max_size_mb"]:
            alerts.append({
                "type": "cache_size_exceeded",
                "message": f"Cache size {disk_usage_mb:.2f}MB exceeds max {config['max_size_mb']}MB",
                "severity": "warning",
            })

        # Check disk space (requires psutil, gracefully handle if unavailable)
        try:
            import shutil
            disk_stat = shutil.disk_usage(self.directory_path)
            disk_percent_used = (disk_stat.used / disk_stat.total) * 100
            if disk_percent_used > config["disk_alert_percent"]:
                alerts.append({
                    "type": "disk_space_low",
                    "message": f"Disk usage {disk_percent_used:.1f}% exceeds alert threshold {config['disk_alert_percent']}%",
                    "severity": "critical",
                })
        except Exception:
            disk_percent_used = None

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bundle_count": self.size(),
            "disk_usage_bytes": disk_usage_bytes,
            "disk_usage_mb": round(disk_usage_mb, 2),
            "protected_count": protected_count,
            "prunable_count": self.size() - protected_count,
            "config": config,
            "disk_percent_used": round(disk_percent_used, 1) if disk_percent_used else None,
            "alerts": alerts,
            "has_alerts": len(alerts) > 0,
        }
