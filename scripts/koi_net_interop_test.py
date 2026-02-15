#!/usr/bin/env python3
"""
KOI-net Level 3 Interop Test
Tests: broadcast -> poll -> fetch_manifests -> fetch_bundles with SignedEnvelope
"""

import json
import hashlib
import base64
from pathlib import Path
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

import httpx
from pydantic import BaseModel

# rid-lib is a required dependency (Phase 2)
from rid_lib.ext import Manifest

# Coordinator details
COORDINATOR_URL = "http://localhost:8005"
COORDINATOR_NODE_ID = "orn:koi-net.node:regen-coordinator+c5ca332d9c7a7534788447747d2f8b7e33caca2e44d89d3988d19c3382a1a426"
COORDINATOR_PUBLIC_KEY_DER_B64 = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEusiBV0QP9mGJzhLJAYEmlKIoB7QN88bWF2hqewJrlR/JgW5ztU6fl/NguYAQGt9I7T1WbG3xGjDavVyKsQVBdA=="


class UnsignedEnvelope(BaseModel):
    """Pydantic model for unsigned envelope."""
    payload: dict
    source_node: str
    target_node: str


def load_coordinator_public_key():
    """Load coordinator's public key from DER-b64."""
    der_bytes = base64.b64decode(COORDINATOR_PUBLIC_KEY_DER_B64)
    return serialization.load_der_public_key(der_bytes, default_backend())


def generate_test_node_keypair():
    """Generate a test KOI-net node keypair."""
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()

    # Compute node_id
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_der_b64 = base64.b64encode(public_der).decode()
    pubkey_hash = hashlib.sha256(public_der_b64.encode()).hexdigest()
    node_id = f"orn:koi-net.node:test-interop-node+{pubkey_hash}"

    return private_key, public_key, node_id, public_der_b64


def sign_envelope(payload, source_node, target_node, private_key):
    """Sign envelope using KOI-net compatible serialization."""
    unsigned = UnsignedEnvelope(
        payload=payload,
        source_node=source_node,
        target_node=target_node
    )
    data_to_sign = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

    # Sign with raw r||s format (not DER)
    der_signature = private_key.sign(data_to_sign, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_signature)
    byte_length = 32  # P-256
    raw_signature = r.to_bytes(byte_length, "big") + s.to_bytes(byte_length, "big")

    return {
        "payload": payload,
        "source_node": source_node,
        "target_node": target_node,
        "signature": base64.b64encode(raw_signature).decode()
    }


def verify_envelope(envelope, public_key):
    """Verify envelope using KOI-net compatible serialization."""
    unsigned = UnsignedEnvelope(
        payload=envelope["payload"],
        source_node=envelope["source_node"],
        target_node=envelope["target_node"]
    )
    data_to_verify = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

    # Decode raw r||s signature
    raw_sig = base64.b64decode(envelope["signature"])
    byte_length = 32
    r = int.from_bytes(raw_sig[:byte_length], "big")
    s = int.from_bytes(raw_sig[byte_length:], "big")
    der_signature = encode_dss_signature(r, s)

    public_key.verify(der_signature, data_to_verify, ec.ECDSA(hashes.SHA256()))
    return True


