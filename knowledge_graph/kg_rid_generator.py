"""
KOI Knowledge Graph - RID Generation Utilities
Extends the KOI RID system with Knowledge Graph-specific resource identifiers

Follows the ORN pattern from koi_protocol.core.rid_system:
- Base RID: orn:namespace.type:reference
- KG extensions: {base_rid}:kg:{pass_type}:{version}
- Entity extensions: {base_rid}:entity:{entity_type}:{entity_id}
- Statement extensions: {base_rid}:statement:{statement_type}:{index}

Examples:
    Memory RID: orn:web.page:domain/abc123
    KG Extraction: orn:web.page:domain/abc123:kg:passA:v1.1
    Entity: orn:web.page:domain/abc123:entity:person:jane-doe
    Statement: orn:web.page:domain/abc123:statement:claim:001
"""

import re
from typing import Optional


def generate_entity_rid(parent_rid: str, entity_type: str, entity_name: str) -> str:
    """
    Generate RID for extracted knowledge graph entity

    Creates a unique identifier for an entity extracted from a memory/document.
    The entity_name is normalized to lowercase, spaces replaced with hyphens,
    and truncated to 50 characters to maintain reasonable RID lengths.

    Args:
        parent_rid: The RID of the parent memory/document (e.g., "orn:web.page:domain/path")
        entity_type: Type of entity (e.g., "person", "organization", "location", "concept")
        entity_name: Name/label of the entity (e.g., "Jane Doe", "Regen Network")

    Returns:
        str: Entity RID in format: {parent_rid}:entity:{entity_type}:{entity_id}

    Examples:
        >>> generate_entity_rid("orn:web.page:regen.network/abc123", "person", "Jane Doe")
        'orn:web.page:regen.network/abc123:entity:person:jane-doe'

        >>> generate_entity_rid("orn:web.page:example.com/xyz", "organization", "Regen Network")
        'orn:web.page:example.com/xyz:entity:organization:regen-network'
    """
    # Normalize entity name: lowercase, replace spaces with hyphens, limit length
    entity_id = entity_name.lower().replace(' ', '-')[:50]

    # Remove any characters that aren't alphanumeric, hyphens, or underscores
    entity_id = re.sub(r'[^a-z0-9\-_]', '', entity_id)

    # Normalize entity type to lowercase
    entity_type = entity_type.lower()

    return f"{parent_rid}:entity:{entity_type}:{entity_id}"


def generate_statement_rid(parent_rid: str, statement_type: str, index: int) -> str:
    """
    Generate RID for extracted knowledge graph statement

    Creates a unique identifier for a statement/triple extracted from a memory/document.
    The index is zero-padded to 3 digits to ensure lexicographic ordering.

    Args:
        parent_rid: The RID of the parent memory/document (e.g., "orn:web.page:domain/path")
        statement_type: Type of statement (e.g., "claim", "fact", "opinion", "relation")
        index: Sequential index of this statement within the extraction (0-999)

    Returns:
        str: Statement RID in format: {parent_rid}:statement:{statement_type}:{index:03d}

    Examples:
        >>> generate_statement_rid("orn:web.page:regen.network/abc123", "claim", 1)
        'orn:web.page:regen.network/abc123:statement:claim:001'

        >>> generate_statement_rid("orn:web.page:example.com/xyz", "fact", 42)
        'orn:web.page:example.com/xyz:statement:fact:042'

    Raises:
        ValueError: If index is negative or > 999
    """
    if index < 0 or index > 999:
        raise ValueError(f"Statement index must be between 0 and 999, got {index}")

    # Normalize statement type to lowercase
    statement_type = statement_type.lower()

    return f"{parent_rid}:statement:{statement_type}:{index:03d}"


