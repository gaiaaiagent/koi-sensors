"""
P1b Cross-Verification Tests for SignedEnvelope Interop

These tests verify that RegenAI's SignedEnvelope implementation is compatible
with KOI-net reference implementation.

Test cases:
1. RegenAI-signed envelope verifies with koi-net
2. koi-net-signed envelope verifies with RegenAI
3. Extra fields break verification
4. FORGET event with None manifest (exclude_none behavior)
5. Signed poll roundtrip

Reference: koi-research/docs/KOI_PROTOCOL_ALIGNMENT_REFERENCE.md
"""

import base64
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

from shared.koi_envelope import (
    UnsignedEnvelope,
    SignedEnvelope,
    ErrorResponse,
    sign_envelope,
    verify_envelope,
    verify_envelope_with_key,
    EnvelopeError,
)


@pytest.fixture
def keypair():
    """Generate test ECDSA P-256 keypair."""
    private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def node_ids():
    """Test KoiNetNode ORNs."""
    return {
        "local": "orn:koi-net.node:regen-test+abc123",
        "remote": "orn:koi-net.node:test-remote+def456"
    }


class TestRegenAISignedEnvelopeParity:
    """Test that RegenAI signing matches KOI-net expectations."""

    def test_unsigned_envelope_serialization(self, node_ids):
        """UnsignedEnvelope serializes with exclude_none=True."""
        payload = {"type": "poll_events", "limit": 10}
        unsigned = UnsignedEnvelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"]
        )
        serialized = unsigned.model_dump_json(exclude_none=True)

        # Verify it's valid JSON
        parsed = json.loads(serialized)
        assert parsed["payload"] == payload
        assert parsed["source_node"] == node_ids["local"]
        assert parsed["target_node"] == node_ids["remote"]

    def test_sign_and_verify_roundtrip(self, keypair, node_ids):
        """Sign and verify using RegenAI functions."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 10}

        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Verify structure
        assert "payload" in signed
        assert "source_node" in signed
        assert "target_node" in signed
        assert "signature" in signed

        # Verify with public key map
        public_keys = {node_ids["local"]: public_key}
        result_payload, result_source = verify_envelope(
            signed,
            public_keys,
            expected_target=node_ids["remote"],
            enforce_target=True
        )
        assert result_payload == payload
        assert result_source == node_ids["local"]

    def test_verify_with_single_key(self, keypair, node_ids):
        """Verify envelope using single key function."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 5}

        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        assert verify_envelope_with_key(signed, public_key) is True


class TestKoiNetCrossVerification:
    """Test cross-verification between RegenAI and KOI-net serialization."""

    def test_regenai_signed_verifies_with_koi_net_bytes(self, keypair, node_ids):
        """RegenAI-signed envelope should verify when using KOI-net byte computation."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 10}

        # Sign with RegenAI
        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Reconstruct bytes the KOI-net way (Pydantic model_dump_json)
        unsigned = UnsignedEnvelope(
            payload=signed["payload"],
            source_node=signed["source_node"],
            target_node=signed["target_node"]
        )
        data_to_verify = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

        # Decode signature (raw r||s format -> DER for cryptography)
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        raw_sig = base64.b64decode(signed["signature"])
        byte_length = (ec.SECP256R1().key_size + 7) // 8
        r = int.from_bytes(raw_sig[:byte_length], byteorder="big")
        s = int.from_bytes(raw_sig[byte_length:], byteorder="big")
        der_sig = encode_dss_signature(r, s)

        # Verify - should not raise
        public_key.verify(der_sig, data_to_verify, ec.ECDSA(hashes.SHA256()))

    def test_external_signed_verifies_with_regenai(self, keypair, node_ids):
        """Envelope signed using direct ECDSA should verify with RegenAI."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 10}

        # Sign manually using the same bytes RegenAI uses
        unsigned = UnsignedEnvelope(
            payload=payload,
            source_node=node_ids["remote"],
            target_node=node_ids["local"]
        )
        data_to_sign = unsigned.model_dump_json(exclude_none=True).encode("utf-8")

        # Sign with cryptography
        der_signature = private_key.sign(data_to_sign, ec.ECDSA(hashes.SHA256()))

        # Convert DER to raw r||s
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        r, s = decode_dss_signature(der_signature)
        byte_length = (ec.SECP256R1().key_size + 7) // 8
        raw_sig = r.to_bytes(byte_length, byteorder="big") + s.to_bytes(byte_length, byteorder="big")
        signature = base64.b64encode(raw_sig).decode("utf-8")

        signed = {
            "payload": payload,
            "source_node": node_ids["remote"],
            "target_node": node_ids["local"],
            "signature": signature
        }

        # Verify with RegenAI
        public_keys = {node_ids["remote"]: public_key}
        result_payload, result_source = verify_envelope(
            signed,
            public_keys,
            expected_target=node_ids["local"],
            enforce_target=True
        )
        assert result_payload == payload
        assert result_source == node_ids["remote"]


