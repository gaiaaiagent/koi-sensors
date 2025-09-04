"""
Document processor for knowledge graph extraction
Orchestrates different extraction methods and processes documents
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from ontology.regen_ontology import RegenOntology, create_ontology
from extractors.pattern_extractor import PatternExtractor
from extractors.claude_extractor import ClaudeExtractor


@dataclass
class ProcessingResult:
    """Result of processing a document"""
    document_id: str
    success: bool
    entities_extracted: int
    relationships_found: int
    processing_time_ms: int
    extraction_methods: Dict[str, Any]
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class DocumentProcessor:
    """
    Main processor that orchestrates knowledge extraction from documents
    """
    
    def __init__(self, ontology: Optional[RegenOntology] = None):
        """Initialize with ontology and extractors"""
        self.ontology = ontology or create_ontology()
        self.pattern_extractor = PatternExtractor(self.ontology)
        self.claude_extractor = ClaudeExtractor(self.ontology)
        
        # Storage paths
        self.storage_base = Path("/home/regenai/project/knowledge_graph/storage")
        self.entities_dir = self.storage_base / "graph" / "entities"
        self.relationships_dir = self.storage_base / "graph" / "relationships"
        self.provenance_dir = self.storage_base / "provenance"
        
        # Create directories
        for directory in [self.entities_dir, self.relationships_dir, self.provenance_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Processing statistics
        self.stats = {
            "documents_processed": 0,
            "total_entities": 0,
            "total_relationships": 0,
            "errors": 0
        }
    
    def process_document(self, document: Dict[str, Any]) -> ProcessingResult:
        """
        Process a single document through the extraction pipeline
        
        Args:
            document: Document dictionary with content, title, etc.
            
        Returns:
            ProcessingResult with extraction details
        """
        start_time = datetime.now()
        doc_id = document.get('id', 'unknown')
        
        print(f"Processing document: {doc_id}")
        print(f"Title: {document.get('title', 'No title')}")
        print(f"Source: {document.get('source', 'Unknown source')}")
        
        try:
            # Extract using pattern matching (fast, specific patterns)
            pattern_results = self.pattern_extractor.extract_from_document(document)
            
            # Extract using Claude (semantic understanding)
            claude_results = self.claude_extractor.extract_from_document(document)
            
            # Combine entities from both extractors
            pattern_entities = pattern_results.get('entities', [])
            claude_entities = claude_results.get('entities', [])
            
            # Filter out bad pattern matches and merge with Claude results
            good_pattern_entities = self._filter_pattern_entities(pattern_entities)
            entities = good_pattern_entities + claude_entities
            
            # Remove duplicates
            entities = self._deduplicate_entities(entities)
            
            # Process and store entities
            stored_entities = self._store_entities(doc_id, entities)
            
            # TODO: Extract relationships
            relationships = []
            
            # Store provenance
            self._store_provenance(doc_id, document, {
                'pattern': pattern_results,
                'claude': claude_results
            })
            
            end_time = datetime.now()
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            # Update statistics
            self.stats["documents_processed"] += 1
            self.stats["total_entities"] += len(stored_entities)
            
            result = ProcessingResult(
                document_id=doc_id,
                success=True,
                entities_extracted=len(stored_entities),
                relationships_found=len(relationships),
                processing_time_ms=processing_time,
                extraction_methods={
                    'pattern': pattern_results,
                    'claude': claude_results
                }
            )
            
            print(f"✅ Extracted {len(stored_entities)} entities in {processing_time}ms")
            self._print_entities(stored_entities)
            
            return result
            
        except Exception as e:
            end_time = datetime.now()
            processing_time = int((end_time - start_time).total_seconds() * 1000)
            
            self.stats["errors"] += 1
            
            result = ProcessingResult(
                document_id=doc_id,
                success=False,
                entities_extracted=0,
                relationships_found=0,
                processing_time_ms=processing_time,
                extraction_methods={},
                errors=[str(e)]
            )
            
            print(f"❌ Error processing document {doc_id}: {e}")
            return result
    
    def _store_entities(self, doc_id: str, entities: List[Dict]) -> List[Dict]:
        """Store extracted entities to disk"""
        stored_entities = []
        
        for entity in entities:
            entity_type = entity.get('entity_type')
            entity_value = entity.get('value')
            
            # Skip invalid entities
            if not entity_type or not entity_value:
                continue
                
            # Clean up the entity value
            entity_value = entity_value.strip()
            if len(entity_value) < 2:  # Skip very short values
                continue
                
            # Add document reference
            entity['source_document'] = doc_id
            entity['extracted_at'] = datetime.now().isoformat()
            
            # Store in type-specific file
            entity_file = self.entities_dir / f"{entity_type.lower()}.jsonl"
            
            with open(entity_file, 'a') as f:
                f.write(json.dumps(entity) + '\n')
            
            stored_entities.append(entity)
        
        return stored_entities
    
    def _store_provenance(self, doc_id: str, document: Dict, extraction_results: Dict):
        """Store extraction provenance"""
        provenance = {
            "document_id": doc_id,
            "document_source": document.get('source'),
            "document_title": document.get('title'),
            "processed_at": datetime.now().isoformat(),
            "ontology_version": self.ontology.VERSION,
            "extraction_methods": extraction_results,
            "total_entities": sum(
                len(result.get('entities', [])) 
                for result in extraction_results.values()
            )
        }
        
        provenance_file = self.provenance_dir / "extraction_log.jsonl"
        with open(provenance_file, 'a') as f:
            f.write(json.dumps(provenance) + '\n')
    
    def _print_entities(self, entities: List[Dict]):
        """Print extracted entities for review"""
        by_type = {}
        for entity in entities:
            entity_type = entity.get('entity_type')
            if entity_type not in by_type:
                by_type[entity_type] = []
            by_type[entity_type].append(entity.get('value'))
        
        for entity_type, values in by_type.items():
            print(f"  {entity_type}: {', '.join(values[:3])}" + 
                  (f" (+{len(values)-3} more)" if len(values) > 3 else ""))
    
    def process_documents_from_directory(self, docs_dir: str, doc_filter: str = None) -> List[ProcessingResult]:
        """
        Process multiple documents from a directory
        
        Args:
            docs_dir: Directory containing JSON document files
            doc_filter: Optional filter (e.g., "github_" for technical docs)
            
        Returns:
            List of processing results
        """
        docs_path = Path(docs_dir)
        if not docs_path.exists():
            print(f"❌ Directory not found: {docs_dir}")
            return []
        
        # Find documents
        pattern = f"{doc_filter}*.json" if doc_filter else "*.json"
        doc_files = list(docs_path.glob(pattern))
        
        print(f"Found {len(doc_files)} documents to process")
        
        results = []
        for doc_file in doc_files[:5]:  # Limit to first 5 for testing
            try:
                with open(doc_file, 'r') as f:
                    document = json.load(f)
                
                result = self.process_document(document)
                results.append(result)
                
                print()  # Add spacing between documents
                
            except Exception as e:
                print(f"❌ Error loading document {doc_file}: {e}")
        
        return results
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        return {
            "stats": self.stats,
            "ontology_version": self.ontology.VERSION,
            "extractors": {
                "pattern": self.pattern_extractor.get_statistics(),
                "claude": {"extractor_type": "claude", "version": self.claude_extractor.version}
            }
        }
    
    def _filter_pattern_entities(self, entities: List[Dict]) -> List[Dict]:
        """Filter out bad pattern matches"""
        good_entities = []
        
        # Common bad pattern words to exclude
        bad_patterns = [
            'inc', 'include', 'including', 'included', 'must', 'should', 'will', 
            'may', 'can', 'need', 'required', 'recommended', 'following',
            'patch release', 'author checklist', 'pull request', 'code of conduct',
            'our pledge', 'our standards', 'upgrade guide', 'migration guide',
            'change log', 'release process', 'security', 'readme', 'license'
        ]
        
        for entity in entities:
            entity_type = entity.get('entity_type')
            value = entity.get('value', '').strip()
            value_lower = value.lower()
            
            # Skip very short or obviously invalid values
            if len(value) < 3 or not value:
                continue
                
            # Skip entities that are clearly not real entities
            if any(bad in value_lower for bad in bad_patterns):
                continue
                
            # Skip entities that are mostly lowercase (likely fragments)
            if value_lower == value and entity_type in ['Person', 'Organization']:
                continue
            
            # Person entity filtering - be very strict
            if entity_type == 'Person':
                # Only keep if it looks like an actual name
                words = value.split()
                if (len(words) == 2 and 
                    all(word[0].isupper() and word[1:].islower() for word in words if word) and
                    all(len(word) >= 2 for word in words) and
                    not any(bad in value_lower for bad in ['guide', 'list', 'process', 'module', 'service'])):
                    good_entities.append(entity)
                continue
            
            # Organization entity filtering - be strict
            if entity_type == 'Organization':
                # Skip obvious non-organizations
                if (len(value) > 50 or 
                    value_lower.endswith(' inc') or
                    any(word in value_lower for word in ['must', 'should', 'will', 'can', 'may']) or
                    value_lower.startswith(('the ', 'a ', 'an ')) and len(value) > 30):
                    continue
                # Only keep well-known organizations or properly capitalized entities
                known_orgs = ['regen network', 'regen foundation', 'regen ledger', 'cosmos', 'github', 'discord', 'verra']
                if (value_lower in known_orgs or 
                    (value[0].isupper() and len(value.split()) <= 4 and 
                     not any(bad in value_lower for bad in ['release', 'guide', 'process', 'module']))):
                    good_entities.append(entity)
                continue
                
            # Keep valid CreditClass, Project, Methodology entities (these patterns are precise)
            if entity_type in ['CreditClass', 'Project', 'Methodology']:
                good_entities.append(entity)
                continue
        
        return good_entities
    
    def _deduplicate_entities(self, entities: List[Dict]) -> List[Dict]:
        """Remove duplicate entities"""
        seen = set()
        unique_entities = []
        
        for entity in entities:
            key = (entity.get('entity_type'), entity.get('value', '').upper())
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return unique_entities


def main():
    """Test the document processor on technical documents"""
    processor = DocumentProcessor()
    
    # Process GitHub/technical documents
    docs_dir = "/home/regenai/project/indexing/storage/documents"
    results = processor.process_documents_from_directory(docs_dir, "github_")
    
    # Print summary
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    print(f"\n📊 Processing Summary:")
    print(f"   Successful: {len(successful)}")
    print(f"   Failed: {len(failed)}")
    print(f"   Total entities: {sum(r.entities_extracted for r in successful)}")
    print(f"   Avg processing time: {sum(r.processing_time_ms for r in successful) / len(successful):.0f}ms")
    
    # Show statistics
    stats = processor.get_statistics()
    print(f"\n📈 Statistics:")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()