def generate_kg_extraction_rid(parent_rid: str, pass_type: str, version: str = "v1.1") -> str:
    """
    Generate RID for knowledge graph extraction result

    Creates a unique identifier for a KG extraction pass on a memory/document.
    This RID represents the entire extraction result (containing multiple entities/statements).

    Args:
        parent_rid: The RID of the parent memory/document (e.g., "orn:web.page:domain/path")
        pass_type: Type of extraction pass (e.g., "passA", "passB", "entity_resolution",
                   "nanopub_creation", "contradiction_detection")
        version: Ontology/extractor version (default: "v1.1")

    Returns:
        str: KG extraction RID in format: {parent_rid}:kg:{pass_type}:{version}

    Examples:
        >>> generate_kg_extraction_rid("orn:web.page:regen.network/abc123", "passA")
        'orn:web.page:regen.network/abc123:kg:passA:v1.1'

        >>> generate_kg_extraction_rid("orn:web.page:example.com/xyz", "passB", "v2.0")
        'orn:web.page:example.com/xyz:kg:passB:v2.0'

        >>> generate_kg_extraction_rid("orn:web.page:example.com/xyz", "entity_resolution")
        'orn:web.page:example.com/xyz:kg:entity_resolution:v1.1'

    Valid pass_types:
        - passA: Initial entity/statement extraction
        - passB: Refinement and relation extraction
        - entity_resolution: Entity deduplication and merging
        - nanopub_creation: Nanopublication generation
        - contradiction_detection: Contradiction identification
    """
    # Normalize version format (ensure it starts with 'v')
    if not version.startswith('v'):
        version = f"v{version}"

    return f"{parent_rid}:kg:{pass_type}:{version}"


def parse_kg_rid(kg_rid: str) -> Optional[dict]:
    """
    Parse a KG-extended RID to extract its components

    Utility function to decompose a KG RID into its constituent parts.
    Useful for validation and debugging.

    Args:
        kg_rid: A KG-extended RID string

    Returns:
        dict or None: Dictionary with parsed components if valid, None otherwise
            - 'parent_rid': Base memory/document RID
            - 'extension_type': 'kg', 'entity', or 'statement'
            - Type-specific fields based on extension_type

    Examples:
        >>> parse_kg_rid("orn:web.page:domain/abc:kg:passA:v1.1")
        {
            'parent_rid': 'orn:web.page:domain/abc',
            'extension_type': 'kg',
            'pass_type': 'passA',
            'version': 'v1.1'
        }

        >>> parse_kg_rid("orn:web.page:domain/abc:entity:person:jane-doe")
        {
            'parent_rid': 'orn:web.page:domain/abc',
            'extension_type': 'entity',
            'entity_type': 'person',
            'entity_id': 'jane-doe'
        }
    """
    # Split RID into base and extension parts
    # Look for :kg:, :entity:, or :statement: markers
    if ':kg:' in kg_rid:
        parts = kg_rid.split(':kg:')
        if len(parts) != 2:
            return None
        parent_rid = parts[0]
        extension = parts[1].split(':')
        if len(extension) != 2:
            return None
        return {
            'parent_rid': parent_rid,
            'extension_type': 'kg',
            'pass_type': extension[0],
            'version': extension[1]
        }

    elif ':entity:' in kg_rid:
        parts = kg_rid.split(':entity:')
        if len(parts) != 2:
            return None
        parent_rid = parts[0]
        extension = parts[1].split(':')
        if len(extension) != 2:
            return None
        return {
            'parent_rid': parent_rid,
            'extension_type': 'entity',
            'entity_type': extension[0],
            'entity_id': extension[1]
        }

    elif ':statement:' in kg_rid:
        parts = kg_rid.split(':statement:')
        if len(parts) != 2:
            return None
        parent_rid = parts[0]
        extension = parts[1].split(':')
        if len(extension) != 2:
            return None
        try:
            index = int(extension[1])
        except ValueError:
            return None
        return {
            'parent_rid': parent_rid,
            'extension_type': 'statement',
            'statement_type': extension[0],
            'index': index
        }

    return None


# Validation utilities

def validate_kg_rid(kg_rid: str, expected_type: Optional[str] = None) -> bool:
    """
    Validate a KG RID format and optionally check its type

    Args:
        kg_rid: The RID to validate
        expected_type: Optional expected extension type ('kg', 'entity', or 'statement')

    Returns:
        bool: True if valid, False otherwise

    Examples:
        >>> validate_kg_rid("orn:web.page:domain/abc:kg:passA:v1.1")
        True

        >>> validate_kg_rid("orn:web.page:domain/abc:kg:passA:v1.1", "kg")
        True

        >>> validate_kg_rid("orn:web.page:domain/abc:entity:person:jane", "statement")
        False
    """
    parsed = parse_kg_rid(kg_rid)
    if parsed is None:
        return False

    if expected_type is not None:
        return parsed['extension_type'] == expected_type

    return True
