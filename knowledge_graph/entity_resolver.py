"""
Entity Resolution for Knowledge Graph

Merges duplicate entities across extractions with CAT receipt tracking.
Implements fuzzy matching to find similar entities and creates canonical RIDs.
"""

import asyncpg
import asyncio
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone
import hashlib
import json
from difflib import SequenceMatcher
from loguru import logger


class EntityResolver:
    """Resolves duplicate entities across KG extractions"""

    def __init__(self, db_url: str, similarity_threshold: float = 0.85):
        """
        Initialize entity resolver

        Args:
            db_url: PostgreSQL connection URL
            similarity_threshold: Minimum similarity score (0-1) to consider entities duplicates
        """
        self.db_url = db_url
        self.similarity_threshold = similarity_threshold

    async def find_duplicate_clusters(self, entity_type: Optional[str] = None) -> List[List[Dict]]:
        """
        Find clusters of duplicate entities across extractions

        Args:
            entity_type: Optional filter by entity type (Person, Organization, Project)

        Returns:
            List of clusters, where each cluster is a list of duplicate entity dicts
        """
        conn = await asyncpg.connect(self.db_url)

        try:
            # Get all entities with their metadata
            query = """
                SELECT
                    e->>'rid' as entity_rid,
                    e->>'type' as entity_type,
                    e->>'name' as entity_name,
                    e->>'confidence' as confidence,
                    kg.extraction_rid,
                    kg.memory_rid,
                    kg.created_at
                FROM koi_kg_extractions kg,
                     jsonb_array_elements(kg.entities) AS e
                WHERE e->>'name' IS NOT NULL
            """

            if entity_type:
                query += f" AND e->>'type' = '{entity_type}'"

            rows = await conn.fetch(query)

            # Convert to list of dicts
            entities = [
                {
                    'rid': row['entity_rid'],
                    'type': row['entity_type'],
                    'name': row['entity_name'],
                    'confidence': float(row['confidence']) if row['confidence'] else 0.0,
                    'extraction_rid': row['extraction_rid'],
                    'memory_rid': row['memory_rid'],
                    'created_at': row['created_at']
                }
                for row in rows
            ]

            logger.info(f"Found {len(entities)} entities{' of type ' + entity_type if entity_type else ''}")

            # Find duplicate clusters using similarity matching
            clusters = self._cluster_duplicates(entities)

            logger.info(f"Found {len(clusters)} duplicate clusters (threshold={self.similarity_threshold})")

            return clusters

        finally:
            await conn.close()

    def _cluster_duplicates(self, entities: List[Dict]) -> List[List[Dict]]:
        """
        Cluster entities by similarity

        Uses single-linkage clustering: if entity A matches B and B matches C,
        then A, B, C are in the same cluster.
        """
        # Group by type first (only compare same types)
        by_type = {}
        for entity in entities:
            entity_type = entity['type']
            if entity_type not in by_type:
                by_type[entity_type] = []
            by_type[entity_type].append(entity)

        all_clusters = []

        for entity_type, type_entities in by_type.items():
            # Build similarity graph
            n = len(type_entities)
            similar = set()  # Set of (i, j) pairs that are similar

            for i in range(n):
                for j in range(i + 1, n):
                    similarity = self._similarity(
                        type_entities[i]['name'],
                        type_entities[j]['name']
                    )
                    if similarity >= self.similarity_threshold:
                        similar.add((i, j))

            # Find connected components (clusters)
            clusters = self._find_connected_components(n, similar)

            # Convert indices back to entity dicts
            for cluster_indices in clusters:
                if len(cluster_indices) > 1:  # Only keep actual duplicates
                    cluster = [type_entities[i] for i in cluster_indices]
                    all_clusters.append(cluster)

        return all_clusters

    def _similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity between two entity names

        Uses SequenceMatcher for fuzzy string matching.
        Normalizes names to lowercase for comparison.
        """
        name1_norm = name1.lower().strip()
        name2_norm = name2.lower().strip()

        # Exact match
        if name1_norm == name2_norm:
            return 1.0

        # Fuzzy match using SequenceMatcher
        return SequenceMatcher(None, name1_norm, name2_norm).ratio()

    def _find_connected_components(self, n: int, edges: set) -> List[List[int]]:
        """
        Find connected components in a graph using Union-Find

        Args:
            n: Number of nodes (0 to n-1)
            edges: Set of (i, j) tuples representing edges

        Returns:
            List of components, where each component is a list of node indices
        """
        parent = list(range(n))

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])  # Path compression
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Build union-find structure
        for i, j in edges:
            union(i, j)

        # Group by root
        components = {}
        for i in range(n):
            root = find(i)
            if root not in components:
                components[root] = []
            components[root].append(i)

        return list(components.values())

    async def resolve_cluster(self, cluster: List[Dict]) -> Tuple[str, List[str]]:
        """
        Resolve a cluster of duplicate entities to a canonical RID

        Args:
            cluster: List of duplicate entity dicts

        Returns:
            Tuple of (canonical_rid, list of resolved RIDs)
        """
        if len(cluster) < 2:
            raise ValueError("Cluster must have at least 2 entities")

        # Determine canonical entity (earliest created, highest confidence)
        canonical = self._determine_canonical(cluster)
        canonical_rid = canonical['rid']

        # Get all non-canonical RIDs
        resolved_rids = [e['rid'] for e in cluster if e['rid'] != canonical_rid]

        logger.info(f"Resolving cluster of {len(cluster)} entities to canonical: {canonical_rid}")
        logger.debug(f"  Canonical: {canonical['name']} (conf={canonical['confidence']:.2f}, created={canonical['created_at']})")
        for entity in cluster:
            if entity['rid'] != canonical_rid:
                logger.debug(f"  Duplicate:  {entity['name']} (conf={entity['confidence']:.2f}, created={entity['created_at']})")

        # Create CAT receipts for each resolution
        conn = await asyncpg.connect(self.db_url)
        try:
            for entity_rid in resolved_rids:
                await self._create_resolution_receipt(
                    conn,
                    input_rid=entity_rid,
                    output_rid=canonical_rid,
                    cluster_size=len(cluster)
                )
        finally:
            await conn.close()

        return canonical_rid, resolved_rids

    def _determine_canonical(self, cluster: List[Dict]) -> Dict:
        """
        Determine canonical entity from cluster

        Prioritization:
        1. Highest confidence score
        2. Earliest creation time
        3. Lexicographically first RID (tie-breaker)
        """
        return max(cluster, key=lambda e: (
            e['confidence'],  # Higher confidence first
            -e['created_at'].timestamp(),  # Earlier creation first (negative to reverse)
            e['rid']  # Lexicographic order as tie-breaker
        ))

    async def _create_resolution_receipt(
        self,
        conn: asyncpg.Connection,
        input_rid: str,
        output_rid: str,
        cluster_size: int
    ) -> str:
        """
        Create CAT receipt for entity resolution transformation

        Args:
            conn: Database connection
            input_rid: Duplicate entity RID
            output_rid: Canonical entity RID
            cluster_size: Size of the duplicate cluster

        Returns:
            Receipt ID (SHA256 hash)
        """
        # Check for existing receipt (deduplication)
        existing = await conn.fetchrow("""
            SELECT receipt_id FROM koi_transformation_receipts
            WHERE input_rid = $1 AND output_rid = $2 AND transformation_type = 'kg_entity_resolution'
        """, input_rid, output_rid)

        if existing:
            logger.debug(f"Receipt already exists: {existing['receipt_id']}")
            return existing['receipt_id']

        # Generate receipt ID using existing pattern
        timestamp = datetime.now(timezone.utc).isoformat()
        content = f"kg_entity_resolution:{input_rid}:{output_rid}:{timestamp}"
        receipt_id = hashlib.sha256(content.encode()).hexdigest()

        # Insert receipt
        await conn.execute("""
            INSERT INTO koi_transformation_receipts (
                receipt_id, transformation_type, input_rid, output_rid,
                processor_name, processor_version,
                metadata, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (receipt_id) DO NOTHING
        """,
            receipt_id,
            'kg_entity_resolution',
            input_rid,
            output_rid,
            'kg-entity-resolver',
            '1.0.0',
            json.dumps({
                'cluster_size': cluster_size,
                'similarity_threshold': self.similarity_threshold,
                'resolution_type': 'duplicate_merge'
            }),
            datetime.now(timezone.utc)
        )

        logger.info(f"Created resolution receipt: {receipt_id} ({input_rid[:30]}... → {output_rid[:30]}...)")

        return receipt_id

    async def resolve_all_duplicates(self, entity_type: Optional[str] = None) -> Dict:
        """
        Find and resolve all duplicate entities

        Args:
            entity_type: Optional filter by entity type

        Returns:
            Dict with resolution statistics
        """
        clusters = await self.find_duplicate_clusters(entity_type)

        stats = {
            'clusters_found': len(clusters),
            'entities_resolved': 0,
            'receipts_created': 0,
            'canonical_entities': []
        }

        for cluster in clusters:
            canonical_rid, resolved_rids = await self.resolve_cluster(cluster)
            stats['entities_resolved'] += len(resolved_rids)
            stats['receipts_created'] += len(resolved_rids)
            stats['canonical_entities'].append({
                'canonical_rid': canonical_rid,
                'resolved_count': len(resolved_rids),
                'cluster_size': len(cluster)
            })

        logger.info(f"Resolution complete: {stats['clusters_found']} clusters, {stats['entities_resolved']} entities resolved")

        return stats


async def main():
    """Test entity resolution"""
    import os

    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    resolver = EntityResolver(db_url, similarity_threshold=0.85)

    # Find duplicates for each type
    for entity_type in ['Person', 'Organization', 'Project']:
        logger.info(f"\n{'='*60}")
        logger.info(f"Finding duplicates for: {entity_type}")
        logger.info(f"{'='*60}")

        stats = await resolver.resolve_all_duplicates(entity_type)

        print(f"\nResults for {entity_type}:")
        print(f"  Clusters found: {stats['clusters_found']}")
        print(f"  Entities resolved: {stats['entities_resolved']}")
        print(f"  Receipts created: {stats['receipts_created']}")

        if stats['canonical_entities']:
            print("\n  Canonical entities:")
            for canonical in stats['canonical_entities'][:5]:
                print(f"    {canonical['canonical_rid'][:50]}... (merged {canonical['resolved_count']} duplicates)")


if __name__ == '__main__':
    asyncio.run(main())
