"""
Pattern-based extractor for known formats in Regen Network content
Uses regex patterns from the ontology to extract entities
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from ontology.regen_ontology import RegenOntology, EntityType


@dataclass
class ExtractedEntity:
    """Represents an extracted entity with metadata"""
    entity_type: EntityType
    value: str
    confidence: float
    start_pos: int
    end_pos: int
    context: str = ""
    properties: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


class PatternExtractor:
    """
    Fast pattern-based extraction using regex
    Best for well-defined formats like C01, P001, VM0042
    """
    
    def __init__(self, ontology: RegenOntology):
        """
        Initialize with ontology
        
        Args:
            ontology: Regen ontology instance
        """
        self.ontology = ontology
        self.version = "1.0.0"
        
        # Compile patterns for efficiency
        self.compiled_patterns = self._compile_patterns()
        
    def _compile_patterns(self) -> Dict[EntityType, List[re.Pattern]]:
        """Compile regex patterns for each entity type"""
        compiled = {}
        
        for entity_type, definition in self.ontology.entities.items():
            compiled[entity_type] = [
                re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for pattern in definition.extraction_patterns
            ]
        
        return compiled
    
    def extract_from_text(self, text: str, document_id: str = None) -> List[ExtractedEntity]:
        """
        Extract entities from text using patterns
        
        Args:
            text: Text to extract from
            document_id: Optional document identifier
            
        Returns:
            List of extracted entities
        """
        entities = []
        
        # Process in priority order (most specific first)
        for entity_type in self.ontology.extraction_rules["priority_order"]:
            if entity_type in self.compiled_patterns:
                entity_extractions = self._extract_entity_type(text, entity_type)
                entities.extend(entity_extractions)
        
        # Remove duplicates (same entity found by multiple patterns)
        entities = self._deduplicate_entities(entities)
        
        # Add context for each entity
        for entity in entities:
            entity.context = self._extract_context(text, entity.start_pos, entity.end_pos)
        
        return entities
    
    def _extract_entity_type(self, text: str, entity_type: EntityType) -> List[ExtractedEntity]:
        """Extract a specific entity type from text"""
        entities = []
        patterns = self.compiled_patterns.get(entity_type, [])
        
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                
                # Validate the match
                if self._validate_extraction(entity_type, value):
                    entity = ExtractedEntity(
                        entity_type=entity_type,
                        value=value,
                        confidence=0.95,  # High confidence for pattern matches
                        start_pos=match.start(),
                        end_pos=match.end(),
                        properties=self._extract_properties(entity_type, value, text, match)
                    )
                    entities.append(entity)
        
        return entities
    
    def _validate_extraction(self, entity_type: EntityType, value: str) -> bool:
        """Validate extracted value against ontology rules"""
        validation_rules = self.ontology.extraction_rules.get("validation_rules", {})
        
        if entity_type in validation_rules:
            validator = validation_rules[entity_type]
            return validator(value)
        
        # Basic validation - not empty
        return bool(value and value.strip())
    
    def _extract_properties(self, entity_type: EntityType, value: str, 
                          text: str, match: re.Match) -> Dict[str, Any]:
        """Extract additional properties based on entity type"""
        properties = {}
        
        if entity_type == EntityType.CREDIT_CLASS:
            properties["classId"] = value
            # Try to determine credit type from context
            context_window = text[max(0, match.start()-100):match.end()+100].lower()
            if "carbon" in context_window:
                properties["creditType"] = "carbon"
            elif "biodiversity" in context_window:
                properties["creditType"] = "biodiversity"
            elif "soil" in context_window:
                properties["creditType"] = "soil"
                
        elif entity_type == EntityType.PROJECT:
            properties["projectId"] = value
            
        elif entity_type == EntityType.METHODOLOGY:
            properties["methodologyId"] = value
            # Check for Verra methodologies
            if value.startswith("VM"):
                properties["standardBody"] = "Verra"
                
        elif entity_type == EntityType.ORGANIZATION:
            properties["name"] = value
            # Determine organization type
            if "foundation" in value.lower():
                properties["type"] = "Foundation"
            elif "network" in value.lower():
                properties["type"] = "Network"
            elif any(suffix in value for suffix in ["Inc", "LLC", "Corp"]):
                properties["type"] = "Company"
                
        return properties
    
    def _extract_context(self, text: str, start: int, end: int, window: int = 100) -> str:
        """Extract context around an entity"""
        context_start = max(0, start - window)
        context_end = min(len(text), end + window)
        
        context = text[context_start:context_end]
        
        # Clean up context
        context = re.sub(r'\s+', ' ', context).strip()
        
        return context
    
    def _deduplicate_entities(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """Remove duplicate entities (same type and value)"""
        seen = set()
        unique_entities = []
        
        for entity in entities:
            key = (entity.entity_type, entity.value.upper())
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return unique_entities
    
    def extract_from_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract entities from a document dictionary
        
        Args:
            document: Document with 'content', 'title', 'id' etc.
            
        Returns:
            Extraction results with entities and metadata
        """
        doc_id = document.get('id', 'unknown')
        content = document.get('content', '')
        title = document.get('title', '')
        
        # Combine title and content for extraction
        full_text = f"{title}\n\n{content}" if title else content
        
        start_time = datetime.now()
        entities = self.extract_from_text(full_text, doc_id)
        end_time = datetime.now()
        
        # Convert entities to dictionaries for serialization
        entity_dicts = []
        for entity in entities:
            entity_dict = {
                "entity_type": entity.entity_type.value,
                "value": entity.value,
                "confidence": entity.confidence,
                "start_pos": entity.start_pos,
                "end_pos": entity.end_pos,
                "context": entity.context,
                "properties": entity.properties
            }
            entity_dicts.append(entity_dict)
        
        return {
            "document_id": doc_id,
            "extraction_method": "pattern",
            "extractor_version": self.version,
            "processing_time_ms": int((end_time - start_time).total_seconds() * 1000),
            "entities_found": len(entities),
            "entities": entity_dicts,
            "timestamp": start_time.isoformat()
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the extractor"""
        return {
            "extractor_type": "pattern",
            "version": self.version,
            "entity_types_supported": [e.value for e in self.compiled_patterns.keys()],
            "total_patterns": sum(len(patterns) for patterns in self.compiled_patterns.values())
        }


def test_pattern_extractor():
    """Test the pattern extractor with sample text"""
    from ontology.regen_ontology import create_ontology
    
    # Create extractor
    ontology = create_ontology()
    extractor = PatternExtractor(ontology)
    
    # Test text
    test_text = """
    The Regen Network has developed several credit classes including C01 for carbon credits,
    C02 for biodiversity credits, and C03 for soil carbon. Project P001 uses the VM0042
    methodology developed by Verra to generate C01 credits. Regen Foundation oversees
    the governance process, while Regen Network Development PBC handles technical implementation.
    """
    
    # Extract entities
    entities = extractor.extract_from_text(test_text)
    
    print(f"Found {len(entities)} entities:")
    for entity in entities:
        print(f"  {entity.entity_type.value}: {entity.value} (confidence: {entity.confidence})")
        if entity.properties:
            print(f"    Properties: {entity.properties}")
        print(f"    Context: {entity.context[:80]}...")
        print()


if __name__ == "__main__":
    test_pattern_extractor()