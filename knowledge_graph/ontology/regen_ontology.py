"""
Regen Network Ontology v1.0.0
Defines entity types, properties, relationships, and extraction rules
"""

import re
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import json
from datetime import datetime


class EntityType(Enum):
    """Core entity types in the Regen Network ecosystem"""
    # Actor entities
    PERSON = "Person"
    ORGANIZATION = "Organization"
    AI_AGENT = "AIAgent"
    
    # Environmental entities
    CREDIT_CLASS = "CreditClass"
    PROJECT = "Project"
    METHODOLOGY = "Methodology"
    GEOGRAPHIC_AREA = "GeographicArea"
    
    # Governance entities
    PROPOSAL = "Proposal"
    VOTE = "Vote"
    
    # Content entities
    DOCUMENT = "Document"
    CLAIM = "Claim"


class RelationType(Enum):
    """Valid relationship types between entities"""
    # Person-Organization
    FOUNDED = "founded"
    EMPLOYS = "employs"
    ADVISES = "advises"
    REPRESENTS = "represents"
    
    # Project-Credit
    GENERATES = "generates"
    IMPLEMENTS = "implements"
    VALIDATES = "validates"
    LOCATED_IN = "locatedIn"
    
    # Document
    AUTHORED_BY = "authoredBy"
    REFERENCES = "references"
    CONTAINS = "contains"
    
    # Governance
    PROPOSED = "proposed"
    VOTED_ON = "votedOn"
    GOVERNS = "governs"
    
    # General
    RELATED_TO = "relatedTo"


@dataclass
class EntityDefinition:
    """Definition of an entity type with properties and extraction patterns"""
    entity_type: EntityType
    properties: Dict[str, Any]
    required_properties: List[str]
    extraction_patterns: List[str]
    context_clues: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    
    def matches_pattern(self, text: str) -> List[str]:
        """Check if text matches any extraction patterns"""
        matches = []
        for pattern in self.extraction_patterns:
            found = re.findall(pattern, text, re.IGNORECASE)
            matches.extend(found)
        return matches


@dataclass
class RelationshipDefinition:
    """Definition of a relationship between entity types"""
    source_type: EntityType
    relation_type: RelationType
    target_type: EntityType
    extraction_patterns: List[str] = field(default_factory=list)
    cardinality: str = "many-to-many"  # one-to-one, one-to-many, many-to-many


