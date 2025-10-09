"""
Bulk KG Extraction Script
Processes existing memories in batches, excluding GitHub/GitLab repos
"""

import asyncio
import asyncpg
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from loguru import logger

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from knowledge_graph.extractors.unified_extractor import UnifiedExtractor


class BulkExtractor:
    """Bulk extraction with progress tracking and resume capability"""

    def __init__(
        self,
        db_url: str,
        model: str = "gpt-5-mini",
        batch_size: int = 100,
        max_workers: int = 2
    ):
        self.db_url = db_url
        self.model = model
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.extractor = UnifiedExtractor(model=model, db_url=db_url)

        # Stats tracking
        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'total_cost': 0.0,
            'total_entities': 0,
            'total_statements': 0,
            'errors': []
        }

    async def get_unextracted_memories(self, limit: int = None) -> List[Dict[str, Any]]:
        """Get memories that haven't been extracted yet (excluding GitHub/GitLab)"""

        conn = await asyncpg.connect(self.db_url)
        try:
            query = """
            SELECT m.rid, m.content, m.metadata
            FROM koi_memories m
            LEFT JOIN koi_kg_extractions e ON m.rid = e.memory_rid
            WHERE m.superseded_at IS NULL
              AND e.memory_rid IS NULL
              AND m.source_sensor NOT LIKE 'github-sensor%'
              AND m.source_sensor NOT LIKE 'gitlab-sensor%'
              AND LENGTH(m.content::text) > 100
            ORDER BY m.created_at DESC
            """

            if limit:
                query += f" LIMIT {limit}"

            rows = await conn.fetch(query)

            memories = []
            for row in rows:
                content_data = json.loads(row['content']) if isinstance(row['content'], str) else row['content']
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                memories.append({
                    'rid': row['rid'],
                    'content': content_data.get('text', ''),
                    'metadata': metadata
                })

            return memories

        finally:
            await conn.close()

    async def extract_single(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        """Extract KG from a single memory"""

        try:
            # Ensure source_url exists and is not empty
            source_url = memory['metadata'].get('source_url', '')
            if not source_url or source_url.strip() == '':
                # Try fallbacks
                if memory['metadata'].get('url'):
                    memory['metadata']['source_url'] = memory['metadata']['url']
                elif memory['metadata'].get('page_url'):
                    memory['metadata']['source_url'] = memory['metadata']['page_url']
                elif 'parent_rid' in memory['metadata']:
                    # For chunks, use the RID as a fallback source
                    memory['metadata']['source_url'] = memory['rid']
                else:
                    logger.warning(f"No source_url found for {memory['rid']}, skipping")
                    return {'status': 'skipped', 'reason': 'no_source_url'}

            # Run extraction
            extraction_rid, receipt_id = await self.extractor.extract_and_track(
                memory['rid'],
                memory['content'],
                memory['metadata']
            )

            # Get extraction stats
            conn = await asyncpg.connect(self.db_url)
            try:
                stats = await conn.fetchrow("""
                    SELECT
                        jsonb_array_length(entities) as entity_count,
                        jsonb_array_length(statements) as statement_count,
                        confidence_score,
                        cost_usd
                    FROM koi_kg_extractions
                    WHERE extraction_rid = $1
                """, extraction_rid)

                return {
                    'status': 'success',
                    'extraction_rid': extraction_rid,
                    'receipt_id': receipt_id,
                    'entity_count': stats['entity_count'],
                    'statement_count': stats['statement_count'],
                    'confidence': stats['confidence_score'],
                    'cost': stats['cost_usd']
                }
            finally:
                await conn.close()

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"Failed to extract {memory['rid']}: {e}")
            logger.error(f"Traceback: {error_trace}")
            return {
                'status': 'failed',
                'error': str(e) if str(e) else error_trace
            }

    async def process_batch(self, memories: List[Dict[str, Any]]):
        """Process a batch of memories with concurrency control"""

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_workers)

        async def extract_with_semaphore(memory):
            async with semaphore:
                return await self.extract_single(memory)

        # Process batch concurrently
        tasks = [extract_with_semaphore(memory) for memory in memories]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update stats
        for i, result in enumerate(results):
            self.stats['total_processed'] += 1

            if isinstance(result, Exception):
                self.stats['failed'] += 1
                self.stats['errors'].append({
                    'rid': memories[i]['rid'],
                    'error': str(result)
                })
            elif result['status'] == 'success':
                self.stats['successful'] += 1
                self.stats['total_cost'] += float(result.get('cost', 0))
                self.stats['total_entities'] += result.get('entity_count', 0)
                self.stats['total_statements'] += result.get('statement_count', 0)
            elif result['status'] == 'skipped':
                self.stats['skipped'] += 1
            else:
                self.stats['failed'] += 1
                self.stats['errors'].append({
                    'rid': memories[i]['rid'],
                    'error': result.get('error', 'Unknown error')
                })

    async def run(self, limit: int = None, dry_run: bool = False):
        """Run bulk extraction"""

        logger.info(f"Starting bulk extraction (model: {self.model}, batch_size: {self.batch_size})")

        # Get all unextracted memories
        memories = await self.get_unextracted_memories(limit)
        total = len(memories)

        logger.info(f"Found {total} memories to extract (excluding GitHub/GitLab)")

        if dry_run:
            logger.info("DRY RUN - would process:")
            for i, memory in enumerate(memories[:5], 1):
                logger.info(f"  {i}. {memory['rid'][:60]}...")
            if total > 5:
                logger.info(f"  ... and {total - 5} more")
            return

        # Process in batches
        start_time = datetime.now()

        for i in range(0, total, self.batch_size):
            batch = memories[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size

            logger.info(f"\n📦 Batch {batch_num}/{total_batches} ({len(batch)} docs)")

            await self.process_batch(batch)

            # Progress update
            elapsed = (datetime.now() - start_time).total_seconds()
            rate = self.stats['total_processed'] / elapsed if elapsed > 0 else 0
            remaining = total - self.stats['total_processed']
            eta = remaining / rate if rate > 0 else 0

            logger.info(f"✓ Progress: {self.stats['total_processed']}/{total} docs")
            logger.info(f"  Success: {self.stats['successful']} | Failed: {self.stats['failed']} | Skipped: {self.stats['skipped']}")
            logger.info(f"  Cost so far: ${self.stats['total_cost']:.2f}")
            logger.info(f"  Rate: {rate:.1f} docs/sec | ETA: {eta/60:.1f} min")

        # Final summary
        logger.info("\n" + "="*80)
        logger.info("BULK EXTRACTION COMPLETE")
        logger.info("="*80)
        logger.info(f"Total Processed: {self.stats['total_processed']}")
        logger.info(f"Successful: {self.stats['successful']}")
        logger.info(f"Failed: {self.stats['failed']}")
        logger.info(f"Skipped: {self.stats['skipped']}")
        logger.info(f"Total Entities: {self.stats['total_entities']}")
        logger.info(f"Total Statements: {self.stats['total_statements']}")
        logger.info(f"Total Cost: ${self.stats['total_cost']:.2f}")
        logger.info(f"Avg Cost/Doc: ${self.stats['total_cost']/max(self.stats['successful'],1):.4f}")

        if self.stats['errors']:
            logger.info(f"\nErrors ({len(self.stats['errors'])}):")
            for error in self.stats['errors'][:10]:
                logger.info(f"  - {error['rid'][:60]}: {error['error'][:100]}")
            if len(self.stats['errors']) > 10:
                logger.info(f"  ... and {len(self.stats['errors']) - 10} more")


async def main():
    """Main entry point"""

    import argparse

    parser = argparse.ArgumentParser(description='Bulk KG Extraction')
    parser.add_argument('--limit', type=int, help='Limit number of documents to process')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    parser.add_argument('--workers', type=int, default=2, help='Max parallel workers (default: 2)')
    parser.add_argument('--model', type=str, default='gpt-4o-mini', help='Model to use (default: gpt-4o-mini)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (show what would be processed)')

    args = parser.parse_args()

    # Get database URL
    db_url = os.getenv('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5433/eliza')

    # Create extractor
    extractor = BulkExtractor(
        db_url=db_url,
        model=args.model,
        batch_size=args.batch_size,
        max_workers=args.workers
    )

    # Run extraction
    await extractor.run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
