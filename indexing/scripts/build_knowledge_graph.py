#!/usr/bin/env python3
"""
Phase 3: Knowledge Graph Building
Processes documents and chunks to extract entities and relationships
"""

import sys
import asyncio
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from loguru import logger
import argparse
from tqdm import tqdm
import re
from collections import defaultdict

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))


class KnowledgeGraphBuilder:
    """
    Phase 3: Build knowledge graph from indexed documents
    Discovers entities and relationships from actual content
    """
    
    def __init__(self):
        """Initialize knowledge graph builder"""
        # Check for manifest from previous phases
        self.manifest_path = Path("/home/regenai/project/indexing/storage/index_manifest.json")
        self.docs_dir = Path("/home/regenai/project/indexing/storage/documents")
        self.chunks_dir = Path("/home/regenai/project/indexing/storage/chunks")
        self.metadata_dir = Path("/home/regenai/project/indexing/storage/metadata")
        self.graph_dir = Path("/home/regenai/project/indexing/storage/knowledge_graph")
        
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                "No index manifest found. Please run collection and embedding phases first."
            )
        
        with open(self.manifest_path) as f:
            self.manifest = json.load(f)
        
        # Create graph storage directory
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        
        # Entity patterns for Regen Network
        self.entity_patterns = {
            'credit_class': r'\b[CP]\d{2,3}\b',  # C01, C02, P001, etc.
            'batch_denom': r'\b[CP]\d{2,3}-\d{3}-\d{8}-\d{8}-\d{3}\b',  # Full batch denoms
            'project_id': r'\bP\d{3,4}\b',  # P001, P002, etc.
            'methodology': r'(?:VM\d{4}|methodology[\s:]+[\w\s-]+)',  # VM0042, methodology names
            'location': r'(?:latitude|longitude|coords?)[\s:]+[-\d.]+',  # Coordinates
            'wallet_address': r'\bregen[a-z0-9]{39}\b',  # Regen wallet addresses
            'validator': r'\bregenvaloper[a-z0-9]{39}\b',  # Validator addresses
        }
        
        # Initialize graph structure
        self.graph = {
            'entities': defaultdict(list),  # entity_type -> list of entities
            'relationships': [],  # list of (source, relation, target) tuples
            'entity_metadata': {},  # entity_id -> metadata
            'statistics': {}
        }
        
        # Statistics
        self.stats = {
            'start_time': datetime.now(),
            'documents_processed': 0,
            'entities_discovered': defaultdict(int),
            'relationships_found': 0,
            'errors': []
        }
    
    def extract_entities(self, text: str, source_id: str) -> Dict[str, List[Dict]]:
        """
        Extract entities from text using patterns
        
        Args:
            text: Text to extract entities from
            source_id: ID of the source document
            
        Returns:
            Dictionary of entity types to entity list
        """
        entities = defaultdict(list)
        
        for entity_type, pattern in self.entity_patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                entity = {
                    'value': match,
                    'type': entity_type,
                    'source': source_id,
                    'context': self.get_context(text, match)
                }
                entities[entity_type].append(entity)
        
        # Also extract custom entities based on keywords
        custom_entities = self.extract_custom_entities(text, source_id)
        for entity_type, entity_list in custom_entities.items():
            entities[entity_type].extend(entity_list)
        
        return dict(entities)
    
    def extract_custom_entities(self, text: str, source_id: str) -> Dict[str, List[Dict]]:
        """
        Extract custom entities based on Regen Network specific patterns
        
        Args:
            text: Text to analyze
            source_id: Source document ID
            
        Returns:
            Dictionary of custom entities
        """
        entities = defaultdict(list)
        
        # Extract credit types
        credit_types = re.findall(r'\b(?:carbon|biodiversity|soil|water) credits?\b', text, re.IGNORECASE)
        for credit_type in credit_types:
            entities['credit_type'].append({
                'value': credit_type.lower(),
                'type': 'credit_type',
                'source': source_id,
                'context': self.get_context(text, credit_type)
            })
        
        # Extract organizations
        org_patterns = [
            r'(?:Regen Network|Regen Foundation|Regen Registry)',
            r'(?:Microsoft|Google|Meta|Amazon|Tesla)',  # Tech companies
            r'(?:Verra|Gold Standard|Climate Action Reserve)',  # Standards bodies
        ]
        for pattern in org_patterns:
            orgs = re.findall(pattern, text, re.IGNORECASE)
            for org in orgs:
                entities['organization'].append({
                    'value': org,
                    'type': 'organization',
                    'source': source_id,
                    'context': self.get_context(text, org)
                })
        
        # Extract governance proposals
        proposals = re.findall(r'(?:proposal|prop)[\s#]+(\d+)', text, re.IGNORECASE)
        for prop_num in proposals:
            entities['proposal'].append({
                'value': f"proposal_{prop_num}",
                'type': 'proposal',
                'source': source_id,
                'context': self.get_context(text, f"proposal {prop_num}")
            })
        
        return dict(entities)
    
    def get_context(self, text: str, entity: str, window: int = 100) -> str:
        """
        Get context around an entity mention
        
        Args:
            text: Full text
            entity: Entity to find context for
            window: Characters to include before/after
            
        Returns:
            Context string
        """
        idx = text.lower().find(entity.lower())
        if idx == -1:
            return ""
        
        start = max(0, idx - window)
        end = min(len(text), idx + len(entity) + window)
        
        context = text[start:end]
        # Clean up context
        context = ' '.join(context.split())
        
        return context
    
    def extract_relationships(self, entities: Dict[str, List[Dict]], doc_metadata: Dict) -> List[Tuple]:
        """
        Extract relationships between entities
        
        Args:
            entities: Extracted entities
            doc_metadata: Document metadata
            
        Returns:
            List of (source, relation, target) tuples
        """
        relationships = []
        
        # Credit class to project relationships
        if 'credit_class' in entities and 'project_id' in entities:
            for credit_class in entities['credit_class']:
                for project in entities['project_id']:
                    relationships.append((
                        credit_class['value'],
                        'has_project',
                        project['value']
                    ))
        
        # Batch to credit class relationships
        if 'batch_denom' in entities and 'credit_class' in entities:
            for batch in entities['batch_denom']:
                # Extract credit class from batch denom (first part)
                class_id = batch['value'].split('-')[0]
                relationships.append((
                    batch['value'],
                    'belongs_to_class',
                    class_id
                ))
        
        # Methodology relationships
        if 'methodology' in entities and 'credit_class' in entities:
            for method in entities['methodology']:
                for credit_class in entities['credit_class']:
                    relationships.append((
                        credit_class['value'],
                        'uses_methodology',
                        method['value']
                    ))
        
        # Organization relationships
        if 'organization' in entities:
            for org in entities['organization']:
                # Link to projects if mentioned together
                if 'project_id' in entities:
                    for project in entities['project_id']:
                        relationships.append((
                            org['value'],
                            'involved_in',
                            project['value']
                        ))
        
        # Document source relationships
        source_type = doc_metadata.get('source_type', 'document')
        doc_id = doc_metadata.get('id', 'unknown')
        
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                relationships.append((
                    entity['value'],
                    'mentioned_in',
                    f"{source_type}:{doc_id}"
                ))
        
        return relationships
    
    def process_document(self, doc_path: Path) -> Tuple[Dict, List]:
        """
        Process a single document to extract entities and relationships
        
        Args:
            doc_path: Path to document JSON file
            
        Returns:
            Tuple of (entities dict, relationships list)
        """
        try:
            with open(doc_path) as f:
                doc = json.load(f)
            
            content = doc.get('content', '')
            doc_id = doc.get('koi_rid', doc.get('id', doc_path.stem))
            
            # Extract entities
            entities = self.extract_entities(content, doc_id)
            
            # Extract relationships
            relationships = self.extract_relationships(entities, doc)
            
            return entities, relationships
            
        except Exception as e:
            logger.error(f"Failed to process document {doc_path}: {e}")
            self.stats['errors'].append(f"Process error: {doc_path.name}")
            return {}, []
    
    def build_graph(self, limit: Optional[int] = None):
        """
        Build knowledge graph from all documents
        
        Args:
            limit: Optional limit on documents to process
        """
        logger.info("🔨 Building knowledge graph from documents...")
        
        doc_files = list(self.docs_dir.glob("*.json"))
        if limit:
            doc_files = doc_files[:limit]
        
        logger.info(f"Processing {len(doc_files)} documents...")
        
        for doc_path in tqdm(doc_files, desc="Processing documents"):
            entities, relationships = self.process_document(doc_path)
            
            # Add entities to graph
            for entity_type, entity_list in entities.items():
                for entity in entity_list:
                    # Deduplicate entities
                    entity_id = f"{entity_type}:{entity['value']}"
                    if entity_id not in self.graph['entity_metadata']:
                        self.graph['entities'][entity_type].append(entity['value'])
                        self.graph['entity_metadata'][entity_id] = {
                            'first_seen': doc_path.stem,
                            'mentions': 1,
                            'contexts': [entity.get('context', '')]
                        }
                        self.stats['entities_discovered'][entity_type] += 1
                    else:
                        # Update existing entity
                        self.graph['entity_metadata'][entity_id]['mentions'] += 1
                        context = entity.get('context', '')
                        if context and context not in self.graph['entity_metadata'][entity_id]['contexts']:
                            self.graph['entity_metadata'][entity_id]['contexts'].append(context)
            
            # Add relationships to graph
            self.graph['relationships'].extend(relationships)
            self.stats['relationships_found'] += len(relationships)
            
            self.stats['documents_processed'] += 1
        
        # Deduplicate relationships
        self.graph['relationships'] = list(set(self.graph['relationships']))
        
        logger.success(f"Processed {self.stats['documents_processed']} documents")
        logger.info(f"Discovered {sum(self.stats['entities_discovered'].values())} entities")
        logger.info(f"Found {len(self.graph['relationships'])} unique relationships")
    
    def save_graph(self):
        """Save the knowledge graph to disk"""
        logger.info("💾 Saving knowledge graph...")
        
        # Save main graph structure
        graph_path = self.graph_dir / "knowledge_graph.json"
        with open(graph_path, 'w') as f:
            # Convert defaultdict to regular dict for JSON serialization
            save_graph = {
                'entities': dict(self.graph['entities']),
                'relationships': self.graph['relationships'],
                'statistics': {
                    'total_entities': sum(len(v) for v in self.graph['entities'].values()),
                    'total_relationships': len(self.graph['relationships']),
                    'entity_types': list(self.graph['entities'].keys()),
                    'entities_by_type': {k: len(v) for k, v in self.graph['entities'].items()}
                }
            }
            json.dump(save_graph, f, indent=2)
        
        # Save entity metadata
        metadata_path = self.graph_dir / "entity_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(self.graph['entity_metadata'], f, indent=2)
        
        # Save relationships in triple format
        triples_path = self.graph_dir / "relationships.jsonl"
        with open(triples_path, 'w') as f:
            for source, relation, target in self.graph['relationships']:
                triple = {'source': source, 'relation': relation, 'target': target}
                f.write(json.dumps(triple) + '\n')
        
        logger.success(f"Saved knowledge graph to {graph_path}")
        logger.info(f"Saved entity metadata to {metadata_path}")
        logger.info(f"Saved relationship triples to {triples_path}")
    
    def update_manifest(self):
        """Update the index manifest with knowledge graph info"""
        self.manifest['knowledge_graph_phase'] = {
            'completed_at': datetime.now().isoformat(),
            'documents_processed': self.stats['documents_processed'],
            'entities_discovered': dict(self.stats['entities_discovered']),
            'relationships_found': self.stats['relationships_found'],
            'errors_count': len(self.stats['errors'])
        }
        self.manifest['requires_knowledge_graph'] = False
        
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)
        
        logger.info("📋 Updated index manifest with knowledge graph info")
    
    def print_graph_summary(self):
        """Print a summary of the knowledge graph"""
        logger.info("\n📊 Knowledge Graph Summary:")
        logger.info(f"  Total entities: {sum(len(v) for v in self.graph['entities'].values())}")
        logger.info(f"  Total relationships: {len(self.graph['relationships'])}")
        
        logger.info("\n🏷️  Entities by type:")
        for entity_type, entities in self.graph['entities'].items():
            logger.info(f"  {entity_type}: {len(entities)}")
            # Show sample entities
            if entities:
                samples = entities[:3]
                for sample in samples:
                    logger.debug(f"    - {sample}")
        
        # Show relationship statistics
        relation_counts = defaultdict(int)
        for _, relation, _ in self.graph['relationships']:
            relation_counts[relation] += 1
        
        logger.info("\n🔗 Relationships by type:")
        for relation, count in sorted(relation_counts.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {relation}: {count}")
    
    def run(self, limit: Optional[int] = None):
        """
        Run knowledge graph building pipeline
        
        Args:
            limit: Optional limit on documents to process
        """
        logger.info("🚀 Starting Knowledge Graph Building (Phase 3)...")
        logger.info(f"📊 Processing documents from: {self.docs_dir}")
        
        try:
            # Build the graph
            self.build_graph(limit=limit)
            
            # Save the graph
            self.save_graph()
            
            # Update manifest
            self.update_manifest()
            
            # Print summary
            self.print_graph_summary()
            
            # Print statistics
            self.print_stats()
            
        except Exception as e:
            logger.error(f"Knowledge graph building failed: {e}")
            self.stats['errors'].append(str(e))
            import traceback
            logger.debug(traceback.format_exc())
    
    def print_stats(self):
        """Print knowledge graph building statistics"""
        duration = datetime.now() - self.stats['start_time']
        
        logger.info("\n" + "=" * 60)
        logger.success("✅ Knowledge Graph Building Complete!")
        logger.info("=" * 60)
        
        logger.info(f"📄 Documents processed: {self.stats['documents_processed']}")
        logger.info(f"🏷️  Total entities discovered: {sum(self.stats['entities_discovered'].values())}")
        logger.info(f"🔗 Total relationships found: {self.stats['relationships_found']}")
        logger.info(f"⏱️  Time taken: {duration}")
        
        logger.info("\n✨ Indexing Pipeline Complete!")
        logger.info("All three phases have been successfully completed:")
        logger.info("  ✅ Phase 1: Document collection and caching")
        logger.info("  ✅ Phase 2: Embedding generation")
        logger.info("  ✅ Phase 3: Knowledge graph building")
        
        if self.stats['errors']:
            logger.warning(f"\n⚠️  Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:
                logger.warning(f"  - {error}")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Build knowledge graph from indexed documents')
    parser.add_argument('--limit', type=int, help='Limit number of documents to process')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = "DEBUG" if args.verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    
    # Add file logging
    log_file = Path("/home/regenai/project/indexing/logs/knowledge_graph.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(log_file, rotation="100 MB", level="DEBUG")
    
    try:
        # Create builder
        builder = KnowledgeGraphBuilder()
        
        # Run knowledge graph building
        builder.run(limit=args.limit)
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())