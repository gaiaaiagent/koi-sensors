"""
KG Metrics Collection and Monitoring

Collects daily metrics for Knowledge Graph operations:
- Extraction counts and quality
- Entity resolution statistics
- Contradiction detection results
- Cost tracking
- Provenance completeness
"""

import asyncpg
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from loguru import logger
import json
import os


class KGMetricsCollector:
    """Collects and aggregates KG metrics"""

    def __init__(self, db_url: str):
        """
        Initialize metrics collector

        Args:
            db_url: PostgreSQL connection URL
        """
        self.db_url = db_url

    async def collect_daily_metrics(self, date: Optional[datetime] = None) -> Dict:
        """
        Collect all KG metrics for a specific date

        Args:
            date: Date to collect metrics for (defaults to today)

        Returns:
            Dict with all metrics
        """
        if date is None:
            date = datetime.now(timezone.utc)

        # Get date range (full day)
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        conn = await asyncpg.connect(self.db_url)

        try:
            metrics = {
                'date': start_of_day.isoformat(),
                'extraction_metrics': await self._collect_extraction_metrics(conn, start_of_day, end_of_day),
                'entity_metrics': await self._collect_entity_metrics(conn, start_of_day, end_of_day),
                'resolution_metrics': await self._collect_resolution_metrics(conn, start_of_day, end_of_day),
                'contradiction_metrics': await self._collect_contradiction_metrics(conn, start_of_day, end_of_day),
                'cost_metrics': await self._collect_cost_metrics(conn, start_of_day, end_of_day),
                'provenance_metrics': await self._collect_provenance_metrics(conn, start_of_day, end_of_day)
            }

            logger.info(f"Collected metrics for {start_of_day.date()}")

            return metrics

        finally:
            await conn.close()

    async def _collect_extraction_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect KG extraction metrics"""

        # Overall extraction stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_extractions,
                COUNT(DISTINCT memory_rid) as unique_memories,
                AVG(confidence_score) as avg_confidence,
                SUM(jsonb_array_length(COALESCE(entities, '[]'::jsonb))) as total_entities,
                SUM(jsonb_array_length(COALESCE(statements, '[]'::jsonb))) as total_statements,
                SUM(jsonb_array_length(COALESCE(relations, '[]'::jsonb))) as total_relations
            FROM koi_kg_extractions
            WHERE created_at >= $1 AND created_at < $2
        """, start, end)

        # By extraction type
        by_type = await conn.fetch("""
            SELECT
                extraction_type,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM koi_kg_extractions
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY extraction_type
        """, start, end)

        return {
            'total_extractions': stats['total_extractions'],
            'unique_memories': stats['unique_memories'],
            'avg_confidence': float(stats['avg_confidence']) if stats['avg_confidence'] else 0.0,
            'total_entities': stats['total_entities'] or 0,
            'total_statements': stats['total_statements'] or 0,
            'total_relations': stats['total_relations'] or 0,
            'by_type': [
                {
                    'type': row['extraction_type'],
                    'count': row['count'],
                    'avg_confidence': float(row['avg_confidence']) if row['avg_confidence'] else 0.0
                }
                for row in by_type
            ]
        }

    async def _collect_entity_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect entity extraction metrics"""

        # Entity type distribution
        entity_types = await conn.fetch("""
            SELECT
                e->>'type' as entity_type,
                COUNT(*) as count,
                AVG(CAST(e->>'confidence' AS FLOAT)) as avg_confidence
            FROM koi_kg_extractions kg,
                 jsonb_array_elements(kg.entities) AS e
            WHERE kg.created_at >= $1 AND kg.created_at < $2
              AND e->>'type' IS NOT NULL
            GROUP BY e->>'type'
            ORDER BY COUNT(*) DESC
        """, start, end)

        # Top entities by frequency
        top_entities = await conn.fetch("""
            SELECT
                e->>'type' as entity_type,
                e->>'name' as entity_name,
                COUNT(*) as occurrences,
                AVG(CAST(e->>'confidence' AS FLOAT)) as avg_confidence
            FROM koi_kg_extractions kg,
                 jsonb_array_elements(kg.entities) AS e
            WHERE kg.created_at >= $1 AND kg.created_at < $2
              AND e->>'name' IS NOT NULL
            GROUP BY e->>'type', e->>'name'
            ORDER BY COUNT(*) DESC
            LIMIT 20
        """, start, end)

        return {
            'by_type': [
                {
                    'type': row['entity_type'],
                    'count': row['count'],
                    'avg_confidence': float(row['avg_confidence']) if row['avg_confidence'] else 0.0
                }
                for row in entity_types
            ],
            'top_entities': [
                {
                    'type': row['entity_type'],
                    'name': row['entity_name'],
                    'occurrences': row['occurrences'],
                    'avg_confidence': float(row['avg_confidence']) if row['avg_confidence'] else 0.0
                }
                for row in top_entities
            ]
        }

    async def _collect_resolution_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect entity resolution metrics"""

        # Resolution stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_resolutions,
                COUNT(DISTINCT input_rid) as entities_resolved,
                COUNT(DISTINCT output_rid) as canonical_entities
            FROM koi_transformation_receipts
            WHERE transformation_type = 'kg_entity_resolution'
              AND created_at >= $1 AND created_at < $2
        """, start, end)

        # By cluster size
        by_cluster = await conn.fetch("""
            SELECT
                CAST(metadata->>'cluster_size' AS INT) as cluster_size,
                COUNT(*) as count
            FROM koi_transformation_receipts
            WHERE transformation_type = 'kg_entity_resolution'
              AND created_at >= $1 AND created_at < $2
              AND metadata->>'cluster_size' IS NOT NULL
            GROUP BY CAST(metadata->>'cluster_size' AS INT)
            ORDER BY cluster_size DESC
        """, start, end)

        return {
            'total_resolutions': stats['total_resolutions'],
            'entities_resolved': stats['entities_resolved'],
            'canonical_entities': stats['canonical_entities'],
            'by_cluster_size': [
                {
                    'cluster_size': row['cluster_size'],
                    'count': row['count']
                }
                for row in by_cluster
            ]
        }

    async def _collect_contradiction_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect contradiction detection metrics"""

        # Contradiction stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_contradictions,
                COUNT(CASE WHEN resolved = true THEN 1 END) as resolved_count,
                COUNT(CASE WHEN resolved = false THEN 1 END) as unresolved_count
            FROM koi_kg_contradictions
            WHERE created_at >= $1 AND created_at < $2
        """, start, end)

        # By type
        by_type = await conn.fetch("""
            SELECT
                contradiction_type,
                COUNT(*) as count,
                AVG(CAST(contradiction_details->>'confidence_score' AS FLOAT)) as avg_confidence
            FROM koi_kg_contradictions
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY contradiction_type
        """, start, end)

        return {
            'total_contradictions': stats['total_contradictions'],
            'resolved': stats['resolved_count'],
            'unresolved': stats['unresolved_count'],
            'by_type': [
                {
                    'type': row['contradiction_type'],
                    'count': row['count'],
                    'avg_confidence': float(row['avg_confidence']) if row['avg_confidence'] else 0.0
                }
                for row in by_type
            ]
        }

    async def _collect_cost_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect cost and resource usage metrics"""

        # Extraction costs
        extraction_cost = await conn.fetchrow("""
            SELECT
                SUM(tokens_consumed) as total_tokens,
                SUM(cost_usd) as total_cost,
                AVG(cost_usd) as avg_cost_per_extraction
            FROM koi_kg_extractions
            WHERE created_at >= $1 AND created_at < $2
        """, start, end)

        # By extractor version
        by_version = await conn.fetch("""
            SELECT
                extractor_version,
                COUNT(*) as extractions,
                SUM(tokens_consumed) as tokens,
                SUM(cost_usd) as cost
            FROM koi_kg_extractions
            WHERE created_at >= $1 AND created_at < $2
            GROUP BY extractor_version
        """, start, end)

        return {
            'total_tokens': extraction_cost['total_tokens'] or 0,
            'total_cost_usd': float(extraction_cost['total_cost']) if extraction_cost['total_cost'] else 0.0,
            'avg_cost_per_extraction': float(extraction_cost['avg_cost_per_extraction']) if extraction_cost['avg_cost_per_extraction'] else 0.0,
            'by_extractor_version': [
                {
                    'version': row['extractor_version'],
                    'extractions': row['extractions'],
                    'tokens': row['tokens'] or 0,
                    'cost_usd': float(row['cost']) if row['cost'] else 0.0
                }
                for row in by_version
            ]
        }

    async def _collect_provenance_metrics(
        self,
        conn: asyncpg.Connection,
        start: datetime,
        end: datetime
    ) -> Dict:
        """Collect provenance tracking metrics"""

        # CAT receipt stats
        receipt_stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_receipts,
                COUNT(DISTINCT transformation_type) as transformation_types
            FROM koi_transformation_receipts
            WHERE transformation_type LIKE 'kg_%'
              AND created_at >= $1 AND created_at < $2
        """, start, end)

        # Check provenance completeness
        completeness = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT kg.extraction_rid) as extractions_with_receipts,
                (SELECT COUNT(*) FROM koi_kg_extractions
                 WHERE created_at >= $1 AND created_at < $2) as total_extractions
            FROM koi_kg_extractions kg
            JOIN koi_transformation_receipts r ON r.output_rid = kg.extraction_rid
            WHERE kg.created_at >= $1 AND kg.created_at < $2
        """, start, end)

        total = completeness['total_extractions'] or 0
        with_receipts = completeness['extractions_with_receipts'] or 0
        completeness_pct = (with_receipts / total * 100) if total > 0 else 0.0

        return {
            'total_cat_receipts': receipt_stats['total_receipts'],
            'transformation_types': receipt_stats['transformation_types'],
            'provenance_completeness': {
                'total_extractions': total,
                'with_receipts': with_receipts,
                'completeness_percentage': completeness_pct
            }
        }

    async def get_all_time_stats(self) -> Dict:
        """Get cumulative all-time statistics"""
        conn = await asyncpg.connect(self.db_url)

        try:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total_extractions,
                    COUNT(DISTINCT memory_rid) as unique_memories,
                    SUM(jsonb_array_length(COALESCE(entities, '[]'::jsonb))) as total_entities,
                    SUM(jsonb_array_length(COALESCE(statements, '[]'::jsonb))) as total_statements,
                    AVG(confidence_score) as avg_confidence,
                    SUM(tokens_consumed) as total_tokens,
                    SUM(cost_usd) as total_cost
                FROM koi_kg_extractions
            """)

            resolutions = await conn.fetchval("""
                SELECT COUNT(*) FROM koi_transformation_receipts
                WHERE transformation_type = 'kg_entity_resolution'
            """)

            contradictions = await conn.fetchval("""
                SELECT COUNT(*) FROM koi_kg_contradictions
            """)

            return {
                'total_extractions': stats['total_extractions'],
                'unique_memories': stats['unique_memories'],
                'total_entities': stats['total_entities'] or 0,
                'total_statements': stats['total_statements'] or 0,
                'avg_confidence': float(stats['avg_confidence']) if stats['avg_confidence'] else 0.0,
                'total_tokens': stats['total_tokens'] or 0,
                'total_cost_usd': float(stats['total_cost']) if stats['total_cost'] else 0.0,
                'entity_resolutions': resolutions,
                'contradictions_detected': contradictions
            }

        finally:
            await conn.close()

    async def export_metrics_to_json(self, filepath: str, date: Optional[datetime] = None):
        """Export metrics to JSON file"""
        metrics = await self.collect_daily_metrics(date)

        with open(filepath, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"Exported metrics to {filepath}")


async def main():
    """Test metrics collection"""
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    collector = KGMetricsCollector(db_url)

    # Get all-time stats
    logger.info("Collecting all-time statistics...")
    all_time = await collector.get_all_time_stats()

    print("\n" + "="*60)
    print("KG METRICS - ALL TIME")
    print("="*60)
    print(f"Total Extractions:       {all_time['total_extractions']}")
    print(f"Unique Memories:         {all_time['unique_memories']}")
    print(f"Total Entities:          {all_time['total_entities']}")
    print(f"Total Statements:        {all_time['total_statements']}")
    print(f"Average Confidence:      {all_time['avg_confidence']:.3f}")
    print(f"Total Tokens:            {all_time['total_tokens']:,}")
    print(f"Total Cost:              ${all_time['total_cost_usd']:.4f}")
    print(f"Entity Resolutions:      {all_time['entity_resolutions']}")
    print(f"Contradictions Detected: {all_time['contradictions_detected']}")

    # Get today's metrics
    logger.info("\nCollecting today's metrics...")
    daily = await collector.collect_daily_metrics()

    print("\n" + "="*60)
    print("KG METRICS - TODAY")
    print("="*60)
    print(f"\nExtractions: {daily['extraction_metrics']['total_extractions']}")
    print(f"  Entities:   {daily['extraction_metrics']['total_entities']}")
    print(f"  Statements: {daily['extraction_metrics']['total_statements']}")
    print(f"  Confidence: {daily['extraction_metrics']['avg_confidence']:.3f}")

    print(f"\nEntity Types:")
    for et in daily['entity_metrics']['by_type'][:5]:
        print(f"  {et['type']:15s}: {et['count']:3d} (conf={et['avg_confidence']:.2f})")

    print(f"\nResolutions: {daily['resolution_metrics']['total_resolutions']}")
    print(f"  Entities resolved: {daily['resolution_metrics']['entities_resolved']}")
    print(f"  Canonical entities: {daily['resolution_metrics']['canonical_entities']}")

    print(f"\nContradictions: {daily['contradiction_metrics']['total_contradictions']}")
    print(f"  Resolved: {daily['contradiction_metrics']['resolved']}")
    print(f"  Unresolved: {daily['contradiction_metrics']['unresolved']}")

    print(f"\nCosts:")
    print(f"  Total tokens: {daily['cost_metrics']['total_tokens']:,}")
    print(f"  Total cost: ${daily['cost_metrics']['total_cost_usd']:.4f}")
    print(f"  Avg per extraction: ${daily['cost_metrics']['avg_cost_per_extraction']:.4f}")

    print(f"\nProvenance:")
    prov = daily['provenance_metrics']['provenance_completeness']
    print(f"  Completeness: {prov['completeness_percentage']:.1f}%")
    print(f"  ({prov['with_receipts']}/{prov['total_extractions']} extractions)")

    # Export to file
    output_file = '/opt/projects/koi-sensors/knowledge_graph/monitoring/metrics_today.json'
    await collector.export_metrics_to_json(output_file)
    print(f"\n✓ Metrics exported to {output_file}")


if __name__ == '__main__':
    asyncio.run(main())
