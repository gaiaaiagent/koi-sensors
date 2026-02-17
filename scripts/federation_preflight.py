#!/usr/bin/env python3
"""
Federation Preflight — Hard Gate

ALL checks must pass before deploying to production.
Exits 0 on success, 1 on hard failure, 2 on soft warning.

Usage:
    python scripts/federation_preflight.py
    python scripts/federation_preflight.py --regen-url http://202.61.196.119:8005/koi-net
    python scripts/federation_preflight.py --skip-inbound  # skip inbound reachability check
"""

import argparse
import hashlib
import json
import os
import sys
import time
from base64 import b64encode
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

try:
    import httpx
except ImportError:
    print("FATAL: httpx not installed. pip install httpx")
    sys.exit(1)

try:
    from shared.koi_envelope import (
        derive_node_rid,
        generate_and_save_keypair,
        node_rid_matches_public_key,
        public_key_from_b64der,
        public_key_to_b64der,
        sign_envelope,
        load_private_key,
    )
except ImportError as e:
    print(f"FATAL: Cannot import shared.koi_envelope: {e}")
    sys.exit(1)


# Defaults
OCTO_URL = "http://45.132.245.30:8351/koi-net"
OCTO_RID = "orn:koi-net.node:octo-salish-sea+50a3c9eac05c807f"
REGEN_URL = "http://202.61.196.119:8005/koi-net"
TIMEOUT = 15.0


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str = "", warn: bool = False):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.warn = warn

    def __str__(self):
        icon = "✓" if self.passed else ("⚠" if self.warn else "✗")
        msg = f"  {icon} {self.name}"
        if self.detail:
            msg += f" — {self.detail}"
        return msg


def check_outbound_to_octo(octo_url: str, octo_rid: str) -> CheckResult:
    """Check 1: Regen can reach Octo's /koi-net/health."""
    name = "Outbound: Regen → Octo /koi-net/health"
    try:
        resp = httpx.get(f"{octo_url}/health", timeout=TIMEOUT)
        if resp.status_code != 200:
            return CheckResult(name, False, f"HTTP {resp.status_code}")

        data = resp.json()
        node = data.get("node", {})
        pub_key = node.get("public_key")
        node_rid = node.get("node_rid")

        if not pub_key:
            return CheckResult(name, False, "Missing node.public_key in response")
        if not node_rid:
            return CheckResult(name, False, "Missing node.node_rid in response")

        # Verify key matches RID
        try:
            key_obj = public_key_from_b64der(pub_key)
            if not node_rid_matches_public_key(node_rid, key_obj):
                return CheckResult(name, False,
                    f"node_rid {node_rid} does not match public_key")
        except Exception as e:
            return CheckResult(name, False, f"Key verification error: {e}")

        return CheckResult(name, True,
            f"node_rid={node_rid[:40]}..., public_key present")
    except httpx.TimeoutException:
        return CheckResult(name, False, f"Timeout after {TIMEOUT}s")
    except Exception as e:
        return CheckResult(name, False, str(e))


def check_inbound_reachability(regen_url: str) -> CheckResult:
    """Check 2: Regen's /koi-net/health is reachable from outside."""
    name = "Inbound: Regen /koi-net/health reachable"
    try:
        resp = httpx.get(f"{regen_url}/health", timeout=TIMEOUT)
        if resp.status_code != 200:
            return CheckResult(name, False, f"HTTP {resp.status_code}")

        data = resp.json()
        node = data.get("node", {})
        node_rid = node.get("node_rid")
        if not node_rid:
            return CheckResult(name, False, "Missing node.node_rid")

        return CheckResult(name, True, f"node_rid={node_rid[:40]}...")
    except httpx.TimeoutException:
        return CheckResult(name, False,
            f"BLOCKED: Timeout after {TIMEOUT}s — "
            f"check firewall rules for {regen_url}")
    except Exception as e:
        return CheckResult(name, False, f"BLOCKED: {e}")


def check_identity_consistency(regen_url: str) -> CheckResult:
    """Check 3: Local keypair derivation matches running node's response."""
    name = "Identity: Local derivation matches live node"
    cache_dir = os.getenv("KOI_CACHE_DIR", ".rid_cache")
    key_path = os.path.join(cache_dir, "node_private_key.pem")
    node_name = os.getenv("KOI_NODE_NAME", "regen-coordinator")

    if not os.path.exists(key_path):
        return CheckResult(name, True,
            "No local key yet (will be generated on first startup)", warn=True)

    try:
        password = os.getenv("KOI_PRIVATE_KEY_PASSWORD")
        priv = load_private_key(key_path, password)
        if not priv:
            return CheckResult(name, False, f"Cannot load key from {key_path}")

        pub = priv.public_key()
        local_rid = derive_node_rid(node_name, pub)

        resp = httpx.get(f"{regen_url}/health", timeout=TIMEOUT)
        if resp.status_code != 200:
            return CheckResult(name, True,
                f"Cannot reach {regen_url}/health (new deploy?)", warn=True)

        live_rid = resp.json().get("node", {}).get("node_rid")
        if not live_rid:
            return CheckResult(name, True,
                "Live node missing node_rid (pre-Phase 5?)", warn=True)

        if local_rid == live_rid:
            return CheckResult(name, True, f"Match: {local_rid[:40]}...")
        else:
            return CheckResult(name, False,
                f"DRIFT: local={local_rid[:30]}... live={live_rid[:30]}...")
    except Exception as e:
        return CheckResult(name, True, f"Skipped: {e}", warn=True)


