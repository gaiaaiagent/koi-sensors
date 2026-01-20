"""
KOI Ledger Entity Indexer
Indexes Regen Ledger credit classes, projects, and organizations for entity resolution.

This module handles the entity indexing pipeline:
1. Fetches credit classes and projects from the Ledger API
2. Resolves metadata IRIs to get canonical names
3. Generates aliases for fuzzy matching
4. Emits KOI bundles for storage in entity_registry
"""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

# Add parent directories to path for shared modules
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from koi_protocol.core.bundle_system import Bundle
from shared.rid_types.blockchain import (
    RegenCreditClassRID,
    RegenProjectRID,
    RegenOrganizationRID,
)
from shared.persistent_state import PersistentSensorState


logger = logging.getLogger('koi.sensor.ledger.entity_indexer')


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class CreditClassEntity:
    """Credit class entity data"""
    id: str
    admin: str
    credit_type_abbrev: str
    metadata_iri: str
    name: Optional[str] = None
    description: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    metadata_resolved: Optional[Dict[str, Any]] = None


@dataclass
class ProjectEntity:
    """Project entity data"""
    id: str
    class_id: str
    admin: str
    jurisdiction: str
    metadata_iri: str
    name: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    metadata_resolved: Optional[Dict[str, Any]] = None


@dataclass
class OrganizationEntity:
    """Organization entity derived from admin addresses"""
    admin: str
    admin_prefix: str
    credit_classes: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)


# ============================================================================
# Metadata Resolver
# ============================================================================

