import logging
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from koi_net.processor.handler import HandlerType
from koi_net.processor.knowledge_object import KnowledgeObject
from koi_net.processor.interface import ProcessorInterface
from rid_lib import RID, Manifest
from .core import node

logger = logging.getLogger(__name__)

# Storage paths for different content types
STORAGE_BASE = Path("/home/regenai/project/koi-infrastructure/koi-regen-node/storage")
AGENT_OUTPUTS_PATH = STORAGE_BASE / "agent_outputs"
CREDIT_DATA_PATH = STORAGE_BASE / "credit_data"
GOVERNANCE_PATH = STORAGE_BASE / "governance"

# Create storage directories
for path in [AGENT_OUTPUTS_PATH, CREDIT_DATA_PATH, GOVERNANCE_PATH]:
    path.mkdir(parents=True, exist_ok=True)

def generate_regen_rid(content: str, object_type: str, subject: str, relevance: str = "relevant") -> str:
    """
    Generate RID following Regen's naming convention
    Format: [relevance].[type].[subject].vX.Y.Z.hash
    """
    # Generate content hash
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
    
    # Clean subject (replace spaces and special chars with hyphens)
    clean_subject = subject.lower().replace(' ', '-').replace('_', '-')
    
    # Create RID string
    rid_string = f"{relevance}.{object_type}.{clean_subject}.v1.0.0.{content_hash}"
    
    return rid_string

@node.processor.register_handler(
    handler_type=HandlerType.RID,
    rid_types=["relevant.agent"]
)
def handle_agent_output(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Handler for AI agent outputs
    Processes and stores agent-generated content with RIDs
    """
    logger.info(f"Processing agent output: {kobj.rid}")
    
    # Extract content and metadata
    content = kobj.contents if kobj.contents else {}
    
    # Store agent output
    output_data = {
        "rid": str(kobj.rid),
        "timestamp": datetime.now().isoformat(),
        "content": content,
        "manifest": kobj.manifest.model_dump() if kobj.manifest else None,
        "metadata": {
            "handler": "agent_output",
            "processed_at": datetime.now().isoformat()
        }
    }
    
    # Save to storage
    filename = AGENT_OUTPUTS_PATH / f"{str(kobj.rid).replace('.', '_')}.json"
    with open(filename, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    logger.info(f"Stored agent output: {filename}")
    
    # Update metrics
    node.metrics["agent_outputs_processed"] = node.metrics.get("agent_outputs_processed", 0) + 1

@node.processor.register_handler(
    handler_type=HandlerType.RID,
    rid_types=["core.credit", "core.registry"]
)
def handle_credit_class_data(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Handler for credit class and registry data
    Processes critical credit-related information
    """
    logger.info(f"Processing credit class data: {kobj.rid}")
    
    # Extract credit class information
    content = kobj.contents if kobj.contents else {}
    
    # Determine if this is credit class or registry data
    if "core.credit" in str(kobj.rid):
        data_type = "credit_class"
    else:
        data_type = "registry"
    
    # Store credit data
    credit_data = {
        "rid": str(kobj.rid),
        "type": data_type,
        "timestamp": datetime.now().isoformat(),
        "content": content,
        "manifest": kobj.manifest.model_dump() if kobj.manifest else None,
        "metadata": {
            "handler": "credit_class_data",
            "processed_at": datetime.now().isoformat(),
            "relevance": "core"  # Credit data is always core relevance
        }
    }
    
    # Save to storage
    filename = CREDIT_DATA_PATH / f"{str(kobj.rid).replace('.', '_')}.json"
    with open(filename, 'w') as f:
        json.dump(credit_data, f, indent=2)
    
    logger.info(f"Stored credit class data: {filename}")
    
    # Update metrics
    node.metrics["credit_data_processed"] = node.metrics.get("credit_data_processed", 0) + 1

@node.processor.register_handler(
    handler_type=HandlerType.RID,
    rid_types=["relevant.governance"]
)
def handle_governance_content(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Handler for governance proposals and discussions
    """
    logger.info(f"Processing governance content: {kobj.rid}")
    
    content = kobj.contents if kobj.contents else {}
    
    # Store governance data
    gov_data = {
        "rid": str(kobj.rid),
        "timestamp": datetime.now().isoformat(),
        "content": content,
        "manifest": kobj.manifest.model_dump() if kobj.manifest else None,
        "metadata": {
            "handler": "governance_content",
            "processed_at": datetime.now().isoformat()
        }
    }
    
    # Save to storage
    filename = GOVERNANCE_PATH / f"{str(kobj.rid).replace('.', '_')}.json"
    with open(filename, 'w') as f:
        json.dump(gov_data, f, indent=2)
    
    logger.info(f"Stored governance content: {filename}")
    
    # Update metrics
    node.metrics["governance_processed"] = node.metrics.get("governance_processed", 0) + 1

@node.processor.register_handler(
    handler_type=HandlerType.MANIFEST
)
def handle_manifest_update(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Handler for manifest updates
    Tracks versions and changes to knowledge objects
    """
    logger.info(f"Processing manifest update: {kobj.rid}")
    
    # Update version tracking
    if kobj.manifest:
        node.metrics["manifests_processed"] = node.metrics.get("manifests_processed", 0) + 1
        logger.info(f"Manifest timestamp: {kobj.manifest.timestamp}")

@node.processor.register_handler(
    handler_type=HandlerType.FINAL
)
def final_processing(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Final handler for all knowledge objects
    Updates overall metrics and performs cleanup
    """
    # Update total RID count
    node.metrics["total_rids"] = node.metrics.get("total_rids", 0) + 1
    
    # Check if we've reached the target (Milestone 1.3.3)
    if node.metrics["total_rids"] >= 10000:
        logger.info("🎉 Reached 10,000+ RID-tagged outputs milestone!")
    
    # Log progress every 100 RIDs
    if node.metrics["total_rids"] % 100 == 0:
        logger.info(f"Progress: {node.metrics['total_rids']} RIDs processed")

# Custom handler for integrating with existing indexing system
@node.processor.register_handler(
    handler_type=HandlerType.RID,
    rid_types=["core.memo", "core.analysis", "relevant.notes", "background.readme"]
)
def handle_document_content(processor: ProcessorInterface, kobj: KnowledgeObject):
    """
    Handler for document content from the existing indexing system
    Bridges KOI with the current document processing pipeline
    """
    logger.info(f"Processing document content: {kobj.rid}")
    
    content = kobj.contents if kobj.contents else {}
    
    # Check if this content comes from the indexing system
    if "source_path" in content:
        # This is from our indexing system
        logger.info(f"Document from indexing system: {content.get('source_path')}")
        
        # Update the document processor to include the RID
        from pathlib import Path
        indexing_path = Path("/home/regenai/project/indexing/storage/documents")
        
        # Store the RID mapping
        rid_mapping = {
            "rid": str(kobj.rid),
            "document_id": content.get("document_id"),
            "source_path": content.get("source_path"),
            "timestamp": datetime.now().isoformat()
        }
        
        mapping_file = indexing_path / "rid_mappings.json"
        mappings = []
        if mapping_file.exists():
            with open(mapping_file, 'r') as f:
                mappings = json.load(f)
        
        mappings.append(rid_mapping)
        
        with open(mapping_file, 'w') as f:
            json.dump(mappings, f, indent=2)
    
    # Update metrics
    node.metrics["documents_processed"] = node.metrics.get("documents_processed", 0) + 1