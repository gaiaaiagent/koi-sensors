"""
KOI Protocol — Node identity models (BlockScience-aligned).

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/protocol/node.py

These Pydantic models match BlockScience's NodeProfile schema so that
Regen's coordinator can serialize/deserialize NodeProfile Bundles that
BlockScience nodes understand.
"""

from enum import StrEnum
from typing import List, Optional

from pydantic import BaseModel


class NodeType(StrEnum):
    """KOI-net node type."""
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class NodeProvides(BaseModel):
    """Declares which RID types a node provides via events and state.

    BlockScience uses rid_lib.RIDType here.  We use plain strings for now
    (e.g. "orn:koi-net.knowledge.*") since Regen hasn't migrated to
    rid-lib RIDType subclasses yet (Phase 2 scope).
    """
    event: List[str] = []
    state: List[str] = []


class NodeProfile(BaseModel):
    """A node's public profile, stored as Bundle contents.

    Matches BlockScience's NodeProfile exactly:
      - base_url: HTTP root (FULL nodes only, None for PARTIAL)
      - node_type: FULL or PARTIAL
      - provides: which RID types this node offers
      - public_key: base64-encoded DER public key (ECDSA P-256)

    The NodeProfile is the *contents* of a Bundle keyed by the node's RID
    (e.g. orn:koi-net.node:regen-coordinator+abc123).
    """
    base_url: Optional[str] = None
    node_type: NodeType
    provides: NodeProvides = NodeProvides()
    public_key: Optional[str] = None