class RegenOntology:
    """
    Regen Network Ontology
    Central definition of entities, relationships, and extraction rules
    """
    
    VERSION = "1.0.0"
    
    def __init__(self):
        """Initialize the ontology with entity and relationship definitions"""
        self.entities = self._define_entities()
        self.relationships = self._define_relationships()
        self.extraction_rules = self._define_extraction_rules()
        
    def _define_entities(self) -> Dict[EntityType, EntityDefinition]:
        """Define all entity types with their properties and patterns"""
        return {
            EntityType.PERSON: EntityDefinition(
                entity_type=EntityType.PERSON,
                properties={
                    "name": str,
                    "role": str,
                    "walletAddress": str,
                    "socialHandles": dict,
                    "email": str,
                    "affiliations": list
                },
                required_properties=["name"],
                extraction_patterns=[
                    r"(?:[A-Z][a-z]+ ){1,3}[A-Z][a-z]+",  # Name pattern
                    r"@[a-zA-Z0-9_]+",  # Social handles
                ],
                context_clues=["founder", "CEO", "developer", "advisor", "said", "proposed"],
                examples=["Gregory Landua", "Will Szal", "Sam Vitello"]
            ),
            
            EntityType.ORGANIZATION: EntityDefinition(
                entity_type=EntityType.ORGANIZATION,
                properties={
                    "name": str,
                    "type": str,
                    "website": str,
                    "walletAddress": str,
                    "role": str,
                    "location": str
                },
                required_properties=["name"],
                extraction_patterns=[
                    r"[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*(?: (?:Inc|LLC|Foundation|Network|DAO|Labs|PBC))",
                    r"Regen (?:Network|Foundation|Registry)",
                    r"(?:Verra|Gold Standard|Climate Action Reserve)"
                ],
                context_clues=["company", "organization", "foundation", "partnered with"],
                examples=["Regen Network", "Regen Foundation", "Microsoft", "Verra"]
            ),
            
            EntityType.CREDIT_CLASS: EntityDefinition(
                entity_type=EntityType.CREDIT_CLASS,
                properties={
                    "classId": str,
                    "creditType": str,
                    "methodology": str,
                    "status": str,
                    "description": str,
                    "issuer": str
                },
                required_properties=["classId"],
                extraction_patterns=[
                    r"\bC\d{2,3}\b",  # C01, C02, C03
                ],
                context_clues=["credit class", "carbon credits", "biodiversity credits"],
                examples=["C01", "C02", "C03"]
            ),
            
            EntityType.PROJECT: EntityDefinition(
                entity_type=EntityType.PROJECT,
                properties={
                    "projectId": str,
                    "name": str,
                    "location": dict,
                    "developer": str,
                    "creditClass": str,
                    "startDate": str,
                    "endDate": str,
                    "status": str
                },
                required_properties=["projectId"],
                extraction_patterns=[
                    r"\bP\d{3,4}\b",  # P001, P002
                ],
                context_clues=["project", "developed by", "generates credits"],
                examples=["P001", "P002", "P003"]
            ),
            
            EntityType.METHODOLOGY: EntityDefinition(
                entity_type=EntityType.METHODOLOGY,
                properties={
                    "methodologyId": str,
                    "name": str,
                    "version": str,
                    "standardBody": str,
                    "creditTypes": list
                },
                required_properties=["methodologyId"],
                extraction_patterns=[
                    r"\bVM\d{4}\b",  # VM0042
                    r"methodology[:\s]+[\w\s-]+"
                ],
                context_clues=["methodology", "verification standard", "protocol"],
                examples=["VM0042", "VM0007"]
            ),
            
            EntityType.PROPOSAL: EntityDefinition(
                entity_type=EntityType.PROPOSAL,
                properties={
                    "proposalId": int,
                    "title": str,
                    "proposer": str,
                    "status": str,
                    "proposalDate": str,
                    "voteEndDate": str,
                    "type": str
                },
                required_properties=["proposalId"],
                extraction_patterns=[
                    r"(?:proposal|prop)[\s#]+(\d+)",
                ],
                context_clues=["proposal", "governance", "vote", "proposed"],
                examples=["Proposal #42", "Prop 23"]
            ),
            
            EntityType.AI_AGENT: EntityDefinition(
                entity_type=EntityType.AI_AGENT,
                properties={
                    "name": str,
                    "platform": str,
                    "koiRid": str,
                    "creator": str,
                    "purpose": str
                },
                required_properties=["name"],
                extraction_patterns=[
                    r"(?:Advocate|Politician|Voice of Nature|Narrative) Agent",
                ],
                context_clues=["AI agent", "bot", "automated"],
                examples=["Advocate Agent", "Politician Agent"]
            ),
        }
    
    def _define_relationships(self) -> List[RelationshipDefinition]:
        """Define valid relationships between entity types"""
        return [
            # Person-Organization relationships
            RelationshipDefinition(
                EntityType.PERSON, RelationType.FOUNDED, EntityType.ORGANIZATION,
                extraction_patterns=["{person} founded {org}", "{person} co-founded {org}"],
                cardinality="many-to-many"
            ),
            RelationshipDefinition(
                EntityType.ORGANIZATION, RelationType.EMPLOYS, EntityType.PERSON,
                extraction_patterns=["{person} (?:at|from|of) {org}", "{person}, {org}"],
                cardinality="one-to-many"
            ),
            
            # Project-Credit relationships
            RelationshipDefinition(
                EntityType.PROJECT, RelationType.GENERATES, EntityType.CREDIT_CLASS,
                extraction_patterns=["{project} generates {credit}", "{project} issues {credit}"],
                cardinality="many-to-one"
            ),
            RelationshipDefinition(
                EntityType.PROJECT, RelationType.IMPLEMENTS, EntityType.METHODOLOGY,
                extraction_patterns=["{project} uses {methodology}", "{project} implements {methodology}"],
                cardinality="many-to-one"
            ),
            
            # Governance relationships
            RelationshipDefinition(
                EntityType.PERSON, RelationType.PROPOSED, EntityType.PROPOSAL,
                extraction_patterns=["{person} proposed {proposal}", "{proposal} by {person}"],
                cardinality="many-to-many"
            ),
            
            # Document relationships
            RelationshipDefinition(
                EntityType.DOCUMENT, RelationType.REFERENCES, EntityType.CREDIT_CLASS,
                extraction_patterns=["mentions {credit}", "describes {credit}"],
                cardinality="many-to-many"
            ),
        ]
    
    def _define_extraction_rules(self) -> Dict[str, Any]:
        """Define rules for extraction and validation"""
        return {
            "priority_order": [
                EntityType.CREDIT_CLASS,  # Extract first (most specific patterns)
                EntityType.PROJECT,
                EntityType.METHODOLOGY,
                EntityType.ORGANIZATION,
                EntityType.PERSON,
                EntityType.PROPOSAL,
                EntityType.AI_AGENT,
            ],
            "validation_rules": {
                EntityType.CREDIT_CLASS: lambda x: re.match(r"^C\d{2,3}$", x),
                EntityType.PROJECT: lambda x: re.match(r"^P\d{3,4}$", x),
                EntityType.METHODOLOGY: lambda x: re.match(r"^VM\d{4}$", x),
            },
            "confidence_thresholds": {
                "pattern_match": 0.95,
                "ner_extraction": 0.75,
                "llm_extraction": 0.60,
            }
        }
    
    def validate_entity(self, entity_type: EntityType, entity_data: Dict) -> Tuple[bool, List[str]]:
        """
        Validate an entity against ontology rules
        
        Args:
            entity_type: Type of entity
            entity_data: Entity properties
            
        Returns:
            (is_valid, list_of_errors)
        """
        errors = []
        
        if entity_type not in self.entities:
            errors.append(f"Unknown entity type: {entity_type}")
            return False, errors
        
        definition = self.entities[entity_type]
        
        # Check required properties
        for prop in definition.required_properties:
            if prop not in entity_data or not entity_data[prop]:
                errors.append(f"Missing required property: {prop}")
        
        # Check validation rules
        if entity_type in self.extraction_rules["validation_rules"]:
            validator = self.extraction_rules["validation_rules"][entity_type]
            key_prop = definition.required_properties[0]
            if key_prop in entity_data:
                if not validator(entity_data[key_prop]):
                    errors.append(f"Invalid format for {key_prop}: {entity_data[key_prop]}")
        
        return len(errors) == 0, errors
    
    def validate_relationship(self, source_type: EntityType, relation: RelationType, 
                            target_type: EntityType) -> bool:
        """Check if a relationship is valid according to the ontology"""
        for rel_def in self.relationships:
            if (rel_def.source_type == source_type and 
                rel_def.relation_type == relation and 
                rel_def.target_type == target_type):
                return True
        return False
    
    def get_entity_patterns(self, entity_type: EntityType) -> List[str]:
        """Get extraction patterns for an entity type"""
        if entity_type in self.entities:
            return self.entities[entity_type].extraction_patterns
        return []
    
    def get_relationship_patterns(self, relation_type: RelationType) -> List[str]:
        """Get extraction patterns for a relationship type"""
        patterns = []
        for rel_def in self.relationships:
            if rel_def.relation_type == relation_type:
                patterns.extend(rel_def.extraction_patterns)
        return patterns
    
    def save_version(self, filepath: str):
        """Save current ontology version to JSON"""
        version_data = {
            "version": self.VERSION,
            "timestamp": datetime.now().isoformat(),
            "entities": {
                str(k): {
                    "properties": v.properties,
                    "required": v.required_properties,
                    "patterns": v.extraction_patterns,
                    "examples": v.examples
                }
                for k, v in self.entities.items()
            },
            "relationships": [
                {
                    "source": str(r.source_type),
                    "relation": str(r.relation_type),
                    "target": str(r.target_type),
                    "patterns": r.extraction_patterns,
                    "cardinality": r.cardinality
                }
                for r in self.relationships
            ],
            "extraction_rules": {
                "priority_order": [str(e) for e in self.extraction_rules["priority_order"]],
                "confidence_thresholds": self.extraction_rules["confidence_thresholds"]
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(version_data, f, indent=2, default=str)
    
    def __str__(self):
        """String representation of the ontology"""
        return f"RegenOntology v{self.VERSION} - {len(self.entities)} entities, {len(self.relationships)} relationships"


# Convenience functions
def create_ontology() -> RegenOntology:
    """Create and return a new Regen ontology instance"""
    return RegenOntology()


def load_ontology(version: str = "1.0.0") -> RegenOntology:
    """Load a specific version of the ontology"""
    # For now, just create the current version
    # In future, could load from saved versions
    return RegenOntology()


if __name__ == "__main__":
    # Test the ontology
    ontology = create_ontology()
    print(ontology)
    
    # Test entity validation
    test_entity = {"classId": "C01", "creditType": "carbon"}
    is_valid, errors = ontology.validate_entity(EntityType.CREDIT_CLASS, test_entity)
    print(f"Valid: {is_valid}, Errors: {errors}")
    
    # Test pattern matching
    text = "The C01 carbon credit class uses VM0042 methodology"
    for entity_type, definition in ontology.entities.items():
        matches = definition.matches_pattern(text)
        if matches:
            print(f"{entity_type}: {matches}")
    
    # Save version
    ontology.save_version("ontology/versions/v1.0.0.json")