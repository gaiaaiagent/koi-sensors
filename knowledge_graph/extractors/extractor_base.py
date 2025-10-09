"""
KOI Knowledge Graph - Base Extractor Class
Foundation for all KG extraction passes with CAT integration

All extractors inherit from this base class to ensure:
- Consistent database storage in koi_kg_extractions table
- CAT receipt generation for provenance tracking
- RID generation following KOI protocol standards
- Proper error handling and logging
"""

import asyncpg
import hashlib
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from loguru import logger

from knowledge_graph.kg_rid_generator import generate_kg_extraction_rid


class KGExtractorBase(ABC):
    """
    Base class for all Knowledge Graph extractors

    Provides:
    - Database connection management
    - CAT receipt creation for provenance
    - RID generation for extraction results
    - Deduplication logic
    - Storage in koi_kg_extractions table

    Subclasses must implement:
    - extract(content: str) -> Dict: The actual extraction logic
    """

    def __init__(
        self,
        db_url: str,
        ontology_version: str = "op-v1.1",
        extractor_version: str = "1.0.0"
    ):
        """
        Initialize base extractor

        Args:
            db_url: PostgreSQL connection URL (e.g., postgresql://user:pass@host:port/db)
            ontology_version: Version of the ontology being used (default: "op-v1.1")
            extractor_version: Version of this extractor (default: "1.0.0")
        """
        self.db_url = db_url
        self.ontology_version = ontology_version
        self.extractor_version = extractor_version
        self.pass_type = "base"  # Override in subclass (e.g., "passA", "passB")

    async def extract_and_track(
        self,
        memory_rid: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> Tuple[str, str]:
        """
        Main orchestration method: Extract KG + Store + Create CAT receipt

        This method:
        1. Extracts source_url from metadata
        2. Calls self.extract() (implemented by subclass)
        3. Generates extraction_rid using kg_rid_generator
        4. Stores extraction result in koi_kg_extractions table
        5. Creates CAT receipt via create_extraction_receipt()
        6. Returns (extraction_rid, receipt_id)

        Args:
            memory_rid: RID of the parent memory/document (e.g., "orn:web.page:domain/abc123")
            content: The text content to extract from
            metadata: Metadata dict containing source_url and other info

        Returns:
            Tuple[str, str]: (extraction_rid, receipt_id)

        Raises:
            ValueError: If source_url missing from metadata
            Exception: Database or extraction errors
        """
        # Extract source_url from metadata
        source_url = metadata.get('source_url')
        if not source_url:
            raise ValueError("source_url is required in metadata")

        logger.info(f"Starting {self.pass_type} extraction for {memory_rid}")

        # Call subclass extraction logic
        extraction_result = await self.extract(content)

        # Generate extraction RID
        extraction_rid = generate_kg_extraction_rid(memory_rid, self.pass_type, self.ontology_version)

        # Store extraction and create receipt
        conn = await asyncpg.connect(self.db_url)
        try:
            # Store extraction in koi_kg_extractions table
            await conn.execute("""
                INSERT INTO koi_kg_extractions (
                    memory_rid, extraction_rid, extraction_type,
                    entities, statements, relations,
                    confidence_score, ontology_version, extractor_version,
                    tokens_consumed, cost_usd, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (extraction_rid) DO UPDATE SET
                    entities = $4, statements = $5, updated_at = $12
            """,
                memory_rid,
                extraction_rid,
                self.pass_type,
                json.dumps(extraction_result.get('entities', [])),
                json.dumps(extraction_result.get('statements', [])),
                json.dumps(extraction_result.get('relations', [])),
                extraction_result.get('confidence_avg', 0.0),
                self.ontology_version,
                self.extractor_version,
                extraction_result.get('tokens_consumed', 0),
                extraction_result.get('cost_usd', 0.0),
                datetime.now(timezone.utc)
            )

            logger.info(f"✓ Stored extraction {extraction_rid[:60]}...")

            # Create CAT receipt for provenance tracking
            receipt_id = await self.create_extraction_receipt(
                conn, memory_rid, extraction_rid, extraction_result, source_url
            )

            logger.info(f"✓ Completed {self.pass_type} extraction: {extraction_rid[:60]}... (receipt: {receipt_id[:8]}...)")
            return extraction_rid, receipt_id
        finally:
            await conn.close()

    async def create_extraction_receipt(
        self,
        conn: asyncpg.Connection,
        input_rid: str,
        output_rid: str,
        result: Dict[str, Any],
        source_url: str
    ) -> str:
        """
        Create CAT receipt for extraction - integrates with existing CAT system

        This follows the same pattern as koi-processor's create_cat_receipt:
        - Checks for existing receipt (deduplication)
        - Generates receipt_id using SHA256 hash
        - Inserts into koi_transformation_receipts table

        Args:
            conn: Active database connection
            input_rid: The memory/document RID being processed
            output_rid: The extraction RID produced
            result: The extraction result dict
            source_url: Source URL from metadata

        Returns:
            str: The receipt_id (SHA256 hash)
        """
        # Check for existing receipt (deduplication)
        existing = await conn.fetchrow("""
            SELECT receipt_id FROM koi_transformation_receipts
            WHERE input_rid = $1 AND output_rid = $2 AND transformation_type = $3
        """, input_rid, output_rid, f'kg_extraction_{self.pass_type}')

        if existing:
            logger.info(f"✓ DUPLICATE RECEIPT: kg_extraction_{self.pass_type} {input_rid} → {output_rid} - SKIPPING")
            return existing['receipt_id']

        # Generate receipt ID using SHA256 (same pattern as create_cat_receipt)
        timestamp = datetime.now(timezone.utc).isoformat()
        content = f"kg_extraction_{self.pass_type}:{input_rid}:{output_rid}:{timestamp}"
        receipt_id = hashlib.sha256(content.encode()).hexdigest()

        # Prepare metadata
        metadata = {
            'source_url': source_url,
            'entities_extracted': len(result.get('entities', [])),
            'statements_extracted': len(result.get('statements', [])),
            'relations_extracted': len(result.get('relations', [])),
            'confidence_avg': result.get('confidence_avg', 0.0),
            'tokens_consumed': result.get('tokens_consumed', 0),
            'cost_usd': result.get('cost_usd', 0.0),
            'timestamp': timestamp
        }

        # Insert receipt into koi_transformation_receipts
        await conn.execute("""
            INSERT INTO koi_transformation_receipts (
                receipt_id, transformation_type, input_rid, output_rid,
                processor_name, processor_version,
                entities_extracted, metadata, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (receipt_id) DO NOTHING
        """,
            receipt_id,
            f'kg_extraction_{self.pass_type}',
            input_rid,
            output_rid,
            f'kg-extractor-{self.pass_type}',
            self.extractor_version,
            len(result.get('entities', [])),
            json.dumps(metadata),
            datetime.now(timezone.utc)
        )

        logger.info(f"✓ NEW RECEIPT: kg_extraction_{self.pass_type} {input_rid[:50]} → {output_rid[:50]} (ID: {receipt_id[:8]}...)")
        return receipt_id

    @abstractmethod
    async def extract(self, content: str) -> Dict[str, Any]:
        """
        Perform knowledge graph extraction (implemented by subclass)

        This method contains the actual extraction logic (e.g., GPT-4 calls, parsing).
        Must be implemented by all subclasses.

        Args:
            content: The text content to extract knowledge from

        Returns:
            Dict containing:
                - entities: List[Dict] - Extracted entities with RIDs
                - statements: List[Dict] - Extracted statements with RIDs
                - relations: List[Dict] - Extracted relations (optional)
                - confidence_avg: float - Average confidence score
                - tokens_consumed: int - Token usage
                - cost_usd: float - API cost in USD

        Example:
            {
                "entities": [
                    {"rid": "orn:...:entity:person:jane-doe", "name": "Jane Doe", ...},
                    ...
                ],
                "statements": [
                    {"rid": "orn:...:statement:claim:001", "subject": ..., ...},
                    ...
                ],
                "relations": [...],
                "confidence_avg": 0.85,
                "tokens_consumed": 1500,
                "cost_usd": 0.03
            }
        """
        raise NotImplementedError("Subclasses must implement extract() method")
