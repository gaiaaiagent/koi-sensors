"""
Whitelist-based entity extractor for high-quality extraction
Uses curated lists and strict validation
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from extractors.known_entities import (
    KNOWN_PEOPLE,
    KNOWN_ORGANIZATIONS,
    NOT_PEOPLE,
    NOT_ORGANIZATIONS,
    is_known_person,
    is_known_organization,
    is_definitely_not_person,
    is_definitely_not_organization,
    normalize_organization_name
)


class WhitelistExtractor:
    """
    High-quality entity extraction using whitelists and strict validation
    """
    
    def __init__(self):
        """Initialize the whitelist extractor"""
        self.version = "2.0.0"
        self.known_people = set(KNOWN_PEOPLE)
        self.known_orgs = set(KNOWN_ORGANIZATIONS)
        
    def extract_from_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract entities from a document using whitelist approach
        
        Args:
            document: Document dictionary with content, title, etc.
            
        Returns:
            Extraction results with high-quality entities
        """
        doc_id = document.get('id', 'unknown')
        content = document.get('content', '')
        title = document.get('title', '')
        
        # Combine title and content
        full_text = f"{title}\n\n{content}" if title else content
        
        start_time = datetime.now()
        
        # Extract entities
        people = self._extract_people(full_text)
        organizations = self._extract_organizations(full_text)
        credit_classes = self._extract_credit_classes(full_text)
        projects = self._extract_projects(full_text)
        methodologies = self._extract_methodologies(full_text)
        
        # Combine all entities
        all_entities = people + organizations + credit_classes + projects + methodologies
        
        end_time = datetime.now()
        
        return {
            "document_id": doc_id,
            "extraction_method": "whitelist",
            "extractor_version": self.version,
            "processing_time_ms": int((end_time - start_time).total_seconds() * 1000),
            "entities_found": len(all_entities),
            "entities": all_entities,
            "timestamp": start_time.isoformat()
        }
    
    def _extract_people(self, text: str) -> List[Dict[str, Any]]:
        """Extract known people from text"""
        entities = []
        
        for person_name in self.known_people:
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(person_name) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                # Check context to ensure it's not in a navigation element
                if not self._is_in_navigation_context(person_name, text):
                    entities.append({
                        "entity_type": "Person",
                        "value": person_name,
                        "confidence": 1.0,  # High confidence for known entities
                        "properties": {
                            "name": person_name,
                            "source": "whitelist"
                        }
                    })
        
        return entities
    
    def _extract_organizations(self, text: str) -> List[Dict[str, Any]]:
        """Extract known organizations from text"""
        entities = []
        seen = set()  # Track what we've already added
        
        for org_name in self.known_orgs:
            # Use word boundaries for accurate matching
            pattern = r'\b' + re.escape(org_name) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                # Normalize the organization name
                normalized = normalize_organization_name(org_name)
                
                # Skip if we've already added this normalized form
                if normalized.lower() in seen:
                    continue
                    
                # Check it's not in a bad context
                if not self._is_in_navigation_context(org_name, text):
                    entities.append({
                        "entity_type": "Organization",
                        "value": normalized,
                        "confidence": 1.0,
                        "properties": {
                            "name": normalized,
                            "original_form": org_name,
                            "source": "whitelist"
                        }
                    })
                    seen.add(normalized.lower())
        
        return entities
    
    def _extract_credit_classes(self, text: str) -> List[Dict[str, Any]]:
        """Extract credit class identifiers"""
        entities = []
        seen = set()
        
        # Pattern for credit classes: C01, C02, etc.
        pattern = r'\b(C\d{2,3})\b'
        matches = re.finditer(pattern, text)
        
        for match in matches:
            credit_id = match.group(1)
            if credit_id not in seen:
                # Get context to determine credit type
                context_start = max(0, match.start() - 100)
                context_end = min(len(text), match.end() + 100)
                context = text[context_start:context_end].lower()
                
                credit_type = "unknown"
                if "carbon" in context:
                    credit_type = "carbon"
                elif "biodiversity" in context:
                    credit_type = "biodiversity"
                elif "soil" in context:
                    credit_type = "soil"
                
                entities.append({
                    "entity_type": "CreditClass",
                    "value": credit_id,
                    "confidence": 1.0,
                    "properties": {
                        "classId": credit_id,
                        "creditType": credit_type,
                        "source": "pattern"
                    }
                })
                seen.add(credit_id)
        
        return entities
    
    def _extract_projects(self, text: str) -> List[Dict[str, Any]]:
        """Extract project identifiers"""
        entities = []
        seen = set()
        
        # Pattern for projects: P001, P002, etc.
        pattern = r'\b(P\d{3,4})\b'
        matches = re.finditer(pattern, text)
        
        for match in matches:
            project_id = match.group(1)
            if project_id not in seen:
                entities.append({
                    "entity_type": "Project",
                    "value": project_id,
                    "confidence": 1.0,
                    "properties": {
                        "projectId": project_id,
                        "source": "pattern"
                    }
                })
                seen.add(project_id)
        
        return entities
    
    def _extract_methodologies(self, text: str) -> List[Dict[str, Any]]:
        """Extract methodology identifiers"""
        entities = []
        seen = set()
        
        # Pattern for Verra methodologies: VM0042, etc.
        pattern = r'\b(VM\d{4})\b'
        matches = re.finditer(pattern, text)
        
        for match in matches:
            method_id = match.group(1)
            if method_id not in seen:
                entities.append({
                    "entity_type": "Methodology",
                    "value": method_id,
                    "confidence": 1.0,
                    "properties": {
                        "methodologyId": method_id,
                        "standardBody": "Verra",
                        "source": "pattern"
                    }
                })
                seen.add(method_id)
        
        return entities
    
    def _is_in_navigation_context(self, entity: str, text: str) -> bool:
        """
        Check if an entity appears in a navigation/menu context
        
        Args:
            entity: The entity string to check
            text: The full text
            
        Returns:
            True if entity is likely in navigation/menu context
        """
        # Find the entity in text
        pattern = re.escape(entity)
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        
        if not matches:
            return False
        
        # Check the context around the first match
        match = matches[0]
        context_start = max(0, match.start() - 50)
        context_end = min(len(text), match.end() + 50)
        context = text[context_start:context_end]
        
        # Navigation/menu indicators
        nav_indicators = [
            '* [',     # Markdown list link
            '](#',     # Anchor link
            '](/',     # Internal link
            '###',     # Header
            '##',      # Header
            '```',     # Code block
            '| ',      # Table
            'Table of Contents',
            'Prerequisites',
            'See also',
            'Related',
            'Navigation',
            'Menu'
        ]
        
        return any(indicator in context for indicator in nav_indicators)


def test_whitelist_extractor():
    """Test the whitelist extractor"""
    extractor = WhitelistExtractor()
    
    test_doc = {
        "id": "test001",
        "title": "Regen Network Documentation",
        "content": """
        Gregory Landua founded Regen Network along with Will Szal. 
        The project uses Cosmos SDK and partners with GitHub for development.
        
        Credit class C01 is for carbon credits, while C02 is for biodiversity.
        Project P001 uses methodology VM0042 from Verra.
        
        ### Navigation
        * [Install Regen](#install)
        * [Update Go](#update)
        
        The Regen Foundation works with the Solana Foundation on various initiatives.
        """
    }
    
    result = extractor.extract_from_document(test_doc)
    
    print(f"Extracted {result['entities_found']} entities:")
    for entity in result['entities']:
        print(f"  {entity['entity_type']}: {entity['value']}")


if __name__ == "__main__":
    test_whitelist_extractor()