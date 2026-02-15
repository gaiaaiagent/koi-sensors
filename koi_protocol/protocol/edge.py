"""
KOI Protocol — Edge models for peer relationships (BlockScience-aligned).

Reference: koi-research/sources/blockscience/koi-net/src/koi_net/protocol/edge.py

An EdgeProfile describes a directional relationship between two nodes,
specifying how events flow (WEBHOOK or POLL) and which RID types are
exchanged.  Edges go through PROPOSED → APPROVED lifecycle during handshake.
"""

import hashlib
from enum import StrEnum
from typing import List

from pydantic import BaseModel


class EdgeType(StrEnum):
    """How events are delivered along this edge."""
    WEBHOOK = "WEBHOOK"
    POLL = "POLL"


class EdgeStatus(StrEnum):
    """Lifecycle status of a peer edge."""
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"


class EdgeProfile(BaseModel):
    """Describes a directional edge between two KOI-net nodes.

    Matches BlockScience's EdgeProfile:
      - source: initiating node RID (str, e.g. "orn:koi-net.node:...")
      - target: receiving node RID
      - edge_type: WEBHOOK or POLL
      - status: PROPOSED or APPROVED
      - rid_types: which RID type patterns flow through this edge
    """
    source: str  # Node RID (BlockScience uses KoiNetNode RID type)
    target: str  # Node RID
    edge_type: EdgeType
    status: EdgeStatus
    rid_types: List[str] = []


def generate_edge_rid(source: str, target: str) -> str:
    """Generate a deterministic edge RID from source and target node RIDs.

    Format: orn:koi-net.edge:{sha256(source+target)[:16]}
    This matches BlockScience's KoiNetEdge(sha256_hash(str(source) + str(target))).
    """
    combined = str(source) + str(target)
    edge_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]
    return f"orn:koi-net.edge:{edge_hash}"


def generate_edge_bundle(
    source: str,
    target: str,
    rid_types: List[str],
    edge_type: EdgeType
) -> dict:
    """Generate an edge Bundle dict with PROPOSED status.

    Returns a dict with {rid, manifest, contents} suitable for caching
    or wrapping in a KOIEvent.  Uses our Bundle format rather than
    rid-lib's Bundle.generate() since we haven't migrated yet (Phase 2).

    Args:
        source: Source node RID
        target: Target node RID
        rid_types: List of RID type patterns for this edge
        edge_type: WEBHOOK or POLL

    Returns:
        Dict with rid, contents (EdgeProfile as dict)
    """
    edge_rid = generate_edge_rid(source, target)
    edge_profile = EdgeProfile(
        source=source,
        target=target,
        rid_types=rid_types,
        edge_type=edge_type,
        status=EdgeStatus.PROPOSED,
    )
    return {
        "rid": edge_rid,
        "contents": edge_profile.model_dump(),
    }
