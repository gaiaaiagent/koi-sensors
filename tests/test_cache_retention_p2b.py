"""
P2b Cache Retention Policy Tests

Tests for:
- Protected bundle detection
- Age-based pruning
- Size-based pruning
- Combined retention policy
- Metrics and monitoring
- Environment variable configuration
"""

import os
import json
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from koi_protocol.core.bundle_system import Bundle, Manifest
from koi_protocol.core.persistent_cache import (
    PersistentBundleCache,
    RID_LIB_CACHE_AVAILABLE,
    _is_protected_rid,
    _get_retention_config,
    PROTECTED_RID_PATTERNS,
    DEFAULT_MAX_SIZE_MB,
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_DISK_ALERT_PERCENT,
)

# Skip all tests if rid_lib not available
pytestmark = pytest.mark.skipif(
    not RID_LIB_CACHE_AVAILABLE,
    reason="rid_lib not available"
)


def create_bundle(rid: str, timestamp: datetime = None, content_size: int = 100) -> Bundle:
    """Create a test bundle with specified timestamp and content size."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    # Create content of specified size
    content = {"data": "x" * content_size, "timestamp": timestamp.isoformat()}

    manifest = Manifest(
        rid=rid,
        timestamp=timestamp.isoformat(),
        sha256_hash="test-hash-" + rid,
        size_bytes=len(json.dumps(content)),
        content_type="application/json",
        version="1.0",
        metadata={},
        legacy_content_hash="legacy-hash-" + rid,
    )

    return Bundle(rid=rid, manifest=manifest, contents=content)


class TestProtectedBundleDetection:
    """Tests for protected bundle pattern matching."""

    def test_node_profile_is_protected(self):
        """NodeProfile bundles should be protected."""
        assert _is_protected_rid("orn:koi.node_profile:regen-coordinator") is True
        assert _is_protected_rid("orn:koi.node_profile:test-node") is True

    def test_identity_is_protected(self):
        """Identity bundles should be protected."""
        assert _is_protected_rid("orn:koi.identity:node-123") is True

    def test_config_is_protected(self):
        """Config bundles should be protected."""
        assert _is_protected_rid("orn:koi.config:network-settings") is True

    def test_regular_bundles_not_protected(self):
        """Regular content bundles should NOT be protected."""
        assert _is_protected_rid("orn:discourse:1234") is False
        assert _is_protected_rid("orn:twitter:tweet/5678") is False
        assert _is_protected_rid("orn:github:repo/commit/abc") is False
        assert _is_protected_rid("orn:notion:page-id") is False

    def test_partial_matches_not_protected(self):
        """Partial matches should NOT be protected."""
        assert _is_protected_rid("orn:koi.node_profile_backup:test") is False
        assert _is_protected_rid("orn:not.koi.identity:test") is False


class TestRetentionConfig:
    """Tests for retention policy configuration."""

    def test_default_config(self):
        """Default config should use defined constants."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear any existing env vars
            os.environ.pop("KOI_CACHE_MAX_SIZE_MB", None)
            os.environ.pop("KOI_CACHE_MAX_AGE_DAYS", None)
            os.environ.pop("KOI_CACHE_DISK_ALERT_PERCENT", None)

            config = _get_retention_config()
            assert config["max_size_mb"] == DEFAULT_MAX_SIZE_MB
            assert config["max_age_days"] == DEFAULT_MAX_AGE_DAYS
            assert config["disk_alert_percent"] == DEFAULT_DISK_ALERT_PERCENT

    def test_env_overrides(self):
        """Environment variables should override defaults."""
        with patch.dict(os.environ, {
            "KOI_CACHE_MAX_SIZE_MB": "100",
            "KOI_CACHE_MAX_AGE_DAYS": "7",
            "KOI_CACHE_DISK_ALERT_PERCENT": "90",
        }):
            config = _get_retention_config()
            assert config["max_size_mb"] == 100
            assert config["max_age_days"] == 7
            assert config["disk_alert_percent"] == 90


