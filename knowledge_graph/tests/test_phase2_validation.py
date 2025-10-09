"""
Phase 2 Validation Test Suite

Tests KG extraction on real scraped data from multiple sensor types.
Validates database storage, CAT receipts, RIDs, and provenance tracking.
"""

import asyncio
import asyncpg
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add koi-sensors to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from knowledge_graph.extractors.pass_a_extractor import PassAExtractor
from knowledge_graph.kg_rid_generator import validate_kg_rid, parse_kg_rid


class Phase2Validator:
    """Validates Phase 2 KG extraction on real sensor data"""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.extractor = PassAExtractor(db_url=db_url)
        self.results = {
            'total_tested': 0,
            'successful': 0,
            'failed': 0,
            'by_sensor': {},
            'total_cost': 0.0,
            'total_entities': 0,
            'total_statements': 0,
            'errors': []
        }

    async def get_sample_documents(self, conn: asyncpg.Connection) -> List[Dict[str, Any]]:
        """Get sample documents from each sensor type - prioritizing substantive content"""

        # Query to get representative samples with better content
        query = """
        WITH sensor_samples AS (
            -- Website samples (5 docs) - longer content
            (SELECT rid, source_sensor, content, metadata, 'website' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'website-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 800
             ORDER BY LENGTH(content::text) DESC LIMIT 5)

            UNION ALL

            -- Discourse samples (5 docs) - governance & technical posts
            (SELECT rid, source_sensor, content, metadata, 'discourse' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'discourse-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 800
                AND (content::text ILIKE '%governance%'
                     OR content::text ILIKE '%proposal%'
                     OR content::text ILIKE '%technical%')
             ORDER BY LENGTH(content::text) DESC LIMIT 5)

            UNION ALL

            -- GitHub samples (5 docs) - READMEs and docs preferred
            (SELECT rid, source_sensor, content, metadata, 'github' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'github-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 800
                AND (rid ILIKE '%README%' OR rid ILIKE '%CONTRIBUTING%' OR rid ILIKE '%LICENSE%')
             ORDER BY LENGTH(content::text) DESC LIMIT 5)

            UNION ALL

            -- Notion samples (5 docs) - longer content
            (SELECT rid, source_sensor, content, metadata, 'notion' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'notion-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 800
             ORDER BY LENGTH(content::text) DESC LIMIT 5)

            UNION ALL

            -- GitLab samples (3 docs) - longer content
            (SELECT rid, source_sensor, content, metadata, 'gitlab' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'gitlab-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 800
             ORDER BY LENGTH(content::text) DESC LIMIT 3)

            UNION ALL

            -- Podcast samples (3 docs) - longer episodes
            (SELECT rid, source_sensor, content, metadata, 'podcast' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'podcast-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
                AND LENGTH(content::text) > 1000
             ORDER BY LENGTH(content::text) DESC LIMIT 3)

            UNION ALL

            -- GitHub Activity samples (2 docs)
            (SELECT rid, source_sensor, content, metadata, 'github-activity' as sensor_type
             FROM koi_memories
             WHERE source_sensor LIKE 'github-activity-sensor%'
                AND superseded_at IS NULL
                AND is_chunk = false
             ORDER BY created_at DESC LIMIT 2)
        )
        SELECT * FROM sensor_samples;
        """

        rows = await conn.fetch(query)
        documents = []

        for row in rows:
            # Extract text from JSONB content
            content_data = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
            text = content_data.get('text', '')

            metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

            documents.append({
                'rid': row['rid'],
                'source_sensor': row['source_sensor'],
                'sensor_type': row['sensor_type'],
                'text': text,
                'metadata': metadata
            })

        return documents

    async def test_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Test KG extraction on a single document"""

        sensor_type = doc['sensor_type']

        try:
            # Run extraction
            extraction_rid, receipt_id = await self.extractor.extract_and_track(
                memory_rid=doc['rid'],
                content=doc['text'],
                metadata=doc['metadata']
            )

            # Verify extraction in database
            conn = await asyncpg.connect(self.db_url)
            try:
                extraction = await conn.fetchrow("""
                    SELECT * FROM koi_kg_extractions WHERE extraction_rid = $1
                """, extraction_rid)

                if not extraction:
                    raise Exception(f"Extraction not found in database: {extraction_rid}")

                # Verify CAT receipt
                receipt = await conn.fetchrow("""
                    SELECT * FROM koi_transformation_receipts WHERE receipt_id = $1
                """, receipt_id)

                if not receipt:
                    raise Exception(f"CAT receipt not found: {receipt_id}")

                # Parse extraction data
                entities = json.loads(extraction['entities']) if isinstance(extraction['entities'], str) else extraction['entities']
                statements = json.loads(extraction['statements']) if isinstance(extraction['statements'], str) else extraction['statements']

                # Validate RIDs
                rid_valid = validate_kg_rid(extraction_rid, expected_type='kg')

                # Collect metrics
                result = {
                    'success': True,
                    'sensor_type': sensor_type,
                    'rid': doc['rid'],
                    'extraction_rid': extraction_rid,
                    'receipt_id': receipt_id,
                    'entity_count': len(entities),
                    'statement_count': len(statements),
                    'confidence': float(extraction['confidence_score']),
                    'cost_usd': float(extraction['cost_usd']),
                    'rid_valid': rid_valid,
                    'source_url_preserved': doc['metadata'].get('url') is not None,
                    'error': None
                }

                # Update aggregates
                self.results['total_entities'] += len(entities)
                self.results['total_statements'] += len(statements)
                self.results['total_cost'] += float(extraction['cost_usd'])

                return result
            finally:
                await conn.close()

        except Exception as e:
            return {
                'success': False,
                'sensor_type': sensor_type,
                'rid': doc['rid'],
                'error': str(e)
            }

    async def run_validation(self):
        """Run full validation suite"""

        print("=" * 80)
        print("PHASE 2 VALIDATION - Testing KG Extraction on Real Sensor Data")
        print("=" * 80)
        print()

        conn = await asyncpg.connect(self.db_url)
        try:
            # Get sample documents
            print("📥 Fetching sample documents from each sensor type...")
            documents = await self.get_sample_documents(conn)
            print(f"   Found {len(documents)} sample documents")
            print()

            # Group by sensor type
            by_sensor = {}
            for doc in documents:
                sensor_type = doc['sensor_type']
                if sensor_type not in by_sensor:
                    by_sensor[sensor_type] = []
                by_sensor[sensor_type].append(doc)

            print(f"📊 Distribution:")
            for sensor_type, docs in by_sensor.items():
                print(f"   - {sensor_type}: {len(docs)} documents")
            print()

            # Test each document
            print("🔬 Running KG extraction tests...")
            print()

            for sensor_type, docs in by_sensor.items():
                print(f"Testing {sensor_type} sensor ({len(docs)} docs)...")

                sensor_results = []
                for i, doc in enumerate(docs, 1):
                    print(f"  [{i}/{len(docs)}] {doc['rid'][:50]}...", end=" ")

                    result = await self.test_document(doc)
                    sensor_results.append(result)

                    if result['success']:
                        print(f"✅ {result['entity_count']} entities, {result['statement_count']} statements")
                        self.results['successful'] += 1
                    else:
                        print(f"❌ {result['error']}")
                        self.results['failed'] += 1
                        self.results['errors'].append(result)

                    self.results['total_tested'] += 1

                # Store sensor-specific results
                self.results['by_sensor'][sensor_type] = {
                    'tested': len(docs),
                    'successful': sum(1 for r in sensor_results if r['success']),
                    'failed': sum(1 for r in sensor_results if not r['success']),
                    'avg_entities': sum(r.get('entity_count', 0) for r in sensor_results) / len(sensor_results) if sensor_results else 0,
                    'avg_statements': sum(r.get('statement_count', 0) for r in sensor_results) / len(sensor_results) if sensor_results else 0,
                    'avg_confidence': sum(r.get('confidence', 0) for r in sensor_results if r['success']) / sum(1 for r in sensor_results if r['success']) if any(r['success'] for r in sensor_results) else 0,
                    'total_cost': sum(r.get('cost_usd', 0) for r in sensor_results)
                }

                print()
        finally:
            await conn.close()

    def print_summary(self):
        """Print validation summary"""

        print()
        print("=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print()

        print(f"📊 Overall Results:")
        print(f"   Total Tested: {self.results['total_tested']}")
        print(f"   Successful: {self.results['successful']} ({self.results['successful']/self.results['total_tested']*100:.1f}%)")
        print(f"   Failed: {self.results['failed']}")
        print()

        print(f"📈 Extraction Metrics:")
        print(f"   Total Entities: {self.results['total_entities']}")
        print(f"   Total Statements: {self.results['total_statements']}")
        print(f"   Avg Entities/Doc: {self.results['total_entities']/self.results['successful']:.1f}" if self.results['successful'] > 0 else "   Avg Entities/Doc: N/A")
        print(f"   Avg Statements/Doc: {self.results['total_statements']/self.results['successful']:.1f}" if self.results['successful'] > 0 else "   Avg Statements/Doc: N/A")
        print()

        print(f"💰 Cost Analysis:")
        print(f"   Total Cost: ${self.results['total_cost']:.4f}")
        print(f"   Avg Cost/Doc: ${self.results['total_cost']/self.results['total_tested']:.6f}" if self.results['total_tested'] > 0 else "   Avg Cost/Doc: N/A")
        print()

        print(f"🔬 Results by Sensor Type:")
        for sensor_type, metrics in self.results['by_sensor'].items():
            print(f"   {sensor_type}:")
            print(f"      Tested: {metrics['tested']}, Success: {metrics['successful']}, Failed: {metrics['failed']}")
            print(f"      Avg Entities: {metrics['avg_entities']:.1f}, Avg Statements: {metrics['avg_statements']:.1f}")
            print(f"      Avg Confidence: {metrics['avg_confidence']:.3f}")
            print(f"      Total Cost: ${metrics['total_cost']:.4f}")
        print()

        if self.results['errors']:
            print(f"❌ Errors ({len(self.results['errors'])}):")
            for error in self.results['errors']:
                print(f"   - {error['sensor_type']}: {error['error']}")
            print()

        print("✅ Validation complete!")
        print()

    async def save_results(self, output_file: str = "phase2_validation_results.json"):
        """Save results to JSON file"""

        output_path = Path(__file__).parent / output_file

        # Add timestamp
        self.results['timestamp'] = datetime.now().isoformat()

        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"📄 Results saved to: {output_path}")


async def main():
    """Main validation runner"""

    # Get database URL from environment
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    # Create validator
    validator = Phase2Validator(db_url)

    # Run validation
    await validator.run_validation()

    # Print summary
    validator.print_summary()

    # Save results
    await validator.save_results()


if __name__ == "__main__":
    asyncio.run(main())