def check_signed_handshake(octo_url: str, octo_rid: str) -> CheckResult:
    """Check 4: Signed handshake dry-run against Octo."""
    name = "Handshake: Signed request accepted by Octo"
    cache_dir = os.getenv("KOI_CACHE_DIR", ".rid_cache")
    key_path = os.path.join(cache_dir, "node_private_key.pem")
    node_name = os.getenv("KOI_NODE_NAME", "regen-coordinator")

    if not os.path.exists(key_path):
        return CheckResult(name, True,
            "No local key yet — skipping (will test after first startup)", warn=True)

    try:
        password = os.getenv("KOI_PRIVATE_KEY_PASSWORD")
        priv = load_private_key(key_path, password)
        if not priv:
            return CheckResult(name, False, f"Cannot load key from {key_path}")

        pub = priv.public_key()
        our_rid = derive_node_rid(node_name, pub)
        pub_b64 = public_key_to_b64der(pub)

        handshake_payload = {
            "type": "events_payload",
            "events": [
                {"rid": our_rid, "event_type": "FORGET"},
                {
                    "rid": our_rid,
                    "event_type": "NEW",
                    "contents": {
                        "base_url": os.getenv("KOI_BASE_URL", "http://202.61.196.119:8005/koi-net"),
                        "node_type": "FULL",
                        "provides": {"event": [], "state": []},
                        "public_key": pub_b64,
                    },
                },
            ],
        }

        signed = sign_envelope(handshake_payload, our_rid, octo_rid, priv)
        resp = httpx.post(
            f"{octo_url}/handshake", json=signed, timeout=TIMEOUT
        )

        if resp.status_code == 200:
            # Extract edge_rid from response for approval check
            result = resp.json()
            inner = result.get("payload", result)
            edge_rid = inner.get("edge_rid")
            return CheckResult(name, True,
                f"Handshake accepted, edge_rid={edge_rid or 'none'}")
        else:
            return CheckResult(name, False,
                f"HTTP {resp.status_code}: {resp.text[:200]}")
    except httpx.TimeoutException:
        return CheckResult(name, False, f"Timeout after {TIMEOUT}s")
    except Exception as e:
        return CheckResult(name, False, str(e))


def check_signed_edge_approve(octo_url: str, octo_rid: str) -> CheckResult:
    """Check 5: Signed /edges/approve dry-run against Octo."""
    name = "Approve: Signed edge approval accepted by Octo"
    cache_dir = os.getenv("KOI_CACHE_DIR", ".rid_cache")
    key_path = os.path.join(cache_dir, "node_private_key.pem")
    node_name = os.getenv("KOI_NODE_NAME", "regen-coordinator")

    if not os.path.exists(key_path):
        return CheckResult(name, True, "No local key — skipping", warn=True)

    try:
        password = os.getenv("KOI_PRIVATE_KEY_PASSWORD")
        priv = load_private_key(key_path, password)
        if not priv:
            return CheckResult(name, False, f"Cannot load key from {key_path}")

        pub = priv.public_key()
        our_rid = derive_node_rid(node_name, pub)
        pub_b64 = public_key_to_b64der(pub)

        # First do a handshake to get an edge_rid
        handshake_payload = {
            "type": "events_payload",
            "events": [
                {"rid": our_rid, "event_type": "FORGET"},
                {
                    "rid": our_rid,
                    "event_type": "NEW",
                    "contents": {
                        "base_url": os.getenv("KOI_BASE_URL", "http://202.61.196.119:8005/koi-net"),
                        "node_type": "FULL",
                        "provides": {"event": [], "state": []},
                        "public_key": pub_b64,
                    },
                },
            ],
        }

        signed_hs = sign_envelope(handshake_payload, our_rid, octo_rid, priv)
        hs_resp = httpx.post(
            f"{octo_url}/handshake", json=signed_hs, timeout=TIMEOUT
        )

        if hs_resp.status_code != 200:
            return CheckResult(name, True,
                f"Handshake failed ({hs_resp.status_code}), cannot test approval", warn=True)

        hs_result = hs_resp.json()
        hs_inner = hs_result.get("payload", hs_result)
        edge_rid = hs_inner.get("edge_rid")
        if not edge_rid:
            return CheckResult(name, True,
                "Handshake returned no edge_rid, cannot test approval", warn=True)

        # Now send signed edge approval
        approve_payload = {
            "type": "edge_approve",
            "edge_rid": edge_rid,
            "node_rid": our_rid,
        }
        signed_approve = sign_envelope(approve_payload, our_rid, octo_rid, priv)
        resp = httpx.post(
            f"{octo_url}/edges/approve", json=signed_approve, timeout=TIMEOUT
        )

        if resp.status_code == 200:
            return CheckResult(name, True, f"Edge {edge_rid} approved")
        else:
            return CheckResult(name, False,
                f"HTTP {resp.status_code}: {resp.text[:200]}")
    except httpx.TimeoutException:
        return CheckResult(name, False, f"Timeout after {TIMEOUT}s")
    except Exception as e:
        return CheckResult(name, False, str(e))


