-- Provenance Chain Validation Queries
-- Run these queries to validate complete provenance tracking for KG extractions

-- ============================================================================
-- 1. CHECK SOURCE URL COVERAGE (Should be 100%)
-- ============================================================================

SELECT
    'Source URL Coverage' as check_name,
    COUNT(*) as total_extractions,
    COUNT(CASE WHEN m.metadata->>'url' IS NOT NULL THEN 1 END) as with_source_url,
    ROUND(100.0 * COUNT(CASE WHEN m.metadata->>'url' IS NOT NULL THEN 1 END) / COUNT(*), 2) as coverage_percent
FROM koi_kg_extractions e
JOIN koi_memories m ON e.memory_rid = m.rid;

-- ============================================================================
-- 2. CHECK CAT RECEIPT COVERAGE (Should be 100%)
-- ============================================================================

SELECT
    'CAT Receipt Coverage' as check_name,
    COUNT(DISTINCT e.extraction_rid) as total_extractions,
    COUNT(DISTINCT r.receipt_id) as with_receipts,
    ROUND(100.0 * COUNT(DISTINCT r.receipt_id) / COUNT(DISTINCT e.extraction_rid), 2) as coverage_percent
FROM koi_kg_extractions e
LEFT JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid;

-- ============================================================================
-- 3. CHECK RID CHAIN VALIDITY
-- ============================================================================

-- Verify all extraction RIDs follow the pattern: {memory_rid}:kg:{pass_type}:v{version}
SELECT
    'RID Chain Validity' as check_name,
    COUNT(*) as total_extractions,
    COUNT(CASE
        WHEN extraction_rid LIKE memory_rid || ':kg:%:v%' THEN 1
    END) as valid_rid_chains,
    ROUND(100.0 * COUNT(CASE
        WHEN extraction_rid LIKE memory_rid || ':kg:%:v%' THEN 1
    END) / COUNT(*), 2) as validity_percent
FROM koi_kg_extractions;

-- ============================================================================
-- 4. FIND ORPHANED EXTRACTIONS (Should be 0)
-- ============================================================================

SELECT
    'Orphaned Extractions' as check_name,
    COUNT(*) as orphaned_count
FROM koi_kg_extractions e
WHERE NOT EXISTS (
    SELECT 1 FROM koi_memories m
    WHERE m.rid = e.memory_rid
);

-- ============================================================================
-- 5. FIND EXTRACTIONS WITHOUT CAT RECEIPTS (Should be 0)
-- ============================================================================

SELECT
    'Extractions Without Receipts' as check_name,
    COUNT(*) as missing_receipts,
    ARRAY_AGG(e.extraction_rid) as extraction_rids
FROM koi_kg_extractions e
WHERE NOT EXISTS (
    SELECT 1 FROM koi_transformation_receipts r
    WHERE r.output_rid = e.extraction_rid
);

-- ============================================================================
-- 6. COMPLETE PROVENANCE CHAIN FOR SAMPLE EXTRACTION
-- ============================================================================

-- Shows the full provenance chain for a random extraction
WITH RECURSIVE provenance_chain AS (
    -- Start with a sample extraction
    SELECT
        e.extraction_rid,
        e.memory_rid,
        r.receipt_id,
        r.transformation_type,
        r.input_rid,
        r.output_rid,
        r.created_at,
        1 as chain_level,
        ARRAY[r.transformation_type] as chain_path
    FROM koi_kg_extractions e
    JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid
    LIMIT 1

    UNION

    -- Follow the chain backwards
    SELECT
        pc.extraction_rid,
        pc.memory_rid,
        r.receipt_id,
        r.transformation_type,
        r.input_rid,
        r.output_rid,
        r.created_at,
        pc.chain_level + 1,
        pc.chain_path || r.transformation_type
    FROM provenance_chain pc
    JOIN koi_transformation_receipts r ON pc.input_rid = r.output_rid
    WHERE pc.chain_level < 10  -- Prevent infinite loops
)
SELECT
    'Sample Provenance Chain' as check_name,
    extraction_rid,
    memory_rid,
    chain_level,
    transformation_type,
    input_rid,
    output_rid,
    created_at,
    chain_path
FROM provenance_chain
ORDER BY chain_level;

-- ============================================================================
-- 7. EXTRACTION METRICS BY SENSOR TYPE
-- ============================================================================

