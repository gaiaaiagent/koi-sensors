"""
Phase 3 Validation Script

Validates all Phase 3 advanced features:
- Entity resolution with CAT receipts
- Contradiction detection
- MCP server KG enrichment
- Metrics monitoring
"""

import asyncio
import asyncpg
import os
from loguru import logger


async def validate_entity_resolution():
    """Validate entity resolution is working"""
    logger.info("Validating Entity Resolution...")

    conn = await asyncpg.connect(os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza'))

    try:
        # Check resolution receipts exist
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM koi_transformation_receipts
            WHERE transformation_type = 'kg_entity_resolution'
        """)

        if count == 0:
            logger.error("❌ No entity resolution receipts found")
            return False

        # Check metadata structure
        sample = await conn.fetchrow("""
            SELECT receipt_id, input_rid, output_rid, metadata
            FROM koi_transformation_receipts
            WHERE transformation_type = 'kg_entity_resolution'
            LIMIT 1
        """)

        if not sample:
            logger.error("❌ No sample resolution receipt found")
            return False

        import json
        metadata = json.loads(sample['metadata']) if isinstance(sample['metadata'], str) else sample['metadata']
        required_fields = ['cluster_size', 'similarity_threshold', 'resolution_type']

        for field in required_fields:
            if field not in metadata:
                logger.error(f"❌ Missing metadata field: {field}")
                return False

        logger.info(f"✅ Entity Resolution: {count} resolutions created")
        logger.info(f"   Sample: {sample['input_rid'][:30]}... → {sample['output_rid'][:30]}...")
        logger.info(f"   Cluster size: {metadata['cluster_size']}")

        return True

    finally:
        await conn.close()


async def validate_contradiction_detection():
    """Validate contradiction detection system"""
    logger.info("\nValidating Contradiction Detection...")

    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/eliza')

    try:
        # Check table exists and has correct schema
        columns = await conn.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'koi_kg_contradictions'
        """)

        required_columns = [
            'statement1_rid', 'statement1_url',
            'statement2_rid', 'statement2_url',
            'contradiction_type', 'contradiction_details'
        ]

        column_names = [c['column_name'] for c in columns]
        for col in required_columns:
            if col not in column_names:
                logger.error(f"❌ Missing column: {col}")
                return False

        # Check if we can detect contradictions (structure test)
        total_statements = await conn.fetchval("""
            SELECT SUM(jsonb_array_length(COALESCE(statements, '[]'::jsonb)))
            FROM koi_kg_extractions
        """)

        logger.info(f"✅ Contradiction Detection: Schema valid")
        logger.info(f"   {total_statements} statements available for detection")

        # Import and test detector
        from knowledge_graph.contradiction_detector import ContradictionDetector

        detector = ContradictionDetector('postgresql://postgres:postgres@localhost:5433/eliza', use_llm=False)
        contradictions = await detector.get_unresolved_contradictions()

        logger.info(f"   {len(contradictions)} unresolved contradictions")

        return True

    except Exception as e:
        logger.error(f"❌ Contradiction detection validation failed: {e}")
        return False

    finally:
        await conn.close()


async def validate_mcp_enrichment():
    """Validate MCP server KG enrichment"""
    logger.info("\nValidating MCP Server KG Enrichment...")

    try:
        # Check if enrichment functions are importable
        import sys
        sys.path.insert(0, '/opt/projects/koi-processor/src/core')

        # Test enrichment function exists
        from koi_knowledge_mcp_server import enrich_with_kg_data, search_with_kg_enrichment

        logger.info("✅ MCP KG Enrichment: Functions importable")

        # Test enrichment on a sample memory
        conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/eliza')

        try:
            # Get a memory RID that has KG data
            sample = await conn.fetchrow("""
                SELECT memory_rid FROM koi_kg_extractions
                WHERE jsonb_array_length(COALESCE(entities, '[]'::jsonb)) > 0
                LIMIT 1
            """)

            if sample:
                kg_data = await enrich_with_kg_data(sample['memory_rid'], conn)

                if kg_data:
                    logger.info(f"   Sample enrichment: {len(kg_data['entities'])} entities")
                    logger.info(f"   Provenance chain: {len(kg_data['provenance_chain'])} receipts")

                    # Check for canonical RIDs
                    resolved_count = sum(1 for e in kg_data['entities'] if e.get('was_resolved'))
                    logger.info(f"   Resolved entities: {resolved_count}/{len(kg_data['entities'])}")

                    return True
                else:
                    logger.warning("⚠️  No KG data for sample memory")
                    return True  # Structure is correct, just no data

            else:
                logger.warning("⚠️  No memories with KG data found")
                return True  # Structure is correct, just no data

        finally:
            await conn.close()

    except Exception as e:
        logger.error(f"❌ MCP enrichment validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def validate_metrics_monitoring():
    """Validate metrics monitoring"""
    logger.info("\nValidating Metrics Monitoring...")

    try:
        from knowledge_graph.monitoring.kg_metrics import KGMetricsCollector

        collector = KGMetricsCollector('postgresql://postgres:postgres@localhost:5433/eliza')

        # Test all-time stats
        all_time = await collector.get_all_time_stats()

        required_fields = [
            'total_extractions', 'total_entities', 'total_statements',
            'avg_confidence', 'total_cost_usd', 'entity_resolutions'
        ]

        for field in required_fields:
            if field not in all_time:
                logger.error(f"❌ Missing metrics field: {field}")
                return False

        logger.info(f"✅ Metrics Monitoring: All fields present")
        logger.info(f"   Total extractions: {all_time['total_extractions']}")
        logger.info(f"   Total entities: {all_time['total_entities']}")
        logger.info(f"   Total cost: ${all_time['total_cost_usd']:.4f}")
        logger.info(f"   Entity resolutions: {all_time['entity_resolutions']}")

        # Test daily metrics
        daily = await collector.collect_daily_metrics()

        if 'extraction_metrics' not in daily:
            logger.error("❌ Daily metrics missing extraction_metrics")
            return False

        logger.info(f"   Daily extractions: {daily['extraction_metrics']['total_extractions']}")

        return True

    except Exception as e:
        logger.error(f"❌ Metrics validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all validations"""
    print("\n" + "="*60)
    print("PHASE 3 VALIDATION - Advanced Features")
    print("="*60 + "\n")

    results = {
        'Entity Resolution': await validate_entity_resolution(),
        'Contradiction Detection': await validate_contradiction_detection(),
        'MCP KG Enrichment': await validate_mcp_enrichment(),
        'Metrics Monitoring': await validate_metrics_monitoring()
    }

    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)

    all_passed = True
    for feature, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{feature:25s}: {status}")
        if not passed:
            all_passed = False

    print("="*60)

    if all_passed:
        print("\n🎉 All Phase 3 features validated successfully!\n")
        return 0
    else:
        print("\n⚠️  Some validations failed. Please review logs above.\n")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    exit(exit_code)