def run_interop_test():
    print("=" * 60)
    print("KOI-net Level 3 Interop Test")
    print("=" * 60)

    # Generate test node keypair
    print("\n[1] Generating test node keypair...")
    private_key, public_key, test_node_id, public_der_b64 = generate_test_node_keypair()
    print(f"    Test node_id: {test_node_id[:60]}...")

    # Load coordinator public key
    print("\n[2] Loading coordinator public key...")
    coordinator_pubkey = load_coordinator_public_key()
    print(f"    Coordinator: {COORDINATOR_NODE_ID[:60]}...")

    # Export test node public key PEM for adding to coordinator
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

    # Add test node to coordinator's public_keys.json
    print("\n[3] Adding test node to coordinator public_keys.json...")
    keys_path = Path("/opt/projects/koi-sensors/keys/public_keys.json")
    with open(keys_path) as f:
        keys = json.load(f)
    keys[test_node_id] = public_pem
    with open(keys_path, "w") as f:
        json.dump(keys, f, indent=2)
    print(f"    Added. Total keys: {len(keys)}")

    # Restart coordinator to reload keys
    print("\n[3b] Restarting coordinator to reload keys...")
    import subprocess
    subprocess.run(["sudo", "systemctl", "restart", "koi-coordinator"], check=True)
    import time
    time.sleep(3)
    print("    Coordinator restarted")

    # Test 1: Signed poll request
    print("\n[4] Testing signed /koi-net/events/poll...")
    poll_payload = {"type": "poll_events", "limit": 3}
    signed_poll = sign_envelope(poll_payload, test_node_id, COORDINATOR_NODE_ID, private_key)

    response = httpx.post(f"{COORDINATOR_URL}/koi-net/events/poll", json=signed_poll)
    print(f"    Status: {response.status_code}")

    if response.status_code != 200:
        print(f"    ERROR: {response.json()}")
        return False

    result = response.json()
    if "signature" not in result:
        print("    ERROR: Response not signed")
        return False

    # Verify response signature
    try:
        verify_envelope(result, coordinator_pubkey)
        print("    Response signature verified!")
    except Exception as e:
        print(f"    Signature verification failed: {e}")
        return False

    events = result["payload"].get("events", [])
    print(f"    Events received: {len(events)}")

    if not events:
        print("    No events available, skipping fetch tests")
        print("\n" + "=" * 60)
        print("Level 3 Interop Test PASSED (poll only)")
        print("=" * 60)
        return True

    test_rid = events[0]["rid"]

    # Test 2: Fetch manifests
    print(f"\n[5] Testing /koi-net/manifests/fetch for: {test_rid[:50]}...")
    fetch_payload = {"type": "fetch_manifests", "rids": [test_rid]}
    signed_fetch = sign_envelope(fetch_payload, test_node_id, COORDINATOR_NODE_ID, private_key)

    response = httpx.post(f"{COORDINATOR_URL}/koi-net/manifests/fetch", json=signed_fetch)
    print(f"    Status: {response.status_code}")

    if response.status_code != 200:
        print(f"    ERROR: {response.json()}")
        return False

    result = response.json()
    if "signature" in result:
        verify_envelope(result, coordinator_pubkey)
        print("    Response signature verified!")

    manifests = result["payload"].get("manifests", [])
    print(f"    Manifests received: {len(manifests)}")

    if manifests:
        m = manifests[0]
        print(f"    Manifest timestamp: {m['timestamp']}")
        if m["timestamp"].endswith("Z"):
            print("    Timestamp has Z suffix!")
        else:
            print(f"    WARNING: Timestamp should end with Z")

    # Test 3: Fetch bundles
    print(f"\n[6] Testing /koi-net/bundles/fetch...")
    fetch_payload = {"type": "fetch_bundles", "rids": [test_rid]}
    signed_fetch = sign_envelope(fetch_payload, test_node_id, COORDINATOR_NODE_ID, private_key)

    response = httpx.post(f"{COORDINATOR_URL}/koi-net/bundles/fetch", json=signed_fetch)
    print(f"    Status: {response.status_code}")

    if response.status_code != 200:
        print(f"    ERROR: {response.json()}")
        return False

    result = response.json()
    if "signature" in result:
        verify_envelope(result, coordinator_pubkey)
        print("    Response signature verified!")

    bundles = result["payload"].get("bundles", [])
    print(f"    Bundles received: {len(bundles)}")

    # Test 4: Verify JCS hash parity
    if bundles:
        print("\n[7] Verifying JCS hash parity...")
        b = bundles[0]
        wire_manifest = b["manifest"]
        contents = b["contents"]

        recomputed = Manifest.generate(wire_manifest["rid"], contents)

        print(f"    Wire sha256_hash:   {wire_manifest['sha256_hash'][:40]}...")
        print(f"    rid-lib recomputed: {recomputed.sha256_hash[:40]}...")

        if wire_manifest["sha256_hash"] == recomputed.sha256_hash:
            print("    JCS hash parity confirmed!")
        else:
            print("    JCS hash MISMATCH!")
            return False

    print("\n" + "=" * 60)
    print("Level 3 Interop Test PASSED")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import sys
    success = run_interop_test()
    sys.exit(0 if success else 1)
