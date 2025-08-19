from pydantic import Field
from koi_net.config import NodeConfig, KoiNetConfig
from koi_net.protocol.node import NodeProfile, NodeProvides, NodeType

class RegenKOIConfig(NodeConfig):
    """
    Configuration for Regen Network's KOI sensor node
    Implements Regen's naming convention: [relevance].[type].[subject].vX.Y.Z
    """
    koi_net: KoiNetConfig | None = Field(default_factory = lambda:
        KoiNetConfig(
            node_name="regen-koi-sensor",   # Regen Network KOI sensor node
            node_profile=NodeProfile(
                node_type=NodeType.FULL,
                provides=NodeProvides(
                    # RID types for AI agent outputs and indexed content
                    event=[
                        "core.memo",         # Strategic documents
                        "core.analysis",     # Data-driven investigations
                        "core.credit",       # Credit class content
                        "core.registry",     # Registry updates
                        "relevant.agent",    # AI agent outputs
                        "relevant.governance", # Governance content
                        "relevant.notes",    # Exploratory ideas
                        "background.readme", # Documentation
                    ],
                    # State types for knowledge base
                    state=[
                        "core.credit",       # Credit class information
                        "core.registry",     # Registry data
                        "relevant.agent",    # Agent outputs with RIDs
                        "relevant.governance", # Governance proposals
                    ]
                )
            )
        )
    )
    
    # Regen-specific configuration
    rid_namespace: str = "regen"
    registry_api_url: str = "https://registry.regen.network/api"
    indexing_path: str = "/home/regenai/project/indexing"
    
    # Contract requirements
    target_rid_count: int = 10000  # Milestone 1.3.3: 10,000+ RID-tagged outputs
    health_check_enabled: bool = True
    
    # Naming convention settings
    default_relevance: str = "relevant"  # Default relevance level
    version_start: tuple = (1, 0, 0)  # Starting version for new subjects