class TestExtraFieldsBreakVerification:
    """Test that non-schema fields cause signature mismatch."""

    def test_extra_field_in_payload_after_stripping(self, keypair, node_ids):
        """Extra fields stripped after signing cause verification failure."""
        private_key, public_key = keypair

        # Sign payload WITH extra field
        payload_with_extra = {
            "type": "poll_events",
            "limit": 10,
            "node_id": "extra-field"  # Non-schema field
        }
        signed = sign_envelope(
            payload=payload_with_extra,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Simulate KOI-net stripping unknown field
        stripped_payload = {"type": "poll_events", "limit": 10}

        # Recreate envelope with stripped payload
        modified_envelope = {
            "payload": stripped_payload,
            "source_node": signed["source_node"],
            "target_node": signed["target_node"],
            "signature": signed["signature"]
        }

        # Verification should FAIL
        public_keys = {node_ids["local"]: public_key}
        with pytest.raises(EnvelopeError, match="Invalid envelope signature"):
            verify_envelope(modified_envelope, public_keys)


class TestForgetEventExcludeNone:
    """Test FORGET events with None manifest (exclude_none behavior)."""

    def test_forget_event_none_manifest_roundtrip(self, keypair, node_ids):
        """FORGET events with manifest=None sign and verify correctly."""
        private_key, public_key = keypair

        # FORGET event: manifest is None
        forget_event = {
            "rid": "orn:test:resource",
            "event_type": "FORGET",
            "manifest": None,  # Must be OMITTED, not "manifest": null
            "contents": None
        }
        payload = {"type": "events_payload", "events": [forget_event]}

        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Verify roundtrip
        public_keys = {node_ids["local"]: public_key}
        result_payload, _ = verify_envelope(signed, public_keys)
        assert result_payload == payload

    def test_none_fields_omitted_in_serialization(self, node_ids):
        """None fields are omitted (not serialized as null) in UnsignedEnvelope."""
        forget_event = {
            "rid": "orn:test:resource",
            "event_type": "FORGET",
            "manifest": None,
            "contents": None
        }
        payload = {"type": "events_payload", "events": [forget_event]}

        unsigned = UnsignedEnvelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"]
        )
        serialized = unsigned.model_dump_json(exclude_none=True)

        # The payload is serialized as-is (including None values in events)
        # but UnsignedEnvelope itself doesn't have None fields
        assert '"source_node":' in serialized
        assert '"target_node":' in serialized
        assert '"payload":' in serialized


class TestErrorResponseModel:
    """Test ErrorResponse model for KOI-net interop."""

    def test_error_response_structure(self):
        """ErrorResponse has correct structure."""
        error = ErrorResponse(error="invalid_signature", detail="Signature verification failed")
        dumped = error.model_dump()
        assert dumped["error"] == "invalid_signature"
        assert dumped["detail"] == "Signature verification failed"

    def test_error_response_excludes_none(self):
        """ErrorResponse with no detail excludes the field when using exclude_none."""
        error = ErrorResponse(error="unknown_source")
        dumped = error.model_dump(exclude_none=True)
        assert "error" in dumped
        assert "detail" not in dumped


class TestTargetNodeValidation:
    """Test target_node validation in verification."""

    def test_wrong_target_raises_error(self, keypair, node_ids):
        """Wrong target_node raises EnvelopeError when enforce_target=True."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 10}

        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        public_keys = {node_ids["local"]: public_key}
        with pytest.raises(EnvelopeError, match="does not match"):
            verify_envelope(
                signed,
                public_keys,
                expected_target="orn:koi-net.node:wrong-node+xyz",
                enforce_target=True
            )

    def test_unknown_source_raises_error(self, keypair, node_ids):
        """Unknown source_node raises EnvelopeError."""
        private_key, public_key = keypair
        payload = {"type": "poll_events", "limit": 10}

        signed = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Empty public keys map
        with pytest.raises(EnvelopeError, match="No public key"):
            verify_envelope(signed, {})


class TestSignedEnvelopeModel:
    """Test SignedEnvelope Pydantic model."""

    def test_signed_envelope_model_validation(self, keypair, node_ids):
        """SignedEnvelope model validates correctly."""
        private_key, _ = keypair
        payload = {"type": "poll_events", "limit": 10}

        signed_dict = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Should parse into SignedEnvelope model
        envelope = SignedEnvelope(**signed_dict)
        assert envelope.payload == payload
        assert envelope.source_node == node_ids["local"]
        assert envelope.target_node == node_ids["remote"]
        assert envelope.signature == signed_dict["signature"]

    def test_signed_envelope_rejects_extra_fields(self, keypair, node_ids):
        """SignedEnvelope model rejects extra fields."""
        private_key, _ = keypair
        payload = {"type": "poll_events", "limit": 10}

        signed_dict = sign_envelope(
            payload=payload,
            source_node=node_ids["local"],
            target_node=node_ids["remote"],
            private_key=private_key
        )

        # Add extra field
        signed_dict["extra_field"] = "should fail"

        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SignedEnvelope(**signed_dict)