class TestAgePruning:
    """Tests for age-based pruning."""

    def test_prune_old_bundles(self):
        """Old bundles should be pruned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            # Create bundles with different ages
            now = datetime.now(timezone.utc)
            old_bundle = create_bundle(
                "orn:test:old-bundle",
                timestamp=now - timedelta(days=60)
            )
            new_bundle = create_bundle(
                "orn:test:new-bundle",
                timestamp=now - timedelta(days=5)
            )

            cache.write(old_bundle)
            cache.write(new_bundle)
            assert cache.size() == 2

            # Prune with 30-day limit
            result = cache.prune_by_age(max_age_days=30)

            assert result["pruned_count"] == 1
            assert "orn:test:old-bundle" in result["pruned_rids"]
            assert cache.size() == 1
            assert cache.exists("orn:test:new-bundle")
            assert not cache.exists("orn:test:old-bundle")

    def test_protected_bundles_not_pruned_by_age(self):
        """Protected bundles should not be pruned even if old."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)
            old_protected = create_bundle(
                "orn:koi.node_profile:test-node",
                timestamp=now - timedelta(days=365)  # Very old
            )
            old_regular = create_bundle(
                "orn:test:regular",
                timestamp=now - timedelta(days=60)
            )

            cache.write(old_protected)
            cache.write(old_regular)
            assert cache.size() == 2

            result = cache.prune_by_age(max_age_days=30)

            assert result["pruned_count"] == 1
            assert result["protected_skipped"] == 1
            assert cache.exists("orn:koi.node_profile:test-node")
            assert not cache.exists("orn:test:regular")


class TestSizePruning:
    """Tests for size-based pruning."""

    def test_prune_when_over_size_limit(self):
        """Oldest bundles should be pruned when over size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)
            # Create bundles that are about 500 bytes each
            bundles = []
            for i in range(10):
                bundle = create_bundle(
                    f"orn:test:bundle-{i}",
                    timestamp=now - timedelta(days=i),  # Oldest has highest index
                    content_size=400
                )
                bundles.append(bundle)
                cache.write(bundle)

            assert cache.size() == 10

            # Prune to 1KB limit (should remove most bundles)
            result = cache.prune_by_size(max_size_mb=0.001)  # 1KB

            assert result["pruned_count"] > 0
            assert result["final_size_mb"] <= 0.001 or cache.size() <= 2

    def test_no_prune_when_under_size_limit(self):
        """No pruning should occur when under size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            bundle = create_bundle("orn:test:small-bundle", content_size=100)
            cache.write(bundle)

            # Prune with large limit
            result = cache.prune_by_size(max_size_mb=100)

            assert result["pruned_count"] == 0
            assert cache.size() == 1


class TestCombinedPruning:
    """Tests for combined prune() method."""

    def test_combined_prune_applies_both_policies(self):
        """Prune should apply both age and size policies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)

            # Old bundle (should be pruned by age)
            old_bundle = create_bundle(
                "orn:test:old",
                timestamp=now - timedelta(days=60)
            )
            # Recent bundle
            new_bundle = create_bundle(
                "orn:test:new",
                timestamp=now - timedelta(days=1)
            )
            # Protected bundle (should survive)
            protected = create_bundle(
                "orn:koi.node_profile:test",
                timestamp=now - timedelta(days=365)
            )

            cache.write(old_bundle)
            cache.write(new_bundle)
            cache.write(protected)

            result = cache.prune(max_age_days=30, max_size_mb=100)

            assert result["age_pruned"] == 1
            assert result["protected_skipped"] >= 1
            assert cache.exists("orn:koi.node_profile:test")
            assert cache.exists("orn:test:new")
            assert not cache.exists("orn:test:old")


class TestMetrics:
    """Tests for cache metrics."""

    def test_metrics_returns_expected_fields(self):
        """get_metrics should return all expected fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            bundle = create_bundle("orn:test:metrics-test")
            cache.write(bundle)

            metrics = cache.get_metrics()

            assert "timestamp" in metrics
            assert "bundle_count" in metrics
            assert "disk_usage_bytes" in metrics
            assert "disk_usage_mb" in metrics
            assert "protected_count" in metrics
            assert "prunable_count" in metrics
            assert "config" in metrics
            assert "alerts" in metrics
            assert "has_alerts" in metrics

    def test_metrics_counts_protected_correctly(self):
        """Metrics should correctly count protected bundles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            cache.write(create_bundle("orn:test:regular"))
            cache.write(create_bundle("orn:koi.node_profile:test"))
            cache.write(create_bundle("orn:koi.identity:test"))

            metrics = cache.get_metrics()

            assert metrics["bundle_count"] == 3
            assert metrics["protected_count"] == 2
            assert metrics["prunable_count"] == 1

    def test_alert_on_size_exceeded(self):
        """Alert should trigger when cache exceeds max size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            # Create a bundle
            bundle = create_bundle("orn:test:alert-test", content_size=1000)
            cache.write(bundle)

            # Set very low limit via env
            with patch.dict(os.environ, {"KOI_CACHE_MAX_SIZE_MB": "0"}):
                metrics = cache.get_metrics()

                assert metrics["has_alerts"] is True
                assert any(a["type"] == "cache_size_exceeded" for a in metrics["alerts"])


