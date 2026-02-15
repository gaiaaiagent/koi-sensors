"""
KOI Protocol Models — BlockScience-aligned data models for KOI-net interoperability.

This package contains Pydantic models that match BlockScience's koi-net protocol
definitions, enabling Regen's coordinator to participate in federated peer discovery.

Modules:
    node  — NodeType, NodeProvides, NodeProfile
    edge  — EdgeType, EdgeStatus, EdgeProfile, generate_edge_bundle()
    config — NodeConfig, ServerConfig, KoiNetConfig (YAML-based configuration)
"""

from .node import NodeType, NodeProvides, NodeProfile
from .edge import EdgeType, EdgeStatus, EdgeProfile, generate_edge_bundle
from .config import ServerConfig, KoiNetConfig, NodeConfig

__all__ = [
    "NodeType", "NodeProvides", "NodeProfile",
    "EdgeType", "EdgeStatus", "EdgeProfile", "generate_edge_bundle",
    "ServerConfig", "KoiNetConfig", "NodeConfig",
]