class MetadataResolver:
    """
    Resolves Regen metadata IRIs to get canonical names and descriptions.

    The metadata resolver fetches JSON-LD metadata from the Regen data API
    and extracts schema.org-style properties for names, descriptions, etc.
    """

    def __init__(self, api_base: str = "https://api.regen.network/data/v2/metadata-graph"):
        self.api_base = api_base
        self._cache: Dict[str, Dict[str, Any]] = {}

    async def resolve(self, iri: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
        """
        Resolve a regen: IRI to get metadata.

        Args:
            iri: The Regen metadata IRI (e.g., regen:13toVf...)
            client: HTTP client for making requests

        Returns:
            Resolved metadata dict or None if resolution fails
        """
        if not iri or not iri.startswith('regen:'):
            return None

        if iri in self._cache:
            return self._cache[iri]

        try:
            url = f"{self.api_base}/{iri}"
            response = await client.get(url, timeout=30.0)

            if response.status_code == 200:
                data = response.json()
                self._cache[iri] = data
                return data
            else:
                logger.debug(f"Failed to resolve metadata for {iri}: {response.status_code}")
                return None

        except Exception as e:
            logger.debug(f"Error resolving metadata for {iri}: {e}")
            return None

    def extract_name(self, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extract canonical name from resolved metadata"""
        if not metadata:
            return None

        # Try common fields for name (JSON-LD style)
        for field_name in ['schema:name', 'name', 'regen:name', 'dc:title', 'title']:
            if field_name in metadata:
                value = metadata[field_name]
                if isinstance(value, list):
                    return value[0] if value else None
                return value

        return None

    def extract_description(self, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extract description from resolved metadata"""
        if not metadata:
            return None

        for field_name in ['schema:description', 'description', 'regen:description', 'dc:description']:
            if field_name in metadata:
                value = metadata[field_name]
                if isinstance(value, list):
                    return value[0] if value else None
                return value

        return None

    def extract_location(self, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """Extract location from resolved metadata"""
        if not metadata:
            return None

        for field_name in ['schema:location', 'location', 'regen:projectLocation', 'regen:location']:
            if field_name in metadata:
                value = metadata[field_name]
                if isinstance(value, dict):
                    # May be a structured location object
                    return value.get('name') or value.get('address') or str(value)
                if isinstance(value, list):
                    return value[0] if value else None
                return value

        return None

    def generate_aliases(self, name: Optional[str], entity_id: str) -> List[str]:
        """
        Generate aliases for an entity based on its name.

        This helps with fuzzy matching in entity resolution.
        """
        aliases = []

        # Always include the ID
        aliases.append(entity_id)

        if not name:
            return aliases

        # Add the name itself
        aliases.append(name)

        # Generate acronym if multi-word
        words = name.split()
        if len(words) > 1:
            acronym = ''.join(w[0].upper() for w in words if w and w[0].isalpha())
            if len(acronym) >= 2 and acronym != entity_id:
                aliases.append(acronym)

        # Add variations without common suffixes
        suffixes_to_strip = [
            'Credit Class', 'Credits', 'Credit', 'Class',
            'Project', 'Program', 'Initiative'
        ]
        for suffix in suffixes_to_strip:
            if name.lower().endswith(suffix.lower()):
                base = name[:-len(suffix)].strip()
                if base and base not in aliases:
                    aliases.append(base)

        # Remove duplicates while preserving order
        seen = set()
        unique_aliases = []
        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower not in seen:
                seen.add(alias_lower)
                unique_aliases.append(alias)

        return unique_aliases


# ============================================================================
# Entity Indexer
# ============================================================================

class EntityIndexer:
    """
    Indexes Regen Ledger entities (credit classes, projects, organizations)
    and emits KOI bundles for storage in the entity_registry.
    """

    def __init__(
        self,
        api_endpoint: str = "https://lcd-regen.keplr.app",
        metadata_api: str = "https://api.regen.network/data/v2/metadata-graph",
        resolve_metadata: bool = True,
        generate_aliases: bool = True,
        build_organizations: bool = True,
        metadata_delay_ms: int = 100,
    ):
        self.api_endpoint = api_endpoint
        self.metadata_resolver = MetadataResolver(metadata_api)
        self.resolve_metadata = resolve_metadata
        self.generate_aliases = generate_aliases
        self.build_organizations = build_organizations
        self.metadata_delay_ms = metadata_delay_ms

        # Track organizations by admin address
        self.organizations: Dict[str, OrganizationEntity] = {}

        # State management
        self.state = PersistentSensorState('ledger_entities', Path(__file__).parent)

    async def collect_credit_classes(self, client: httpx.AsyncClient) -> List[CreditClassEntity]:
        """Fetch all credit classes from Ledger API"""
        classes = []
        pagination_key = None

        while True:
            try:
                url = f"{self.api_endpoint}/regen/ecocredit/v1/classes"
                params = {"pagination.limit": "100"}
                if pagination_key:
                    params["pagination.key"] = pagination_key

                response = await client.get(url, params=params, timeout=30.0)

                if response.status_code != 200:
                    logger.error(f"Failed to fetch credit classes: {response.status_code}")
                    break

                data = response.json()

                for class_data in data.get('classes', []):
                    credit_class = CreditClassEntity(
                        id=class_data.get('id', ''),
                        admin=class_data.get('admin', ''),
                        credit_type_abbrev=class_data.get('credit_type_abbrev', ''),
                        metadata_iri=class_data.get('metadata', ''),
                    )
                    classes.append(credit_class)

                pagination = data.get('pagination', {})
                pagination_key = pagination.get('next_key')
                if not pagination_key:
                    break

            except Exception as e:
                logger.error(f"Error fetching credit classes: {e}")
                break

        logger.info(f"Collected {len(classes)} credit classes from ledger")
        return classes

    async def collect_projects(self, client: httpx.AsyncClient) -> List[ProjectEntity]:
        """Fetch all projects from Ledger API"""
        projects = []
        pagination_key = None

        while True:
            try:
                url = f"{self.api_endpoint}/regen/ecocredit/v1/projects"
                params = {"pagination.limit": "100"}
                if pagination_key:
                    params["pagination.key"] = pagination_key

                response = await client.get(url, params=params, timeout=30.0)

                if response.status_code != 200:
                    logger.error(f"Failed to fetch projects: {response.status_code}")
                    break

                data = response.json()

                for project_data in data.get('projects', []):
                    project = ProjectEntity(
                        id=project_data.get('id', ''),
                        class_id=project_data.get('class_id', ''),
                        admin=project_data.get('admin', ''),
                        jurisdiction=project_data.get('jurisdiction', ''),
                        metadata_iri=project_data.get('metadata', ''),
                    )
                    projects.append(project)

                pagination = data.get('pagination', {})
                pagination_key = pagination.get('next_key')
                if not pagination_key:
                    break

            except Exception as e:
                logger.error(f"Error fetching projects: {e}")
                break

        logger.info(f"Collected {len(projects)} projects from ledger")
        return projects

    async def enrich_credit_class(
        self, credit_class: CreditClassEntity, client: httpx.AsyncClient
    ) -> CreditClassEntity:
        """Enrich credit class with resolved metadata"""
        if not self.resolve_metadata or not credit_class.metadata_iri:
            return credit_class

        metadata = await self.metadata_resolver.resolve(credit_class.metadata_iri, client)
        if metadata:
            credit_class.metadata_resolved = metadata
            credit_class.name = self.metadata_resolver.extract_name(metadata)
            credit_class.description = self.metadata_resolver.extract_description(metadata)

            if self.generate_aliases:
                credit_class.aliases = self.metadata_resolver.generate_aliases(
                    credit_class.name, credit_class.id
                )

        # Delay to respect rate limits
        await asyncio.sleep(self.metadata_delay_ms / 1000)
        return credit_class

    async def enrich_project(
        self, project: ProjectEntity, client: httpx.AsyncClient
    ) -> ProjectEntity:
        """Enrich project with resolved metadata"""
        if not self.resolve_metadata or not project.metadata_iri:
            return project

        metadata = await self.metadata_resolver.resolve(project.metadata_iri, client)
        if metadata:
            project.metadata_resolved = metadata
            project.name = self.metadata_resolver.extract_name(metadata)
            project.description = self.metadata_resolver.extract_description(metadata)
            project.location = self.metadata_resolver.extract_location(metadata)

            if self.generate_aliases:
                project.aliases = self.metadata_resolver.generate_aliases(
                    project.name, project.id
                )

        # Delay to respect rate limits
        await asyncio.sleep(self.metadata_delay_ms / 1000)
        return project

    def track_organization(self, admin: str, entity_type: str, entity_id: str):
        """Track organizations by admin address"""
        if not self.build_organizations:
            return

        # Use first 15 chars of admin address as identifier
        admin_prefix = admin[:15] if len(admin) > 15 else admin

        if admin not in self.organizations:
            self.organizations[admin] = OrganizationEntity(
                admin=admin,
                admin_prefix=admin_prefix,
            )

        org = self.organizations[admin]
        if entity_type == 'CREDIT_CLASS':
            if entity_id not in org.credit_classes:
                org.credit_classes.append(entity_id)
        elif entity_type == 'PROJECT':
            if entity_id not in org.projects:
                org.projects.append(entity_id)

    def create_credit_class_bundle(self, credit_class: CreditClassEntity) -> Bundle:
        """Create KOI Bundle for a credit class entity"""
        rid = RegenCreditClassRID(credit_class.id)
        collected_at = datetime.now(timezone.utc).isoformat()

        # Bundle contents - structured for entity_registry storage
        contents = {
            'entity_type': 'CREDIT_CLASS',
            'id': credit_class.id,
            'name': credit_class.name or credit_class.id,
            'aliases': credit_class.aliases,
            'admin': credit_class.admin,
            'credit_type': credit_class.credit_type_abbrev,
            'metadata_iri': credit_class.metadata_iri,
            'description': credit_class.description,
            'source': 'regen_ledger',
            'collected_at': collected_at,
        }

        # Manifest metadata - used by Event Bridge for indexing
        metadata = {
            'source': 'regen_ledger',
            'source_type': 'blockchain',
            'entity_type': 'CREDIT_CLASS',
            'ledger_id': credit_class.id,
            'admin_address': credit_class.admin,
            'metadata_iri': credit_class.metadata_iri,
            'aliases': json.dumps(credit_class.aliases),  # JSON string for JSONB
            'published_at': collected_at,
            'published_confidence': 0.95,
        }

        return Bundle.generate(
            rid=rid,
            contents=contents,
            content_type='application/json',
            metadata=metadata
        )

    def create_project_bundle(self, project: ProjectEntity) -> Bundle:
        """Create KOI Bundle for a project entity"""
        rid = RegenProjectRID(project.id)
        collected_at = datetime.now(timezone.utc).isoformat()

        contents = {
            'entity_type': 'PROJECT',
            'id': project.id,
            'name': project.name or project.id,
            'class_id': project.class_id,
            'jurisdiction': project.jurisdiction,
            'location': project.location,
            'aliases': project.aliases,
            'admin': project.admin,
            'metadata_iri': project.metadata_iri,
            'description': project.description,
            'source': 'regen_ledger',
            'collected_at': collected_at,
        }

        metadata = {
            'source': 'regen_ledger',
            'source_type': 'blockchain',
            'entity_type': 'PROJECT',
            'ledger_id': project.id,
            'class_id': project.class_id,
            'admin_address': project.admin,
            'jurisdiction': project.jurisdiction,
            'metadata_iri': project.metadata_iri,
            'aliases': json.dumps(project.aliases),
            'published_at': collected_at,
            'published_confidence': 0.95,
        }

        return Bundle.generate(
            rid=rid,
            contents=contents,
            content_type='application/json',
            metadata=metadata
        )

    def create_organization_bundle(self, org: OrganizationEntity) -> Bundle:
        """Create KOI Bundle for an organization entity"""
        rid = RegenOrganizationRID(org.admin_prefix)
        collected_at = datetime.now(timezone.utc).isoformat()

        contents = {
            'entity_type': 'ORGANIZATION',
            'id': org.admin_prefix,
            'admin': org.admin,
            'credit_classes': org.credit_classes,
            'projects': org.projects,
            'source': 'regen_ledger',
            'collected_at': collected_at,
        }

        metadata = {
            'source': 'regen_ledger',
            'source_type': 'blockchain',
            'entity_type': 'ORGANIZATION',
            'admin_address': org.admin,
            'administered_classes': json.dumps(org.credit_classes),
            'administered_projects': json.dumps(org.projects),
            'published_at': collected_at,
            'published_confidence': 0.90,
        }

        return Bundle.generate(
            rid=rid,
            contents=contents,
            content_type='application/json',
            metadata=metadata
        )

    def get_content_hash(self, bundle: Bundle) -> str:
        """Get content hash from bundle for deduplication"""
        return bundle.manifest.sha256_hash

    async def index_entities(self) -> Dict[str, Any]:
        """
        Main indexing method - collects and enriches all entities.

        Returns a dict with all collected bundles and statistics.
        """
        logger.info("Starting entity indexing cycle")

        results = {
            'credit_class_bundles': [],
            'project_bundles': [],
            'organization_bundles': [],
            'stats': {
                'credit_classes': 0,
                'projects': 0,
                'organizations': 0,
                'metadata_resolved': 0,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        }

        async with httpx.AsyncClient() as client:
            # Collect and enrich credit classes
            credit_classes = await self.collect_credit_classes(client)
            for credit_class in credit_classes:
                enriched = await self.enrich_credit_class(credit_class, client)
                bundle = self.create_credit_class_bundle(enriched)
                results['credit_class_bundles'].append(bundle)
                self.track_organization(credit_class.admin, 'CREDIT_CLASS', credit_class.id)
                if enriched.metadata_resolved:
                    results['stats']['metadata_resolved'] += 1

            results['stats']['credit_classes'] = len(credit_classes)

            # Collect and enrich projects
            projects = await self.collect_projects(client)
            for project in projects:
                enriched = await self.enrich_project(project, client)
                bundle = self.create_project_bundle(enriched)
                results['project_bundles'].append(bundle)
                self.track_organization(project.admin, 'PROJECT', project.id)
                if enriched.metadata_resolved:
                    results['stats']['metadata_resolved'] += 1

            results['stats']['projects'] = len(projects)

            # Create organization bundles
            if self.build_organizations:
                for org in self.organizations.values():
                    bundle = self.create_organization_bundle(org)
                    results['organization_bundles'].append(bundle)

                results['stats']['organizations'] = len(self.organizations)

        logger.info(
            f"Entity indexing complete: {results['stats']['credit_classes']} classes, "
            f"{results['stats']['projects']} projects, "
            f"{results['stats']['organizations']} organizations"
        )

        return results


# ============================================================================
# Standalone Usage
# ============================================================================

async def main():
    """Standalone indexing run (for testing)"""
    import argparse

    parser = argparse.ArgumentParser(description='Index Regen Ledger entities')
    parser.add_argument('--api', default='https://lcd-regen.keplr.app', help='Ledger API endpoint')
    parser.add_argument('--no-metadata', action='store_true', help='Skip metadata resolution')
    parser.add_argument('--output', default='output/entities.json', help='Output file path')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    indexer = EntityIndexer(
        api_endpoint=args.api,
        resolve_metadata=not args.no_metadata,
    )

    results = await indexer.index_entities()

    # Convert bundles to serializable format
    output = {
        'credit_classes': [b.to_dict() for b in results['credit_class_bundles']],
        'projects': [b.to_dict() for b in results['project_bundles']],
        'organizations': [b.to_dict() for b in results['organization_bundles']],
        'stats': results['stats'],
    }

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Indexed entities written to {output_path}")
    print(f"Stats: {results['stats']}")


if __name__ == '__main__':
    asyncio.run(main())