class TestDiskUsage:
    """Tests for disk usage calculations."""

    def test_disk_usage_increases_with_bundles(self):
        """Disk usage should increase as bundles are added."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            initial_usage = cache.get_disk_usage_bytes()
            assert initial_usage == 0

            cache.write(create_bundle("orn:test:bundle1", content_size=1000))
            after_one = cache.get_disk_usage_bytes()
            assert after_one > 0

            cache.write(create_bundle("orn:test:bundle2", content_size=1000))
            after_two = cache.get_disk_usage_bytes()
            assert after_two > after_one

    def test_disk_usage_decreases_after_prune(self):
        """Disk usage should decrease after pruning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)
            cache.write(create_bundle(
                "orn:test:old",
                timestamp=now - timedelta(days=60),
                content_size=1000
            ))
            cache.write(create_bundle(
                "orn:test:new",
                timestamp=now,
                content_size=1000
            ))

            before_prune = cache.get_disk_usage_bytes()
            cache.prune_by_age(max_age_days=30)
            after_prune = cache.get_disk_usage_bytes()

            assert after_prune < before_prune


class TestBundleAges:
    """Tests for get_bundle_ages method."""

    def test_bundles_sorted_oldest_first(self):
        """Bundles should be sorted with oldest first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)
            cache.write(create_bundle("orn:test:new", timestamp=now))
            cache.write(create_bundle("orn:test:old", timestamp=now - timedelta(days=10)))
            cache.write(create_bundle("orn:test:medium", timestamp=now - timedelta(days=5)))

            ages = cache.get_bundle_ages()

            assert len(ages) == 3
            # Should be sorted oldest first
            assert ages[0][0] == "orn:test:old"
            assert ages[1][0] == "orn:test:medium"
            assert ages[2][0] == "orn:test:new"

    def test_protection_status_included(self):
        """Bundle ages should include protection status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            cache.write(create_bundle("orn:test:regular"))
            cache.write(create_bundle("orn:koi.node_profile:protected"))

            ages = cache.get_bundle_ages()

            regular = next(a for a in ages if a[0] == "orn:test:regular")
            protected = next(a for a in ages if a[0] == "orn:koi.node_profile:protected")

            assert regular[2] is False  # Not protected
            assert protected[2] is True  # Protected


class TestPruneScriptIntegration:
    """Integration tests for the prune script."""

    def test_script_imports_correctly(self):
        """The prune script should import without errors."""
        # This tests that the script's imports work
        from scripts.prune_bundle_cache import run_metrics, run_dry_run, run_prune

    def test_dry_run_does_not_delete(self):
        """Dry run mode should not actually delete anything."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = PersistentBundleCache(tmpdir)

            now = datetime.now(timezone.utc)
            cache.write(create_bundle(
                "orn:test:old",
                timestamp=now - timedelta(days=60)
            ))

            initial_count = cache.size()

            # Import and run dry_run
            from scripts.prune_bundle_cache import run_dry_run
            run_dry_run(cache)

            # Bundle should still exist
            assert cache.size() == initial_count
            assert cache.exists("orn:test:old")
