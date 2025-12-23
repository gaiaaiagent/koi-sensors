#!/usr/bin/env python3
"""
P2b Bundle Cache Pruning Script

Runs retention policy on the persistent bundle cache:
- Prunes bundles older than KOI_CACHE_MAX_AGE_DAYS (default: 30)
- Prunes oldest bundles if cache exceeds KOI_CACHE_MAX_SIZE_MB (default: 500)
- Never prunes protected bundles (NodeProfile, identity, config)
- Logs all actions and outputs metrics

Designed to be run via systemd timer (koi-cache-prune.timer) or cron.

Usage:
    python scripts/prune_bundle_cache.py [--cache-dir PATH] [--dry-run]
    python scripts/prune_bundle_cache.py --metrics-only
    python scripts/prune_bundle_cache.py --help

Environment Variables:
    KOI_CACHE_DIR: Cache directory (default: project-local .rid_cache)
    KOI_CACHE_MAX_SIZE_MB: Max cache size in MB (default: 500)
    KOI_CACHE_MAX_AGE_DAYS: Max bundle age in days (default: 30)
    KOI_CACHE_DISK_ALERT_PERCENT: Disk alert threshold (default: 80)

Examples:
    # Standard prune with env defaults
    python scripts/prune_bundle_cache.py

    # Dry run to see what would be pruned
    python scripts/prune_bundle_cache.py --dry-run

    # Just show metrics without pruning
    python scripts/prune_bundle_cache.py --metrics-only

    # Override max age to 7 days
    KOI_CACHE_MAX_AGE_DAYS=7 python scripts/prune_bundle_cache.py
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from koi_protocol.core.persistent_cache import (
    PersistentBundleCache,
    RID_LIB_CACHE_AVAILABLE,
    _get_retention_config,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("koi.cache_prune")


def run_metrics(cache: PersistentBundleCache) -> dict:
    """Get and display cache metrics."""
    metrics = cache.get_metrics()

    print("\n" + "=" * 60)
    print("CACHE METRICS")
    print("=" * 60)
    print(f"Timestamp:        {metrics['timestamp']}")
    print(f"Directory:        {cache.directory_path}")
    print(f"Bundle count:     {metrics['bundle_count']}")
    print(f"Disk usage:       {metrics['disk_usage_mb']} MB ({metrics['disk_usage_bytes']} bytes)")
    print(f"Protected count:  {metrics['protected_count']}")
    print(f"Prunable count:   {metrics['prunable_count']}")
    print()
    print("RETENTION CONFIG:")
    print(f"  Max size:       {metrics['config']['max_size_mb']} MB")
    print(f"  Max age:        {metrics['config']['max_age_days']} days")
    print(f"  Disk alert:     {metrics['config']['disk_alert_percent']}%")
    if metrics['disk_percent_used'] is not None:
        print(f"  Disk used:      {metrics['disk_percent_used']}%")

    if metrics['has_alerts']:
        print()
        print("ALERTS:")
        for alert in metrics['alerts']:
            severity_icon = "🔴" if alert['severity'] == 'critical' else "🟡"
            print(f"  {severity_icon} [{alert['severity'].upper()}] {alert['message']}")

    print("=" * 60)

    return metrics


def run_dry_run(cache: PersistentBundleCache) -> dict:
    """Show what would be pruned without actually pruning."""
    config = _get_retention_config()
    bundles = cache.get_bundle_ages()

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=config['max_age_days'])

    print("\n" + "=" * 60)
    print("DRY RUN - What would be pruned")
    print("=" * 60)

    # Age-based pruning
    age_candidates = []
    age_protected = 0
    for rid, ts, is_protected in bundles:
        if ts < cutoff:
            if is_protected:
                age_protected += 1
            else:
                age_candidates.append((rid, ts))

    print(f"\nAge-based pruning (max age: {config['max_age_days']} days):")
    print(f"  Cutoff date:    {cutoff.isoformat()}")
    print(f"  Would prune:    {len(age_candidates)} bundles")
    print(f"  Protected:      {age_protected} (skipped)")

    if age_candidates:
        print("\n  Candidates:")
        for rid, ts in age_candidates[:10]:  # Show first 10
            age_days = (datetime.now(timezone.utc) - ts).days
            print(f"    - {rid[:60]}... (age: {age_days} days)")
        if len(age_candidates) > 10:
            print(f"    ... and {len(age_candidates) - 10} more")

    # Size-based pruning (estimate after age pruning)
    current_size = cache.get_disk_usage_mb()
    print(f"\nSize-based pruning (max size: {config['max_size_mb']} MB):")
    print(f"  Current size:   {current_size:.2f} MB")
    if current_size > config['max_size_mb']:
        print(f"  Status:         Over limit by {current_size - config['max_size_mb']:.2f} MB")
        print(f"  Action:         Would prune oldest bundles until under limit")
    else:
        print(f"  Status:         Within limit ({config['max_size_mb'] - current_size:.2f} MB headroom)")

    print("\n" + "=" * 60)

    return {
        "dry_run": True,
        "age_candidates": len(age_candidates),
        "age_protected": age_protected,
        "current_size_mb": current_size,
        "over_size_limit": current_size > config['max_size_mb'],
    }


def run_prune(cache: PersistentBundleCache) -> dict:
    """Run the full prune cycle."""
    print("\n" + "=" * 60)
    print("RUNNING PRUNE CYCLE")
    print("=" * 60)

    result = cache.prune()

    print(f"\nTimestamp:        {result['timestamp']}")
    print(f"Initial count:    {result['initial_count']} bundles")
    print(f"Final count:      {result['final_count']} bundles")
    print(f"Initial size:     {result['initial_size_mb']:.2f} MB")
    print(f"Final size:       {result['final_size_mb']:.2f} MB")
    print(f"Age pruned:       {result['age_pruned']}")
    print(f"Size pruned:      {result['size_pruned']}")
    print(f"Total pruned:     {result['total_pruned']}")
    print(f"Protected skip:   {result['protected_skipped']}")

    if result['total_pruned'] > 0:
        reclaimed_mb = result['initial_size_mb'] - result['final_size_mb']
        print(f"\nSpace reclaimed:  {reclaimed_mb:.2f} MB")

    print("\n" + "=" * 60)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Prune the persistent bundle cache based on retention policy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Path to cache directory (default: env KOI_CACHE_DIR or project-local .rid_cache)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be pruned without actually pruning"
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Only show metrics, don't prune"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    # Determine cache directory
    import os
    if args.cache_dir:
        cache_dir = args.cache_dir
    else:
        cache_dir = os.getenv("KOI_CACHE_DIR")
        if cache_dir is None:
            cache_dir = Path(__file__).parent.parent / ".rid_cache"
        else:
            cache_dir = Path(cache_dir)

    if not args.json:
        print("=" * 60)
        print("P2b Bundle Cache Prune Script")
        print("=" * 60)
        print(f"Cache directory: {cache_dir}")
        print(f"Mode:            {'dry-run' if args.dry_run else 'metrics-only' if args.metrics_only else 'prune'}")

    # Check rid_lib availability
    if not RID_LIB_CACHE_AVAILABLE:
        logger.error("rid_lib not available - cannot run pruning")
        sys.exit(1)

    # Check cache directory exists
    if not cache_dir.exists():
        logger.warning(f"Cache directory does not exist: {cache_dir}")
        if args.json:
            print(json.dumps({"error": "cache_directory_not_found", "path": str(cache_dir)}))
        sys.exit(0)  # Not an error, just nothing to prune

    # Initialize cache
    cache = PersistentBundleCache(str(cache_dir))
    cache.load_all()

    # Run appropriate mode
    if args.metrics_only:
        result = run_metrics(cache)
    elif args.dry_run:
        result = run_dry_run(cache)
    else:
        result = run_prune(cache)

    # JSON output
    if args.json:
        print(json.dumps(result, default=str))

    # Exit with appropriate code
    if isinstance(result, dict) and result.get("has_alerts"):
        sys.exit(2)  # Non-zero for alerts (useful for monitoring)

    sys.exit(0)


if __name__ == "__main__":
    main()
