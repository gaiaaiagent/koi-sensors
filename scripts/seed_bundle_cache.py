#!/usr/bin/env python3
"""
P2a Bundle Cache Seed Script

Populates the persistent bundle cache from existing sources:
- coordinator_event_queue.json (primary)

BACKFILL SCOPE LIMITATION:
    This script seeds from coordinator_event_queue.json, which only contains
    RECENT PENDING events (those not yet confirmed by all subscribers).
    It does NOT contain historical events that have been fully delivered.

    For full historical backfill from Postgres (koi_* tables), you would need
    a separate script that queries the database directly. This is a separate
    step not covered by P2a.

Usage:
    python scripts/seed_bundle_cache.py [--cache-dir PATH] [--event-queue PATH]
    python scripts/seed_bundle_cache.py --help

Examples:
    # Use defaults (project-local paths)
    python scripts/seed_bundle_cache.py

    # Custom paths
    python scripts/seed_bundle_cache.py --cache-dir /opt/projects/koi-sensors/.rid_cache \
        --event-queue /opt/projects/koi-sensors/koi_protocol/coordinator/coordinator_event_queue.json

    # Dry run to see what would be seeded
    python scripts/seed_bundle_cache.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from koi_protocol.core.bundle_system import Bundle, Manifest
from koi_protocol.core.persistent_cache import (
    PersistentBundleCache,
    RID_LIB_CACHE_AVAILABLE,
)


def load_bundles_from_event_queue(event_queue_path: Path) -> list[Bundle]:
    """Load bundles from coordinator event queue JSON."""
    if not event_queue_path.exists():
        print(f"Event queue not found: {event_queue_path}")
        return []

    with open(event_queue_path) as f:
        data = json.load(f)

    bundles = []
    seen_rids = set()  # Deduplicate by RID (keep latest)

    events = data.get("events", [])
    print(f"Found {len(events)} events in queue")

    # Process in reverse order to keep latest version of each RID
    for queued_event in reversed(events):
        event = queued_event.get("event", {})
        event_type = event.get("event_type")

        # Only process NEW and UPDATE events with bundles
        if event_type not in ["NEW", "UPDATE"]:
            continue

        bundle_data = event.get("bundle")
        if not bundle_data:
            continue

        rid = bundle_data.get("rid")
        if not rid or rid in seen_rids:
            continue

        seen_rids.add(rid)

        try:
            manifest_data = bundle_data.get("manifest", {})
            manifest = Manifest.from_dict(manifest_data)
            bundle = Bundle(
                rid=rid,
                manifest=manifest,
                contents=bundle_data.get("contents", {})
            )
            bundles.append(bundle)
        except Exception as e:
            print(f"  Warning: Failed to parse bundle {rid}: {e}")

    # Reverse to get chronological order (oldest first)
    bundles.reverse()
    return bundles


def seed_cache(cache_dir: Path, bundles: list[Bundle]) -> int:
    """Write bundles to persistent cache."""
    if not RID_LIB_CACHE_AVAILABLE:
        print("ERROR: rid_lib not available - cannot seed cache")
        return 0

    cache = PersistentBundleCache(str(cache_dir))
    written = 0

    for bundle in bundles:
        try:
            cache.write(bundle)
            written += 1
            print(f"  Seeded: {bundle.rid[:60]}...")
        except Exception as e:
            print(f"  ERROR writing {bundle.rid}: {e}")

    return written


def main():
    parser = argparse.ArgumentParser(
        description="Seed the persistent bundle cache from existing sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).parent.parent / ".rid_cache",
        help="Path to cache directory (default: project-local .rid_cache)"
    )
    parser.add_argument(
        "--event-queue",
        type=Path,
        default=Path(__file__).parent.parent / "koi_protocol/coordinator/coordinator_event_queue.json",
        help="Path to coordinator event queue JSON"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be seeded without writing"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("P2a Bundle Cache Seed Script")
    print("=" * 60)
    print(f"Cache directory: {args.cache_dir}")
    print(f"Event queue: {args.event_queue}")
    print(f"Dry run: {args.dry_run}")
    print()

    if not RID_LIB_CACHE_AVAILABLE:
        print("ERROR: rid_lib not available - cannot seed cache")
        sys.exit(1)

    # Load bundles from event queue
    print(f"[1] Loading bundles from {args.event_queue.name}...")
    bundles = load_bundles_from_event_queue(args.event_queue)
    print(f"    Found {len(bundles)} unique bundles")

    if not bundles:
        print("\nNo bundles to seed")
        sys.exit(0)

    if args.dry_run:
        print("\n[DRY RUN] Would seed the following bundles:")
        for bundle in bundles:
            print(f"  - {bundle.rid}")
        print(f"\nTotal: {len(bundles)} bundles")
        sys.exit(0)

    # Seed cache
    print(f"\n[2] Writing bundles to cache...")
    written = seed_cache(args.cache_dir, bundles)

    print()
    print("=" * 60)
    print(f"Seeded {written}/{len(bundles)} bundles to {args.cache_dir}")
    print("=" * 60)

    # Verify by reading back
    print(f"\n[3] Verifying cache...")
    cache = PersistentBundleCache(str(args.cache_dir))
    cache.load_all()
    stats = cache.stats()
    print(f"    Cache size: {stats['memory_size']} bundles")
    print(f"    RIDs in cache: {len(cache.list_rids())}")


if __name__ == "__main__":
    main()
