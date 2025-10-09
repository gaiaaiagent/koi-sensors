"""
Cost & Performance Metrics Report Generator

Generates a comprehensive report on KG extraction costs, performance, and quality metrics.
"""

import asyncio
import asyncpg
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import sys


class MetricsReportGenerator:
    """Generates comprehensive metrics report for KG extraction"""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.metrics = {}

    async def collect_metrics(self):
        """Collect all metrics from database"""

        async with asyncpg.connect(self.db_url) as conn:
            # Overall metrics
            self.metrics['overall'] = await self._collect_overall_metrics(conn)

            # Sensor-specific metrics
            self.metrics['by_sensor'] = await self._collect_sensor_metrics(conn)

            # Temporal metrics
            self.metrics['temporal'] = await self._collect_temporal_metrics(conn)

            # Quality metrics
            self.metrics['quality'] = await self._collect_quality_metrics(conn)

            # Cost analysis
            self.metrics['costs'] = await self._collect_cost_metrics(conn)

            # Provenance metrics
            self.metrics['provenance'] = await self._collect_provenance_metrics(conn)

    async def _collect_overall_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect overall system metrics"""

        # Total extractions
        total_extractions = await conn.fetchval("""
            SELECT COUNT(*) FROM koi_kg_extractions
        """)

        # Total entities and statements
        entity_statement_counts = await conn.fetchrow("""
            SELECT
                SUM(JSONB_ARRAY_LENGTH(entities)) as total_entities,
                SUM(JSONB_ARRAY_LENGTH(statements)) as total_statements
            FROM koi_kg_extractions
        """)

        # Average metrics
        avg_metrics = await conn.fetchrow("""
            SELECT
                AVG(confidence_score) as avg_confidence,
                AVG(JSONB_ARRAY_LENGTH(entities)) as avg_entities,
                AVG(JSONB_ARRAY_LENGTH(statements)) as avg_statements,
                AVG(tokens_consumed) as avg_tokens,
                AVG(cost_usd) as avg_cost
            FROM koi_kg_extractions
        """)

        # Total costs
        total_cost = await conn.fetchval("""
            SELECT SUM(cost_usd) FROM koi_kg_extractions
        """) or 0.0

        total_tokens = await conn.fetchval("""
            SELECT SUM(tokens_consumed) FROM koi_kg_extractions
        """) or 0

        return {
            'total_extractions': total_extractions or 0,
            'total_entities': int(entity_statement_counts['total_entities'] or 0),
            'total_statements': int(entity_statement_counts['total_statements'] or 0),
            'avg_confidence': float(avg_metrics['avg_confidence'] or 0),
            'avg_entities_per_doc': float(avg_metrics['avg_entities'] or 0),
            'avg_statements_per_doc': float(avg_metrics['avg_statements'] or 0),
            'avg_tokens_per_doc': float(avg_metrics['avg_tokens'] or 0),
            'avg_cost_per_doc': float(avg_metrics['avg_cost'] or 0),
            'total_cost_usd': float(total_cost),
            'total_tokens': int(total_tokens)
        }

    async def _collect_sensor_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect metrics by sensor type"""

        rows = await conn.fetch("""
            SELECT
                CASE
                    WHEN m.source_sensor LIKE 'website%' THEN 'website'
                    WHEN m.source_sensor LIKE 'discourse%' THEN 'discourse'
                    WHEN m.source_sensor LIKE 'github-activity%' THEN 'github-activity'
                    WHEN m.source_sensor LIKE 'github%' THEN 'github'
                    WHEN m.source_sensor LIKE 'gitlab%' THEN 'gitlab'
                    WHEN m.source_sensor LIKE 'notion%' THEN 'notion'
                    WHEN m.source_sensor LIKE 'podcast%' THEN 'podcast'
                    ELSE 'other'
                END as sensor_type,
                COUNT(*) as extraction_count,
                AVG(e.confidence_score) as avg_confidence,
                SUM(JSONB_ARRAY_LENGTH(e.entities)) as total_entities,
                SUM(JSONB_ARRAY_LENGTH(e.statements)) as total_statements,
                AVG(JSONB_ARRAY_LENGTH(e.entities)) as avg_entities,
                AVG(JSONB_ARRAY_LENGTH(e.statements)) as avg_statements,
                SUM(e.tokens_consumed) as total_tokens,
                SUM(e.cost_usd) as total_cost,
                AVG(e.cost_usd) as avg_cost
            FROM koi_kg_extractions e
            JOIN koi_memories m ON e.memory_rid = m.rid
            GROUP BY sensor_type
            ORDER BY extraction_count DESC
        """)

        by_sensor = {}
        for row in rows:
            by_sensor[row['sensor_type']] = {
                'extraction_count': row['extraction_count'],
                'avg_confidence': float(row['avg_confidence'] or 0),
                'total_entities': int(row['total_entities'] or 0),
                'total_statements': int(row['total_statements'] or 0),
                'avg_entities': float(row['avg_entities'] or 0),
                'avg_statements': float(row['avg_statements'] or 0),
                'total_tokens': int(row['total_tokens'] or 0),
                'total_cost_usd': float(row['total_cost'] or 0),
                'avg_cost_usd': float(row['avg_cost'] or 0)
            }

        return by_sensor

    async def _collect_temporal_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect temporal metrics (daily/hourly)"""

        # Extractions by day
        by_day = await conn.fetch("""
            SELECT
                DATE(created_at) as date,
                COUNT(*) as extraction_count,
                SUM(cost_usd) as daily_cost,
                AVG(confidence_score) as avg_confidence
            FROM koi_kg_extractions
            GROUP BY DATE(created_at)
            ORDER BY date DESC
            LIMIT 30
        """)

        # Extractions by hour (last 24 hours)
        by_hour = await conn.fetch("""
            SELECT
                DATE_TRUNC('hour', created_at) as hour,
                COUNT(*) as extraction_count,
                SUM(cost_usd) as hourly_cost
            FROM koi_kg_extractions
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            GROUP BY hour
            ORDER BY hour DESC
        """)

        return {
            'by_day': [
                {
                    'date': str(row['date']),
                    'extraction_count': row['extraction_count'],
                    'daily_cost': float(row['daily_cost'] or 0),
                    'avg_confidence': float(row['avg_confidence'] or 0)
                }
                for row in by_day
            ],
            'by_hour': [
                {
                    'hour': str(row['hour']),
                    'extraction_count': row['extraction_count'],
                    'hourly_cost': float(row['hourly_cost'] or 0)
                }
                for row in by_hour
            ]
        }

    async def _collect_quality_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect quality-related metrics"""

        # Confidence distribution
        confidence_dist = await conn.fetch("""
            SELECT
                CASE
                    WHEN confidence_score >= 0.9 THEN 'excellent (0.9-1.0)'
                    WHEN confidence_score >= 0.8 THEN 'good (0.8-0.9)'
                    WHEN confidence_score >= 0.7 THEN 'fair (0.7-0.8)'
                    ELSE 'poor (<0.7)'
                END as confidence_range,
                COUNT(*) as count
            FROM koi_kg_extractions
            GROUP BY confidence_range
            ORDER BY MIN(confidence_score) DESC
        """)

        # Entity type distribution (if available)
        # This requires parsing JSON, which we'll do in Python
        extractions = await conn.fetch("""
            SELECT entities, statements FROM koi_kg_extractions
        """)

        entity_types = {}
        statement_types = {}

        for extraction in extractions:
            # Parse entities
            entities = json.loads(extraction['entities']) if isinstance(extraction['entities'], str) else extraction['entities']
            for entity in entities:
                etype = entity.get('type', 'unknown')
                entity_types[etype] = entity_types.get(etype, 0) + 1

            # Parse statements
            statements = json.loads(extraction['statements']) if isinstance(extraction['statements'], str) else extraction['statements']
            for statement in statements:
                stype = statement.get('statementType', 'unknown')
                statement_types[stype] = statement_types.get(stype, 0) + 1

        return {
            'confidence_distribution': [
                {
                    'range': row['confidence_range'],
                    'count': row['count']
                }
                for row in confidence_dist
            ],
            'entity_types': entity_types,
            'statement_types': statement_types
        }

    async def _collect_cost_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect cost analysis metrics"""

        # Total cost breakdown
        cost_breakdown = await conn.fetchrow("""
            SELECT
                SUM(cost_usd) as total_cost,
                SUM(tokens_consumed) as total_tokens,
                AVG(cost_usd) as avg_cost_per_extraction,
                MIN(cost_usd) as min_cost,
                MAX(cost_usd) as max_cost
            FROM koi_kg_extractions
        """)

        # Cost per entity/statement
        per_unit_cost = await conn.fetchrow("""
            SELECT
                SUM(cost_usd) / NULLIF(SUM(JSONB_ARRAY_LENGTH(entities)), 0) as cost_per_entity,
                SUM(cost_usd) / NULLIF(SUM(JSONB_ARRAY_LENGTH(statements)), 0) as cost_per_statement
            FROM koi_kg_extractions
        """)

        # Projected monthly cost (based on current rate)
        total_cost = float(cost_breakdown['total_cost'] or 0)
        total_extractions = await conn.fetchval("SELECT COUNT(*) FROM koi_kg_extractions") or 1
        avg_cost = total_cost / total_extractions

        # Get first and last extraction dates
        date_range = await conn.fetchrow("""
            SELECT MIN(created_at) as first_extraction, MAX(created_at) as last_extraction
            FROM koi_kg_extractions
        """)

        if date_range['first_extraction'] and date_range['last_extraction']:
            days_active = (date_range['last_extraction'] - date_range['first_extraction']).days or 1
            daily_avg_extractions = total_extractions / days_active
            projected_monthly_cost = daily_avg_extractions * avg_cost * 30
        else:
            projected_monthly_cost = 0.0

        return {
            'total_cost_usd': float(cost_breakdown['total_cost'] or 0),
            'total_tokens': int(cost_breakdown['total_tokens'] or 0),
            'avg_cost_per_extraction': float(cost_breakdown['avg_cost_per_extraction'] or 0),
            'min_cost': float(cost_breakdown['min_cost'] or 0),
            'max_cost': float(cost_breakdown['max_cost'] or 0),
            'cost_per_entity': float(per_unit_cost['cost_per_entity'] or 0),
            'cost_per_statement': float(per_unit_cost['cost_per_statement'] or 0),
            'projected_monthly_cost_usd': float(projected_monthly_cost)
        }

    async def _collect_provenance_metrics(self, conn: asyncpg.Connection) -> Dict[str, Any]:
        """Collect provenance tracking metrics"""

        # Source URL coverage
        url_coverage = await conn.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN m.metadata->>'url' IS NOT NULL THEN 1 END) as with_url
            FROM koi_kg_extractions e
            JOIN koi_memories m ON e.memory_rid = m.rid
        """)

        # CAT receipt coverage
        receipt_coverage = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT e.extraction_rid) as total_extractions,
                COUNT(DISTINCT r.receipt_id) as with_receipts
            FROM koi_kg_extractions e
            LEFT JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid
        """)

        # RID validity
        rid_validity = await conn.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN extraction_rid LIKE memory_rid || ':kg:%:v%' THEN 1 END) as valid_rids
            FROM koi_kg_extractions
        """)

        # Orphaned records
        orphaned = await conn.fetchval("""
            SELECT COUNT(*)
            FROM koi_kg_extractions e
            WHERE NOT EXISTS (
                SELECT 1 FROM koi_memories m WHERE m.rid = e.memory_rid
            )
        """) or 0

        return {
            'url_coverage_percent': round(100.0 * url_coverage['with_url'] / url_coverage['total'], 2) if url_coverage['total'] > 0 else 0,
            'receipt_coverage_percent': round(100.0 * receipt_coverage['with_receipts'] / receipt_coverage['total_extractions'], 2) if receipt_coverage['total_extractions'] > 0 else 0,
            'rid_validity_percent': round(100.0 * rid_validity['valid_rids'] / rid_validity['total'], 2) if rid_validity['total'] > 0 else 0,
            'orphaned_records': orphaned
        }

    def print_report(self):
        """Print formatted metrics report"""

        print()
        print("=" * 100)
        print(" " * 35 + "KG EXTRACTION METRICS REPORT")
        print("=" * 100)
        print()
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # Overall metrics
        print("📊 OVERALL METRICS")
        print("-" * 100)
        overall = self.metrics['overall']
        print(f"  Total Extractions:        {overall['total_extractions']:,}")
        print(f"  Total Entities Extracted: {overall['total_entities']:,}")
        print(f"  Total Statements:         {overall['total_statements']:,}")
        print(f"  Avg Entities/Doc:         {overall['avg_entities_per_doc']:.1f}")
        print(f"  Avg Statements/Doc:       {overall['avg_statements_per_doc']:.1f}")
        print(f"  Avg Confidence Score:     {overall['avg_confidence']:.3f}")
        print()

        # Cost metrics
        print("💰 COST ANALYSIS")
        print("-" * 100)
        costs = self.metrics['costs']
        print(f"  Total Cost:               ${costs['total_cost_usd']:.4f}")
        print(f"  Total Tokens Consumed:    {costs['total_tokens']:,}")
        print(f"  Avg Cost/Document:        ${costs['avg_cost_per_extraction']:.6f}")
        print(f"  Cost/Entity:              ${costs['cost_per_entity']:.6f}")
        print(f"  Cost/Statement:           ${costs['cost_per_statement']:.6f}")
        print(f"  Projected Monthly Cost:   ${costs['projected_monthly_cost_usd']:.2f}")
        print()

        # Provenance metrics
        print("🔗 PROVENANCE TRACKING")
        print("-" * 100)
        prov = self.metrics['provenance']
        print(f"  Source URL Coverage:      {prov['url_coverage_percent']:.1f}%")
        print(f"  CAT Receipt Coverage:     {prov['receipt_coverage_percent']:.1f}%")
        print(f"  RID Validity:             {prov['rid_validity_percent']:.1f}%")
        print(f"  Orphaned Records:         {prov['orphaned_records']}")
        print()

        # Sensor metrics
        if self.metrics['by_sensor']:
            print("📡 METRICS BY SENSOR TYPE")
            print("-" * 100)
            for sensor_type, metrics in sorted(self.metrics['by_sensor'].items(), key=lambda x: x[1]['extraction_count'], reverse=True):
                print(f"  {sensor_type.upper()}:")
                print(f"    Extractions:       {metrics['extraction_count']:,}")
                print(f"    Entities:          {metrics['total_entities']:,} (avg {metrics['avg_entities']:.1f}/doc)")
                print(f"    Statements:        {metrics['total_statements']:,} (avg {metrics['avg_statements']:.1f}/doc)")
                print(f"    Avg Confidence:    {metrics['avg_confidence']:.3f}")
                print(f"    Total Cost:        ${metrics['total_cost_usd']:.4f} (avg ${metrics['avg_cost_usd']:.6f}/doc)")
                print()

        # Quality distribution
        print("📈 QUALITY DISTRIBUTION")
        print("-" * 100)
        for dist in self.metrics['quality']['confidence_distribution']:
            print(f"  {dist['range']:20s} {dist['count']:,}")
        print()

        # Entity types
        if self.metrics['quality']['entity_types']:
            print("👥 ENTITY TYPES EXTRACTED")
            print("-" * 100)
            for etype, count in sorted(self.metrics['quality']['entity_types'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {etype:30s} {count:,}")
            print()

        # Statement types
        if self.metrics['quality']['statement_types']:
            print("💬 STATEMENT TYPES EXTRACTED")
            print("-" * 100)
            for stype, count in sorted(self.metrics['quality']['statement_types'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {stype:30s} {count:,}")
            print()

        print("=" * 100)
        print()

    async def save_report(self, output_file: str = "kg_metrics_report.json"):
        """Save metrics to JSON file"""

        output_path = Path(__file__).parent / output_file

        # Add metadata
        report = {
            'generated_at': datetime.now().isoformat(),
            'metrics': self.metrics
        }

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"📄 Report saved to: {output_path}")


async def main():
    """Main report generator"""

    # Get database URL
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    print("Collecting metrics from database...")

    # Create generator
    generator = MetricsReportGenerator(db_url)

    # Collect metrics
    await generator.collect_metrics()

    # Print report
    generator.print_report()

    # Save to file
    await generator.save_report()


if __name__ == "__main__":
    asyncio.run(main())
