"""
KOI Protocol — Node configuration (BlockScience-aligned).

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/config.py

Provides YAML-based configuration that auto-generates ECDSA P-256 keypairs
and stable node RIDs on first load.  Backward-compatible with existing
env-var-based configuration used by the production coordinator.
"""

from __future__ import annotations

import hashlib
import os
import uuid
import logging
from base64 import b64encode
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field, PrivateAttr

from .node import NodeProfile, NodeProvides, NodeType

logger = logging.getLogger(__name__)

# Optional YAML support
try:
    from ruamel.yaml import YAML
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# Optional cryptography support (for keypair generation)
try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


class ServerConfig(BaseModel):
    """HTTP server configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    path: Optional[str] = "/koi-net"

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.path or ''}"


class NodeContact(BaseModel):
    """A known peer for first-contact bootstrap."""
    rid: Optional[str] = None
    url: Optional[str] = None


class KoiNetConfig(BaseModel):
    """KOI-net node configuration."""
    node_name: str
    node_rid: Optional[str] = None
    node_profile: NodeProfile = Field(
        default_factory=lambda: NodeProfile(node_type=NodeType.FULL)
    )

    cache_directory_path: str = ".rid_cache"
    event_queues_path: str = "event_queues.json"
    private_key_pem_path: str = "priv_key.pem"
    polling_interval: int = 30

    first_contact: NodeContact = Field(default_factory=NodeContact)


class EnvConfig(BaseModel):
    """Environment variable references (BlockScience pattern)."""
    priv_key_password: Optional[str] = "PRIV_KEY_PASSWORD"


class NodeConfig(BaseModel):
    """Complete node configuration, loadable from YAML or constructed programmatically.

    Matches BlockScience's NodeConfig structure:
      - server: HTTP listener settings
      - koi_net: Node identity, profile, cache paths, first-contact
      - env: Environment variable names for secrets

    Usage:
        # From YAML file (auto-generates keypair on first load)
        config = NodeConfig.load_from_yaml("config.yaml")

        # Programmatic (for tests or backward compat)
        config = NodeConfig(
            koi_net=KoiNetConfig(node_name="test-node"),
            server=ServerConfig(port=8005),
        )
    """
    server: ServerConfig = Field(default_factory=ServerConfig)
    koi_net: KoiNetConfig
    env: EnvConfig = Field(default_factory=EnvConfig)

    _file_path: str = PrivateAttr(default="config.yaml")

    @classmethod
    def load_from_yaml(
        cls,
        file_path: str = "config.yaml",
        generate_missing: bool = True,
    ) -> "NodeConfig":
        """Load configuration from YAML, generating keypair and node RID if absent.

        On first load with generate_missing=True:
        1. Generates ECDSA P-256 keypair
        2. Derives node_rid from public key hash: orn:koi-net.node:{name}+{hash16}
        3. Persists private key to PEM file
        4. Saves updated config back to YAML

        Args:
            file_path: Path to YAML config file
            generate_missing: If True, generate keypair/RID when not present
        """
        if not _YAML_AVAILABLE:
            raise ImportError(
                "ruamel.yaml is required for YAML config loading. "
                "Install with: pip install ruamel.yaml"
            )

        yaml = YAML()
        config_data = None

        try:
            with open(file_path, "r") as f:
                config_data = yaml.load(f)
        except FileNotFoundError:
            logger.info(f"Config file {file_path} not found, using defaults")

        if config_data:
            config = cls.model_validate(config_data)
        else:
            # Minimal default — caller must provide node_name via env or override
            node_name = os.getenv("KOI_NODE_NAME", "koi-node")
            config = cls(
                koi_net=KoiNetConfig(node_name=node_name),
            )

        config._file_path = file_path

        if generate_missing:
            config._generate_missing_identity()
            config.save_to_yaml()

        return config

    @classmethod
    def from_env(cls, node_name: Optional[str] = None) -> "NodeConfig":
        """Create config from environment variables (backward compat).

        Reads:
          KOI_NODE_NAME, KOI_NODE_ID, KOI_COORDINATOR_PORT,
          KOI_CACHE_DIR, KOI_FIRST_CONTACT_RID, KOI_FIRST_CONTACT_URL,
          KOI_POLL_INTERVAL
        """
        name = node_name or os.getenv("KOI_NODE_NAME", "regen-coordinator")
        port = int(os.getenv("KOI_COORDINATOR_PORT", os.getenv("KOI_PORT", "8000")))
        cache_dir = os.getenv("KOI_CACHE_DIR", ".rid_cache")
        poll_interval = int(os.getenv("KOI_POLL_INTERVAL", "30"))

        # First contact
        fc_rid = os.getenv("KOI_FIRST_CONTACT_RID")
        fc_url = os.getenv("KOI_FIRST_CONTACT_URL")

        # Existing node_id (from Phase 0A identity persistence)
        existing_rid = os.getenv("KOI_NODE_ID")

        node_type_str = os.getenv("KOI_NODE_TYPE", "FULL").upper()
        node_type = NodeType.FULL if node_type_str == "FULL" else NodeType.PARTIAL

        config = cls(
            server=ServerConfig(port=port),
            koi_net=KoiNetConfig(
                node_name=name,
                node_rid=existing_rid,
                node_profile=NodeProfile(
                    node_type=node_type,
                    base_url=(os.getenv('KOI_BASE_URL') or f"http://localhost:{port}/koi-net") if node_type == NodeType.FULL else None,
                ),
                cache_directory_path=cache_dir,
                polling_interval=poll_interval,
                first_contact=NodeContact(rid=fc_rid, url=fc_url),
            ),
        )
        return config

    def _generate_missing_identity(self):
        """Generate keypair and node RID if not already present."""
        if self.koi_net.node_rid:
            return  # Already has identity

        if not _CRYPTO_AVAILABLE:
            # Fallback: generate RID without crypto (same as Phase 0A)
            random_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:16]
            self.koi_net.node_rid = (
                f"orn:koi-net.node:{self.koi_net.node_name}+{random_hash}"
            )
            logger.warning(
                "cryptography not available — generated RID without keypair. "
                "Install cryptography for proper ECDSA identity."
            )
            return

        # Generate ECDSA P-256 keypair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Derive node RID from public key — full 64-char hash matching
        # BlockScience's canonical sha256(base64(DER)) pattern.
        # Uses shared/koi_envelope.py as single source of truth.
        try:
            from shared.koi_envelope import derive_node_rid, public_key_to_b64der
            self.koi_net.node_rid = derive_node_rid(self.koi_net.node_name, public_key)
            self.koi_net.node_profile.public_key = public_key_to_b64der(public_key)
        except ImportError:
            # Fallback if shared module not available
            pub_der = public_key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            pub_b64 = b64encode(pub_der).decode()
            pub_hash = hashlib.sha256(pub_b64.encode()).hexdigest()
            self.koi_net.node_rid = (
                f"orn:koi-net.node:{self.koi_net.node_name}+{pub_hash}"
            )
            self.koi_net.node_profile.public_key = pub_b64

        # Persist private key to PEM
        pem_path = Path(self.koi_net.private_key_pem_path)
        password_env = self.env.priv_key_password
        password = os.getenv(password_env) if password_env else None
        password_bytes = password.encode() if password else None

        encryption = (
            serialization.BestAvailableEncryption(password_bytes)
            if password_bytes
            else serialization.NoEncryption()
        )

        pem_data = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            encryption,
        )

        pem_path.parent.mkdir(parents=True, exist_ok=True)
        pem_path.write_bytes(pem_data)
        logger.info(f"Generated ECDSA P-256 keypair, private key saved to {pem_path}")
        logger.info(f"Node RID: {self.koi_net.node_rid}")

    def save_to_yaml(self):
        """Save current configuration to YAML file."""
        if not _YAML_AVAILABLE:
            logger.warning("ruamel.yaml not available, skipping config save")
            return

        yaml = YAML()
        path = Path(self._file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            yaml.dump(self.model_dump(mode="json"), f)

        logger.info(f"Saved config to {path}")
