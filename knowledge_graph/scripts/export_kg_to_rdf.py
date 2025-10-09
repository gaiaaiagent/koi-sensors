#!/usr/bin/env python3
"""
Export KG Extractions from PostgreSQL to RDF/Turtle format for Apache Jena

This script converts knowledge graph extractions from the PostgreSQL database
into RDF triples suitable for loading into Apache Jena Fuseki.

Usage:
    python export_kg_to_rdf.py --output kg-extractions.ttl
"""

import asyncio
import asyncpg
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any
from loguru import logger

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ontology.namespaces import NAMESPACES, REG, REGX, SCHEMA, PROV, SKOS


class KGToRDFExporter:
    """Export KG extractions to RDF/Turtle format"""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.triples = []
        self.entity_label_to_uri = {}  # Map entity labels to URIs for resolution
        self.stats = {
            'entities_exported': 0,
            'statements_exported': 0,
            'direct_triples_created': 0,
            'reified_statements_kept': 0,
            'entity_to_entity_links': 0,
            'entity_to_literal_links': 0
        }

    def escape_literal(self, value: str) -> str:
        """Escape special characters in RDF literals"""
        if not value:
            return '""'

        # Escape backslashes and quotes
        value = value.replace('\\', '\\\\')
        value = value.replace('"', '\\"')
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '\\r')
        value = value.replace('\t', '\\t')

        return f'"{value}"'

    def rid_to_uri(self, rid: str) -> str:
        """Convert RID to URI format"""
        # RIDs like orn:web.page:domain/path → <https://regen.network/koi/web.page/domain/path>
        clean_rid = rid.replace('orn:', '').replace(':', '/')
        return f"<{REGX}{clean_rid}>"

    def add_triple(self, subject: str, predicate: str, obj: str):
        """Add a triple to the output"""
        self.triples.append(f"    {subject} {predicate} {obj} .")

    async def export_extractions(self) -> int:
        """Export all KG extractions to RDF"""
        logger.info("Connecting to PostgreSQL...")

        conn = await asyncpg.connect(self.db_url)

        try:
            # Get all extractions with source memory info
            query = """
            SELECT
                e.extraction_rid,
                e.memory_rid,
                e.extraction_type,
                e.entities,
                e.statements,
                e.confidence_score,
                e.ontology_version,
                e.tokens_consumed,
                e.cost_usd,
                e.created_at,
                m.metadata->>'source_url' as source_url,
                m.content as source_content
            FROM koi_kg_extractions e
            JOIN koi_memories m ON e.memory_rid = m.rid
            WHERE m.superseded_at IS NULL
            ORDER BY e.created_at
            """

            rows = await conn.fetch(query)
            logger.info(f"Found {len(rows)} extractions to export")

            # PHASE 1: Export all entities and build label-to-URI mapping
            logger.info("Phase 1: Exporting entities and building label index...")
            for row in rows:
                self._export_extraction(row)

                # Export entities (parse JSON if needed)
                entities = row['entities']
                if isinstance(entities, str):
                    import json
                    entities = json.loads(entities)
                entities = entities or []

                for entity in entities:
                    self._export_entity(entity, row['extraction_rid'], row['source_url'])

            logger.info(f"Built entity index with {len(self.entity_label_to_uri)} unique labels")

            # PHASE 2: Export statements with entity resolution
            logger.info("Phase 2: Exporting statements with entity linking...")
            for row in rows:
                statements = row['statements']
                if isinstance(statements, str):
                    import json
                    statements = json.loads(statements)
                statements = statements or []

                for stmt in statements:
                    self._export_statement(stmt, row['extraction_rid'], row['source_url'])

            logger.info(f"Generated {len(self.triples)} RDF triples")
            logger.info(f"Stats: {self.stats}")
            return len(self.triples)

        finally:
            await conn.close()

    def _export_extraction(self, row: Dict[str, Any]):
        """Export extraction metadata as RDF"""
        extraction_uri = self.rid_to_uri(row['extraction_rid'])
        memory_uri = self.rid_to_uri(row['memory_rid'])

        # Type
        self.add_triple(extraction_uri, "rdf:type", "regx:KGExtraction")
        self.add_triple(extraction_uri, "rdf:type", "prov:Activity")

        # Basic properties
        self.add_triple(extraction_uri, "regx:extractionType", self.escape_literal(row['extraction_type']))
        self.add_triple(extraction_uri, "regx:memoryRID", memory_uri)
        self.add_triple(extraction_uri, "regx:confidenceScore", f'"{row["confidence_score"]}"^^xsd:float')
        self.add_triple(extraction_uri, "regx:ontologyVersion", self.escape_literal(row['ontology_version']))

        # Provenance
        if row['source_url']:
            self.add_triple(extraction_uri, "prov:hadPrimarySource", f"<{row['source_url']}>")

        self.add_triple(extraction_uri, "prov:wasGeneratedBy", f"<{REGX}extractor/unified-extractor>")
        self.add_triple(extraction_uri, "prov:generatedAtTime", f'"{row["created_at"].isoformat()}"^^xsd:dateTime')

        # Metrics
        self.add_triple(extraction_uri, "regx:tokensConsumed", f'"{row["tokens_consumed"]}"^^xsd:integer')
        self.add_triple(extraction_uri, "regx:costUSD", f'"{row["cost_usd"]}"^^xsd:float')

    def _export_entity(self, entity: Dict[str, Any], extraction_rid: str, source_url: str):
        """Export entity as RDF and register in label index"""
        entity_uri = self.rid_to_uri(entity['rid'])
        extraction_uri = self.rid_to_uri(extraction_rid)

        # Type (from ontology)
        entity_type = entity.get('type', 'Entity')
        if entity_type in ['Person', 'Organization', 'Project', 'Place', 'Asset', 'Credit', 'Methodology', 'Event']:
            self.add_triple(entity_uri, "rdf:type", f"schema:{entity_type}")
        else:
            self.add_triple(entity_uri, "rdf:type", "regx:Entity")

        # Basic properties
        entity_name = entity.get('name', '')
        self.add_triple(entity_uri, "rdfs:label", self.escape_literal(entity_name))
        self.add_triple(entity_uri, "regx:entityType", self.escape_literal(entity_type))
        self.add_triple(entity_uri, "regx:confidence", f'"{entity.get("confidence", 0.0)}"^^xsd:float')

        # Provenance
        self.add_triple(entity_uri, "prov:wasGeneratedBy", extraction_uri)
        if source_url:
            self.add_triple(entity_uri, "prov:hadPrimarySource", f"<{source_url}>")

        # Register in label-to-URI mapping for entity resolution
        # Use normalized label for better matching
        normalized_label = self._normalize_label(entity_name)
        if normalized_label:
            # Store both normalized and original for fuzzy matching
            self.entity_label_to_uri[normalized_label] = entity_uri
            self.entity_label_to_uri[entity_name] = entity_uri

        self.stats['entities_exported'] += 1

    def _normalize_label(self, label: str) -> str:
        """Normalize entity label for matching"""
        if not label:
            return ""
        # Lowercase, strip, remove extra whitespace
        return " ".join(label.lower().strip().split())

    def _resolve_entity(self, text: str) -> str:
        """Resolve text to entity URI if it matches a known entity"""
        if not text:
            return None

        # Try exact match first
        if text in self.entity_label_to_uri:
            return self.entity_label_to_uri[text]

        # Try normalized match
        normalized = self._normalize_label(text)
        if normalized in self.entity_label_to_uri:
            return self.entity_label_to_uri[normalized]

        return None

    def _predicate_to_uri(self, predicate: str) -> str:
        """Convert predicate string to ontology URI"""
        # Map common predicates to schema.org/prov/custom properties
        predicate_map = {
            'holds_copyright_for': 'regx:holdsCopyrightFor',
            'licenses_work_under': 'regx:licensesWorkUnder',
            'requires_compliance_for_use': 'regx:requiresComplianceForUse',
            'is_available_at': 'schema:url',
            'disclaims_warranties': 'regx:disclaimsWarranties',
            'permits_exceptions_by_law_or_written_agreement': 'regx:permitsExceptions',
            'founded_by': 'schema:founder',
            'founded': 'schema:foundingDate',
            'develops': 'regx:develops',
            'works_for': 'schema:worksFor',
            'member_of': 'schema:memberOf',
            'part_of': 'schema:isPartOf',
            'located_in': 'schema:location',
            'partner_with': 'regx:partnerWith',
        }

        # Try mapped predicate
        if predicate in predicate_map:
            return predicate_map[predicate]

        # Normalize predicate: replace spaces with underscores, remove special chars
        # Allow only alphanumeric, underscore, and hyphen
        import re
        predicate = predicate.replace(' ', '_')
        predicate = re.sub(r'[^a-zA-Z0-9_-]', '', predicate)

        # Default: convert to camelCase property in regx namespace
        # e.g., "is_related_to" -> "regx:isRelatedTo"
        # e.g., "allows users to query" -> "regx:allowsUsersToQuery"
        words = predicate.split('_')
        camel = words[0].lower() + ''.join(word.capitalize() for word in words[1:])
        return f"regx:{camel}"

    def _export_statement(self, stmt: Dict[str, Any], extraction_rid: str, source_url: str):
        """
        Export statement as RDF with entity resolution

        Creates TWO representations:
        1. Direct triple: subject_entity -> predicate -> object (if entities resolved)
        2. Reified statement: For provenance/confidence metadata
        """
        stmt_uri = self.rid_to_uri(stmt['rid'])
        extraction_uri = self.rid_to_uri(extraction_rid)

        subject_text = stmt.get('subject', '')
        predicate_text = stmt.get('predicate', '')
        object_text = stmt.get('object', '')

        # Try to resolve subject and object to entity URIs
        subject_uri = self._resolve_entity(subject_text)
        object_uri = self._resolve_entity(object_text)

        # CREATE DIRECT TRIPLE if subject is an entity
        if subject_uri:
            predicate_uri = self._predicate_to_uri(predicate_text)

            if object_uri:
                # Entity-to-entity relationship
                self.add_triple(subject_uri, predicate_uri, object_uri)
                self.stats['entity_to_entity_links'] += 1
            else:
                # Entity-to-literal relationship
                self.add_triple(subject_uri, predicate_uri, self.escape_literal(object_text))
                self.stats['entity_to_literal_links'] += 1

            self.stats['direct_triples_created'] += 1

        # KEEP REIFIED STATEMENT for provenance and confidence metadata
        self.add_triple(stmt_uri, "rdf:type", "regx:Statement")
        self.add_triple(stmt_uri, "rdf:type", "prov:Entity")

        # Link to resolved entities if available
        if subject_uri:
            self.add_triple(stmt_uri, "regx:subjectEntity", subject_uri)
        else:
            self.add_triple(stmt_uri, "regx:subjectText", self.escape_literal(subject_text))

        if object_uri:
            self.add_triple(stmt_uri, "regx:objectEntity", object_uri)
        else:
            self.add_triple(stmt_uri, "regx:objectText", self.escape_literal(object_text))

        self.add_triple(stmt_uri, "regx:predicate", self.escape_literal(predicate_text))
        self.add_triple(stmt_uri, "regx:statementType", self.escape_literal(stmt.get('statementType', 'claim')))
        self.add_triple(stmt_uri, "regx:confidence", f'"{stmt.get("confidence", 0.0)}"^^xsd:float')

        # Provenance
        self.add_triple(stmt_uri, "prov:wasGeneratedBy", extraction_uri)
        if source_url:
            self.add_triple(stmt_uri, "prov:hadPrimarySource", f"<{source_url}>")

        self.stats['statements_exported'] += 1
        self.stats['reified_statements_kept'] += 1

    def write_turtle(self, output_path: str):
        """Write RDF triples to Turtle file"""
        logger.info(f"Writing {len(self.triples)} triples to {output_path}...")

        with open(output_path, 'w', encoding='utf-8') as f:
            # Write prefixes
            f.write("# KG Extractions exported from PostgreSQL\n")
            f.write(f"# Generated: {datetime.now().isoformat()}\n\n")

            for prefix, uri in NAMESPACES.items():
                f.write(f"@prefix {prefix}: <{uri}> .\n")

            f.write("\n")

            # Write triples
            for triple in self.triples:
                f.write(f"{triple}\n")

        logger.info(f"✅ Successfully wrote {output_path}")


async def main():
    parser = argparse.ArgumentParser(description='Export KG extractions to RDF/Turtle')
    parser.add_argument('--output', '-o', type=str, default='kg-extractions.ttl',
                        help='Output Turtle file path (default: kg-extractions.ttl)')
    parser.add_argument('--db-url', type=str,
                        default=os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza'),
                        help='PostgreSQL connection URL')

    args = parser.parse_args()

    logger.info("=== KG to RDF Export ===")
    logger.info(f"Database: {args.db_url.split('@')[-1]}")  # Hide password
    logger.info(f"Output: {args.output}")

    exporter = KGToRDFExporter(args.db_url)

    try:
        triple_count = await exporter.export_extractions()
        exporter.write_turtle(args.output)

        logger.info("=== Export Complete ===")
        logger.info(f"Total triples: {triple_count}")
        logger.info(f"Output file: {args.output}")

    except Exception as e:
        logger.error(f"Export failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
