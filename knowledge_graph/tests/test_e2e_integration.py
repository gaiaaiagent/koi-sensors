"""
End-to-End Integration Test

Tests the complete KG extraction pipeline from memory creation to database storage.
Validates event bridge integration, CAT receipts, and provenance chains.
"""

import asyncio
import asyncpg
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add koi-sensors to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from knowledge_graph.extractors.pass_a_extractor import PassAExtractor
from knowledge_graph.kg_rid_generator import (
    validate_kg_rid,
    parse_kg_rid,
    generate_kg_extraction_rid
)


class E2EIntegrationTester:
    """End-to-end integration tester for KG extraction pipeline"""

    def __init__(self, db_url: str):
        self.db_url = db_url

    async def test_full_pipeline(self):
        """Test the complete pipeline from memory to extraction"""

        print("=" * 80)
        print("END-TO-END INTEGRATION TEST")
        print("=" * 80)
        print()

        # Test 1: Direct extraction (simulating event bridge trigger)
        print("🧪 TEST 1: Direct Extraction Pipeline")
        print("-" * 80)
        await self._test_direct_extraction()
        print()

        # Test 2: Provenance chain validation
        print("🧪 TEST 2: Provenance Chain Validation")
        print("-" * 80)
        await self._test_provenance_chain()
        print()

        # Test 3: RID validation
        print("🧪 TEST 3: RID Format Validation")
        print("-" * 80)
        await self._test_rid_validation()
        print()

        # Test 4: CAT receipt validation
        print("🧪 TEST 4: CAT Receipt Validation")
        print("-" * 80)
        await self._test_cat_receipts()
        print()

        # Test 5: Deduplication
        print("🧪 TEST 5: Deduplication Test")
        print("-" * 80)
        await self._test_deduplication()
        print()

        print("=" * 80)
        print("✅ END-TO-END INTEGRATION TEST COMPLETE")
        print("=" * 80)

    async def _test_direct_extraction(self):
        """Test direct extraction via PassAExtractor"""

        # Get a sample memory from database
        async with asyncpg.connect(self.db_url) as conn:
            memory = await conn.fetchrow("""
                SELECT rid, content, metadata, source_sensor
                FROM koi_memories
                WHERE superseded_at IS NULL
                    AND is_chunk = false
                    AND LENGTH(content::text) > 500
                ORDER BY created_at DESC
                LIMIT 1
            """)

            if not memory:
                print("   ❌ No test memory found in database")
                return

            print(f"   📄 Test Memory: {memory['rid']}")
            print(f"   📡 Source Sensor: {memory['source_sensor']}")

            # Extract content
            content_data = json.loads(memory['content']) if isinstance(memory['content'], str) else memory['content']
            text = content_data.get('text', '')
            metadata = json.loads(memory['metadata']) if isinstance(memory['metadata'], str) else memory['metadata']

            print(f"   📝 Content Length: {len(text)} chars")

            # Run extraction
            extractor = PassAExtractor(db_url=self.db_url)

            try:
                extraction_rid, receipt_id = await extractor.extract_and_track(
                    memory_rid=memory['rid'],
                    content=text,
                    metadata=metadata
                )

                print(f"   ✅ Extraction Complete")
                print(f"      Extraction RID: {extraction_rid}")
                print(f"      Receipt ID: {receipt_id[:16]}...")

                # Verify in database
                extraction = await conn.fetchrow("""
                    SELECT * FROM koi_kg_extractions WHERE extraction_rid = $1
                """, extraction_rid)

                if extraction:
                    entities = json.loads(extraction['entities']) if isinstance(extraction['entities'], str) else extraction['entities']
                    statements = json.loads(extraction['statements']) if isinstance(extraction['statements'], str) else extraction['statements']

                    print(f"      Entities Extracted: {len(entities)}")
                    print(f"      Statements Extracted: {len(statements)}")
                    print(f"      Confidence: {extraction['confidence_score']:.3f}")
                    print(f"      Cost: ${extraction['cost_usd']:.6f}")
                else:
                    print(f"   ❌ Extraction not found in database!")

            except Exception as e:
                print(f"   ❌ Extraction failed: {e}")

    async def _test_provenance_chain(self):
        """Validate complete provenance chain"""

        async with asyncpg.connect(self.db_url) as conn:
            # Get a random extraction
            extraction = await conn.fetchrow("""
                SELECT e.*, m.source_sensor, m.metadata
                FROM koi_kg_extractions e
                JOIN koi_memories m ON e.memory_rid = m.rid
                LIMIT 1
            """)

            if not extraction:
                print("   ⚠️  No extractions found to validate")
                return

            print(f"   🔍 Checking extraction: {extraction['extraction_rid']}")

            # Check 1: Source URL preserved
            metadata = json.loads(extraction['metadata']) if isinstance(extraction['metadata'], str) else extraction['metadata']
            source_url = metadata.get('url')

            if source_url:
                print(f"   ✅ Source URL preserved: {source_url}")
            else:
                print(f"   ❌ Source URL missing!")

            # Check 2: Memory RID linkage
            memory = await conn.fetchrow("""
                SELECT rid FROM koi_memories WHERE rid = $1
            """, extraction['memory_rid'])

            if memory:
                print(f"   ✅ Memory RID linkage valid: {extraction['memory_rid']}")
            else:
                print(f"   ❌ Memory RID not found!")

            # Check 3: CAT receipt exists
            receipt = await conn.fetchrow("""
                SELECT receipt_id, transformation_type
                FROM koi_transformation_receipts
                WHERE output_rid = $1
            """, extraction['extraction_rid'])

            if receipt:
                print(f"   ✅ CAT receipt exists: {receipt['receipt_id'][:16]}...")
                print(f"      Transformation type: {receipt['transformation_type']}")
            else:
                print(f"   ❌ CAT receipt missing!")

            # Check 4: Complete provenance chain
            provenance_chain = await conn.fetch("""
                WITH RECURSIVE chain AS (
                    -- Start with the extraction
                    SELECT
                        receipt_id,
                        transformation_type,
                        input_rid,
                        output_rid,
                        1 as level
                    FROM koi_transformation_receipts
                    WHERE output_rid = $1

                    UNION

                    -- Follow the chain backwards
                    SELECT
                        t.receipt_id,
                        t.transformation_type,
                        t.input_rid,
                        t.output_rid,
                        c.level + 1
                    FROM koi_transformation_receipts t
                    JOIN chain c ON t.output_rid = c.input_rid
                    WHERE c.level < 10  -- Prevent infinite loops
                )
                SELECT * FROM chain ORDER BY level;
            """, extraction['extraction_rid'])

            if provenance_chain:
                print(f"   ✅ Provenance chain depth: {len(provenance_chain)}")
                for i, step in enumerate(provenance_chain):
                    print(f"      Level {step['level']}: {step['transformation_type']}")
            else:
                print(f"   ⚠️  Provenance chain has only 1 level (extraction itself)")

    async def _test_rid_validation(self):
        """Validate RID formats"""

        async with asyncpg.connect(self.db_url) as conn:
            # Get all extractions
            extractions = await conn.fetch("""
                SELECT extraction_rid, memory_rid
                FROM koi_kg_extractions
                LIMIT 10
            """)

            if not extractions:
                print("   ⚠️  No extractions to validate")
                return

            print(f"   🔍 Validating {len(extractions)} extraction RIDs...")

            all_valid = True
            for extraction in extractions:
                extraction_rid = extraction['extraction_rid']
                memory_rid = extraction['memory_rid']

                # Validate extraction RID format
                try:
                    is_valid = validate_kg_rid(extraction_rid, expected_type='kg')

                    if is_valid:
                        parsed = parse_kg_rid(extraction_rid)
                        print(f"   ✅ {extraction_rid[:50]}...")
                        print(f"      Parent: {parsed['parent_rid'][:50]}...")
                        print(f"      Type: {parsed['kg_type']}, Pass: {parsed['pass_type']}, Version: {parsed['version']}")
                    else:
                        print(f"   ❌ Invalid RID format: {extraction_rid}")
                        all_valid = False

                except Exception as e:
                    print(f"   ❌ RID validation error: {e}")
                    all_valid = False

            if all_valid:
                print(f"   ✅ All RIDs valid!")
            else:
                print(f"   ❌ Some RIDs invalid!")

    async def _test_cat_receipts(self):
        """Validate CAT receipt creation and deduplication"""

        async with asyncpg.connect(self.db_url) as conn:
            # Check all extractions have CAT receipts
            query = """
            SELECT
                COUNT(*) as total_extractions,
                COUNT(DISTINCT r.receipt_id) as receipts_found
            FROM koi_kg_extractions e
            LEFT JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid
            """

            result = await conn.fetchrow(query)

            total = result['total_extractions']
            found = result['receipts_found']

            print(f"   📊 Total Extractions: {total}")
            print(f"   📊 CAT Receipts Found: {found}")

            if total == found:
                print(f"   ✅ All extractions have CAT receipts (100% coverage)")
            else:
                missing = total - found
                print(f"   ❌ Missing {missing} CAT receipts ({missing/total*100:.1f}%)")

            # Check receipt metadata
            sample_receipt = await conn.fetchrow("""
                SELECT *
                FROM koi_transformation_receipts
                WHERE transformation_type LIKE 'kg_extraction_%'
                LIMIT 1
            """)

            if sample_receipt:
                print(f"   📄 Sample Receipt:")
                print(f"      Transformation: {sample_receipt['transformation_type']}")
                print(f"      Processor: {sample_receipt['processor_name']}")

                metadata = json.loads(sample_receipt['metadata']) if isinstance(sample_receipt['metadata'], str) else sample_receipt['metadata']
                print(f"      Metadata keys: {list(metadata.keys())}")

                required_keys = ['source_url', 'entities_extracted', 'statements_extracted', 'tokens_consumed', 'cost_usd']
                missing_keys = [key for key in required_keys if key not in metadata]

                if not missing_keys:
                    print(f"   ✅ All required metadata present")
                else:
                    print(f"   ❌ Missing metadata: {missing_keys}")

    async def _test_deduplication(self):
        """Test deduplication logic"""

        # Get a sample memory
        async with asyncpg.connect(self.db_url) as conn:
            memory = await conn.fetchrow("""
                SELECT rid, content, metadata
                FROM koi_memories
                WHERE superseded_at IS NULL
                    AND is_chunk = false
                    AND LENGTH(content::text) > 300
                ORDER BY created_at DESC
                LIMIT 1
            """)

            if not memory:
                print("   ⚠️  No test memory available")
                return

            # Extract content
            content_data = json.loads(memory['content']) if isinstance(memory['content'], str) else memory['content']
            text = content_data.get('text', '')
            metadata = json.loads(memory['metadata']) if isinstance(memory['metadata'], str) else memory['metadata']

            print(f"   🔄 Testing deduplication with: {memory['rid'][:50]}...")

            extractor = PassAExtractor(db_url=self.db_url)

            # First extraction
            try:
                extraction_rid_1, receipt_id_1 = await extractor.extract_and_track(
                    memory_rid=memory['rid'],
                    content=text,
                    metadata=metadata
                )

                print(f"   ✅ First extraction: {extraction_rid_1[:50]}...")
                print(f"      Receipt ID: {receipt_id_1[:16]}...")

                # Second extraction (should be deduplicated)
                extraction_rid_2, receipt_id_2 = await extractor.extract_and_track(
                    memory_rid=memory['rid'],
                    content=text,
                    metadata=metadata
                )

                print(f"   ✅ Second extraction: {extraction_rid_2[:50]}...")
                print(f"      Receipt ID: {receipt_id_2[:16]}...")

                # Check if RIDs are the same (deduplication working)
                if extraction_rid_1 == extraction_rid_2:
                    print(f"   ✅ Extraction RIDs match (deduplication working)")
                else:
                    print(f"   ⚠️  Extraction RIDs differ (expected for different content)")

                if receipt_id_1 == receipt_id_2:
                    print(f"   ✅ Receipt IDs match (deduplication working)")
                else:
                    print(f"   ⚠️  Receipt IDs differ")

                # Check database counts
                extraction_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM koi_kg_extractions WHERE memory_rid = $1
                """, memory['rid'])

                receipt_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM koi_transformation_receipts
                    WHERE input_rid = $1 AND transformation_type LIKE 'kg_extraction_%'
                """, memory['rid'])

                print(f"   📊 DB Records:")
                print(f"      Extractions: {extraction_count}")
                print(f"      Receipts: {receipt_count}")

                if extraction_count == 1 and receipt_count == 1:
                    print(f"   ✅ Deduplication working correctly (1 record each)")
                else:
                    print(f"   ⚠️  Expected 1 extraction and 1 receipt, found {extraction_count} and {receipt_count}")

            except Exception as e:
                print(f"   ❌ Deduplication test failed: {e}")


async def main():
    """Main test runner"""

    # Get database URL
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    # Create tester
    tester = E2EIntegrationTester(db_url)

    # Run tests
    await tester.test_full_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