def check_signed_poll(octo_url: str, octo_rid: str) -> CheckResult:
    """Check 6: Signed /koi-net/events/poll roundtrip."""
    name = "Poll: Signed poll request accepted by Octo"
    cache_dir = os.getenv("KOI_CACHE_DIR", ".rid_cache")
    key_path = os.path.join(cache_dir, "node_private_key.pem")
    node_name = os.getenv("KOI_NODE_NAME", "regen-coordinator")

    if not os.path.exists(key_path):
        return CheckResult(name, True, "No local key — skipping", warn=True)

    try:
        password = os.getenv("KOI_PRIVATE_KEY_PASSWORD")
        priv = load_private_key(key_path, password)
        if not priv:
            return CheckResult(name, False, f"Cannot load key from {key_path}")

        pub = priv.public_key()
        our_rid = derive_node_rid(node_name, pub)

        poll_payload = {"type": "poll_events", "limit": 1}
        signed = sign_envelope(poll_payload, our_rid, octo_rid, priv)
        resp = httpx.post(
            f"{octo_url}/events/poll", json=signed, timeout=TIMEOUT
        )

        if resp.status_code == 200:
            return CheckResult(name, True, "Poll accepted")
        else:
            return CheckResult(name, False,
                f"HTTP {resp.status_code}: {resp.text[:200]}")
    except httpx.TimeoutException:
        return CheckResult(name, False, f"Timeout after {TIMEOUT}s")
    except Exception as e:
        return CheckResult(name, False, str(e))


def main():
    parser = argparse.ArgumentParser(description="Federation preflight checks")
    parser.add_argument("--octo-url", default=OCTO_URL)
    parser.add_argument("--octo-rid", default=OCTO_RID)
    parser.add_argument("--regen-url", default=REGEN_URL)
    parser.add_argument("--skip-inbound", action="store_true",
        help="Skip inbound reachability check")
    parser.add_argument("--skip-handshake", action="store_true",
        help="Skip live handshake test")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("Federation Preflight — Phase 5")
    print(f"{'='*60}")
    print(f"  Octo:  {args.octo_url}")
    print(f"  Regen: {args.regen_url}")
    print()

    results = []

    # Check 1: Outbound connectivity
    results.append(check_outbound_to_octo(args.octo_url, args.octo_rid))

    # Check 2: Inbound reachability
    if not args.skip_inbound:
        results.append(check_inbound_reachability(args.regen_url))

    # Check 3: Identity consistency
    results.append(check_identity_consistency(args.regen_url))

    # Check 4: Signed handshake
    if not args.skip_handshake:
        results.append(check_signed_handshake(args.octo_url, args.octo_rid))

    # Check 5: Signed edge approval
    if not args.skip_handshake:
        results.append(check_signed_edge_approve(args.octo_url, args.octo_rid))

    # Check 6: Signed poll
    if not args.skip_handshake:
        results.append(check_signed_poll(args.octo_url, args.octo_rid))

    # Print results
    print("Results:")
    for r in results:
        print(r)

    hard_failures = [r for r in results if not r.passed and not r.warn]
    warnings = [r for r in results if r.warn]
    passes = [r for r in results if r.passed and not r.warn]

    print(f"\n  {len(passes)} passed, {len(warnings)} warnings, {len(hard_failures)} failures")

    if hard_failures:
        print("\n  ✗ DEPLOY BLOCKED — fix failures above before proceeding")
        sys.exit(1)
    elif warnings:
        print("\n  ⚠ DEPLOY AT YOUR OWN RISK — warnings above may cause issues")
        sys.exit(2)
    else:
        print("\n  ✓ ALL CHECKS PASSED — safe to deploy")
        sys.exit(0)


if __name__ == "__main__":
    main()
