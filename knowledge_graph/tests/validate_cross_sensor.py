"""
Cross-Sensor Validation Script

Compares KG extraction quality across different sensor types.
Identifies which sensors produce the best structured knowledge.
"""

import asyncio
import asyncpg
import json
import os
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict


class CrossSensorAnalyzer:
    """Analyzes KG extraction quality across sensor types"""

    def __init__(self, db_url: str):
        self.db_url = db_url

    async def analyze_extractions(self):
        """Analyze all KG extractions by sensor type"""

        print("=" * 80)
        print("CROSS-SENSOR KG EXTRACTION QUALITY ANALYSIS")
        print("=" * 80)
        print()

        conn = await asyncpg.connect(self.db_url)
        try:
            # Get all extractions with their source sensor info
            query = """
            SELECT
                e.extraction_rid,
                e.memory_rid,
                e.extraction_type,
                e.entities,
                e.statements,
                e.confidence_score,
                e.tokens_consumed,
                e.cost_usd,
                e.created_at,
                m.source_sensor,
                m.metadata
            FROM koi_kg_extractions e
            JOIN koi_memories m ON e.memory_rid = m.rid
            WHERE m.superseded_at IS NULL
            ORDER BY e.created_at DESC;
            """

            rows = await conn.fetch(query)

            if not rows:
                print("⚠️  No KG extractions found in database.")
                print("   Run test_phase2_validation.py first to generate test data.")
                return

            print(f"📊 Found {len(rows)} KG extractions")
            print()

            # Group by sensor type
            by_sensor = defaultdict(list)

            for row in rows:
                # Determine sensor type from source_sensor
                source_sensor = row['source_sensor']
                sensor_type = self._get_sensor_type(source_sensor)

                entities = json.loads(row['entities']) if isinstance(row['entities'], str) else row['entities']
                statements = json.loads(row['statements']) if isinstance(row['statements'], str) else row['statements']

                by_sensor[sensor_type].append({
                    'extraction_rid': row['extraction_rid'],
                    'entity_count': len(entities),
                    'statement_count': len(statements),
                    'confidence': float(row['confidence_score']),
                    'tokens_consumed': row['tokens_consumed'],
                    'cost_usd': float(row['cost_usd']),
                    'entities': entities,
                    'statements': statements
                })

            # Analyze each sensor type
            self._print_sensor_comparison(by_sensor)
            self._print_entity_analysis(by_sensor)
            self._print_statement_analysis(by_sensor)
            self._print_cost_efficiency(by_sensor)
            self._print_recommendations(by_sensor)
        finally:
            await conn.close()

    def _get_sensor_type(self, source_sensor: str) -> str:
        """Extract sensor type from source_sensor field"""

        if 'website' in source_sensor:
            return 'website'
        elif 'discourse' in source_sensor:
            return 'discourse'
        elif 'github-activity' in source_sensor:
            return 'github-activity'
        elif 'github' in source_sensor:
            return 'github'
        elif 'gitlab' in source_sensor:
            return 'gitlab'
        elif 'notion' in source_sensor:
            return 'notion'
        elif 'podcast' in source_sensor:
            return 'podcast'
        elif 'twitter' in source_sensor:
            return 'twitter'
        elif 'telegram' in source_sensor:
            return 'telegram'
        elif 'medium' in source_sensor:
            return 'medium'
        else:
            return 'unknown'

    def _print_sensor_comparison(self, by_sensor: Dict[str, List[Dict]]):
        """Print comparison across sensor types"""

        print("📊 SENSOR TYPE COMPARISON")
        print("-" * 80)
        print()

        # Calculate aggregates for each sensor
        for sensor_type, extractions in sorted(by_sensor.items()):
            count = len(extractions)
            avg_entities = sum(e['entity_count'] for e in extractions) / count
            avg_statements = sum(e['statement_count'] for e in extractions) / count
            avg_confidence = sum(e['confidence'] for e in extractions) / count
            total_cost = sum(e['cost_usd'] for e in extractions)
            avg_cost = total_cost / count

            print(f"🔹 {sensor_type.upper()}")
            print(f"   Documents: {count}")
            print(f"   Avg Entities: {avg_entities:.1f}")
            print(f"   Avg Statements: {avg_statements:.1f}")
            print(f"   Avg Confidence: {avg_confidence:.3f}")
            print(f"   Avg Cost: ${avg_cost:.6f}")
            print(f"   Total Cost: ${total_cost:.4f}")
            print()

    def _print_entity_analysis(self, by_sensor: Dict[str, List[Dict]]):
        """Analyze entity extraction patterns"""

        print("👥 ENTITY EXTRACTION ANALYSIS")
        print("-" * 80)
        print()

        for sensor_type, extractions in sorted(by_sensor.items()):
            # Count entity types
            entity_types = defaultdict(int)
            for extraction in extractions:
                for entity in extraction['entities']:
                    entity_type = entity.get('type', 'unknown')
                    entity_types[entity_type] += 1

            if entity_types:
                print(f"🔹 {sensor_type.upper()}")
                for etype, count in sorted(entity_types.items(), key=lambda x: x[1], reverse=True):
                    print(f"   {etype}: {count}")
                print()

    def _print_statement_analysis(self, by_sensor: Dict[str, List[Dict]]):
        """Analyze statement extraction patterns"""

        print("💬 STATEMENT EXTRACTION ANALYSIS")
        print("-" * 80)
        print()

        for sensor_type, extractions in sorted(by_sensor.items()):
            # Count statement types
            statement_types = defaultdict(int)
            for extraction in extractions:
                for statement in extraction['statements']:
                    stmt_type = statement.get('statementType', 'unknown')
                    statement_types[stmt_type] += 1

            if statement_types:
                print(f"🔹 {sensor_type.upper()}")
                for stype, count in sorted(statement_types.items(), key=lambda x: x[1], reverse=True):
                    print(f"   {stype}: {count}")
                print()

    def _print_cost_efficiency(self, by_sensor: Dict[str, List[Dict]]):
        """Analyze cost efficiency"""

        print("💰 COST EFFICIENCY ANALYSIS")
        print("-" * 80)
        print()

        # Calculate cost per entity and per statement
        efficiency_data = []

        for sensor_type, extractions in sorted(by_sensor.items()):
            total_cost = sum(e['cost_usd'] for e in extractions)
            total_entities = sum(e['entity_count'] for e in extractions)
            total_statements = sum(e['statement_count'] for e in extractions)

            cost_per_entity = total_cost / total_entities if total_entities > 0 else 0
            cost_per_statement = total_cost / total_statements if total_statements > 0 else 0
            cost_per_extraction = total_cost / len(extractions) if extractions else 0

            efficiency_data.append({
                'sensor_type': sensor_type,
                'cost_per_entity': cost_per_entity,
                'cost_per_statement': cost_per_statement,
                'cost_per_extraction': cost_per_extraction,
                'total_entities': total_entities,
                'total_statements': total_statements
            })

        # Sort by cost per extraction
        efficiency_data.sort(key=lambda x: x['cost_per_extraction'])

        for data in efficiency_data:
            print(f"🔹 {data['sensor_type'].upper()}")
            print(f"   Cost/Extraction: ${data['cost_per_extraction']:.6f}")
            print(f"   Cost/Entity: ${data['cost_per_entity']:.6f}")
            print(f"   Cost/Statement: ${data['cost_per_statement']:.6f}")
            print(f"   Total Extracted: {data['total_entities']} entities, {data['total_statements']} statements")
            print()

    def _print_recommendations(self, by_sensor: Dict[str, List[Dict]]):
        """Print recommendations based on analysis"""

        print("💡 RECOMMENDATIONS")
        print("-" * 80)
        print()

        # Find best performing sensors
        sensor_scores = {}

        for sensor_type, extractions in by_sensor.items():
            if not extractions:
                continue

            avg_entities = sum(e['entity_count'] for e in extractions) / len(extractions)
            avg_statements = sum(e['statement_count'] for e in extractions) / len(extractions)
            avg_confidence = sum(e['confidence'] for e in extractions) / len(extractions)

            # Composite score (higher is better)
            score = (avg_entities + avg_statements) * avg_confidence

            sensor_scores[sensor_type] = {
                'score': score,
                'avg_entities': avg_entities,
                'avg_statements': avg_statements,
                'avg_confidence': avg_confidence
            }

        # Sort by score
        ranked = sorted(sensor_scores.items(), key=lambda x: x[1]['score'], reverse=True)

        print("🏆 Sensor Performance Ranking (by knowledge extraction quality):")
        print()
        for i, (sensor_type, metrics) in enumerate(ranked, 1):
            print(f"   {i}. {sensor_type.upper()}")
            print(f"      Score: {metrics['score']:.2f}")
            print(f"      Avg Entities: {metrics['avg_entities']:.1f}")
            print(f"      Avg Statements: {metrics['avg_statements']:.1f}")
            print(f"      Avg Confidence: {metrics['avg_confidence']:.3f}")
            print()

        if ranked:
            best = ranked[0][0]
            worst = ranked[-1][0] if len(ranked) > 1 else None

            print(f"✅ Best performing sensor: {best.upper()}")
            if worst and worst != best:
                print(f"⚠️  Lowest performing sensor: {worst.upper()}")
                print(f"   Consider reviewing extraction prompts or sensor data quality")
            print()

        print("📋 Next Steps:")
        print("   1. Review entity/statement types extracted from each sensor")
        print("   2. Identify sensors with low confidence scores")
        print("   3. Adjust extraction prompts for specific sensor types if needed")
        print("   4. Consider cost-efficiency when prioritizing which sensors to process")
        print()


async def main():
    """Main analyzer runner"""

    # Get database URL from environment
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    # Create analyzer
    analyzer = CrossSensorAnalyzer(db_url)

    # Run analysis
    await analyzer.analyze_extractions()


if __name__ == "__main__":
    asyncio.run(main())