SELECT
    'Metrics by Sensor' as report_name,
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
    SUM(e.tokens_consumed) as total_tokens,
    SUM(e.cost_usd) as total_cost_usd,
    AVG(e.cost_usd) as avg_cost_per_doc,
    COUNT(CASE WHEN r.receipt_id IS NOT NULL THEN 1 END) as with_receipts,
    ROUND(100.0 * COUNT(CASE WHEN r.receipt_id IS NOT NULL THEN 1 END) / COUNT(*), 2) as receipt_coverage_pct
FROM koi_kg_extractions e
JOIN koi_memories m ON e.memory_rid = m.rid
LEFT JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid
GROUP BY sensor_type
ORDER BY extraction_count DESC;

-- ============================================================================
-- 8. ENTITY AND STATEMENT COUNTS BY SOURCE
-- ============================================================================

SELECT
    'Entity/Statement Counts' as report_name,
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
    COUNT(*) as documents,
    SUM(JSONB_ARRAY_LENGTH(e.entities)) as total_entities,
    SUM(JSONB_ARRAY_LENGTH(e.statements)) as total_statements,
    ROUND(AVG(JSONB_ARRAY_LENGTH(e.entities)), 1) as avg_entities_per_doc,
    ROUND(AVG(JSONB_ARRAY_LENGTH(e.statements)), 1) as avg_statements_per_doc
FROM koi_kg_extractions e
JOIN koi_memories m ON e.memory_rid = m.rid
GROUP BY sensor_type
ORDER BY total_entities DESC;

-- ============================================================================
-- 9. FIND BROKEN REFERENCES (Should be empty)
-- ============================================================================

-- Extractions pointing to non-existent memories
SELECT
    'Broken Memory References' as issue_type,
    e.extraction_rid,
    e.memory_rid as broken_memory_rid
FROM koi_kg_extractions e
WHERE NOT EXISTS (
    SELECT 1 FROM koi_memories m WHERE m.rid = e.memory_rid
);

-- Receipts pointing to non-existent extractions
SELECT
    'Broken Extraction References' as issue_type,
    r.receipt_id,
    r.output_rid as broken_extraction_rid
FROM koi_transformation_receipts r
WHERE r.transformation_type LIKE 'kg_extraction_%'
  AND NOT EXISTS (
    SELECT 1 FROM koi_kg_extractions e WHERE e.extraction_rid = r.output_rid
);

-- ============================================================================
-- 10. SUMMARY VALIDATION REPORT
-- ============================================================================

SELECT
    '=== PROVENANCE VALIDATION SUMMARY ===' as summary;

-- Total extractions
SELECT
    'Total Extractions' as metric,
    COUNT(*) as value
FROM koi_kg_extractions;

-- Source URL coverage
SELECT
    'Source URL Coverage' as metric,
    CONCAT(
        ROUND(100.0 * COUNT(CASE WHEN m.metadata->>'url' IS NOT NULL THEN 1 END) / COUNT(*), 2),
        '%'
    ) as value
FROM koi_kg_extractions e
JOIN koi_memories m ON e.memory_rid = m.rid;

-- CAT receipt coverage
SELECT
    'CAT Receipt Coverage' as metric,
    CONCAT(
        ROUND(100.0 * COUNT(DISTINCT r.receipt_id) / COUNT(DISTINCT e.extraction_rid), 2),
        '%'
    ) as value
FROM koi_kg_extractions e
LEFT JOIN koi_transformation_receipts r ON e.extraction_rid = r.output_rid;

-- RID validity
SELECT
    'Valid RID Chains' as metric,
    CONCAT(
        ROUND(100.0 * COUNT(CASE
            WHEN extraction_rid LIKE memory_rid || ':kg:%:v%' THEN 1
        END) / COUNT(*), 2),
        '%'
    ) as value
FROM koi_kg_extractions;

-- Orphaned records
SELECT
    'Orphaned Records' as metric,
    COUNT(*) as value
FROM koi_kg_extractions e
WHERE NOT EXISTS (
    SELECT 1 FROM koi_memories m WHERE m.rid = e.memory_rid
);

-- Total entities extracted
SELECT
    'Total Entities Extracted' as metric,
    SUM(JSONB_ARRAY_LENGTH(entities)) as value
FROM koi_kg_extractions;

-- Total statements extracted
SELECT
    'Total Statements Extracted' as metric,
    SUM(JSONB_ARRAY_LENGTH(statements)) as value
FROM koi_kg_extractions;

-- Average confidence
SELECT
    'Average Confidence Score' as metric,
    ROUND(AVG(confidence_score), 3) as value
FROM koi_kg_extractions;

-- Total cost
SELECT
    'Total Cost (USD)' as metric,
    CONCAT('$', ROUND(SUM(cost_usd)::numeric, 4)) as value
FROM koi_kg_extractions;
