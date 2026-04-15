#!/usr/bin/env python3
"""
Email Sensor for Personal-KOI
Indexes Gmail Maildir emails into the personal knowledge graph

Architecture:
1. Reads emails from local Maildir (synced via mbsync)
2. Filters by age, folder, category
3. Writes to koi_memories + koi_embeddings + koi_memory_chunks
4. Stores email metadata in email_metadata table
5. Extracts entities and links via /ingest endpoint
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, urlunparse
import yaml

import asyncpg
import httpx

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.persistent_state import PersistentSensorState
from shared.rid_types.communication import GmailMessage as GmailMessageRID, GmailAttachment as GmailAttachmentRID

from maildir_parser import MaildirParser
from chunker import SentenceAwareChunker
from embedder import EmailEmbedder
from ics_writer import process_ics_attachments

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmailSensor:
    """
    Main email sensor class.

    Processes Maildir emails and ingests into personal-KOI.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize email sensor.

        Args:
            config_path: Path to config.yaml (defaults to same directory)
        """
        # Load configuration
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Initialize components
        self.maildir = MaildirParser(
            base_path=os.path.expanduser(self.config['maildir']['base_path']),
            exclude_folders=self.config['maildir'].get('exclude_folders', []),
            exclude_categories=self.config['maildir'].get('exclude_categories', []),
            max_age_years=self.config['filtering'].get('max_age_years', 5),
            min_body_length=self.config['filtering'].get('min_body_length', 50),
            max_email_size=self.config['filtering'].get('max_email_size', 10 * 1024 * 1024),
        )

        self.chunker = SentenceAwareChunker(
            chunk_size=self.config['chunking'].get('chunk_size', 500),
            chunk_overlap=self.config['chunking'].get('chunk_overlap', 50),
            min_chunk_size=self.config['chunking'].get('min_chunk_size', 100),
        )

        self.embedder = EmailEmbedder(
            bge_server_url=self.config['embeddings'].get('bge_server_url', 'http://localhost:8351/embed'),
            dimension=self.config['embeddings'].get('dimension', 1024),
            batch_size=self.config['embeddings'].get('batch_size', 20),
            doc_embedding_tokens=self.config['embeddings'].get('doc_embedding_tokens', 512),
        )

        # Persistent state for tracking processed emails
        self.state = PersistentSensorState('email', Path(__file__).parent)

        # Storage configuration
        self.source_sensor = self.config['storage'].get('source_sensor', 'email-sensor')
        self.is_private = self.config['storage'].get('is_private', True)
        self.access_source = self.config['storage'].get('access_source', 'email-sensor')

        koi_backend = self.config.get('koi_backend', {})

        # Database connection
        self.db_url = self._resolve_backend_setting(
            configured_value=koi_backend.get('database_url'),
            env_var_names=('PERSONAL_KOI_DB_URL', 'KOI_DATABASE_URL', 'DATABASE_URL'),
            default=None,
            required=True,
            setting_name='koi_backend.database_url'
        )
        self.db_pool: Optional[asyncpg.Pool] = None

        # API client for entity extraction
        self.api_url = self._resolve_backend_setting(
            configured_value=koi_backend.get('api_url'),
            env_var_names=('PERSONAL_KOI_API_URL', 'KOI_API_URL', 'KOI_BACKEND_URL'),
            default='http://localhost:8351',
            required=False,
            setting_name='koi_backend.api_url'
        )
        self.http_client: Optional[httpx.AsyncClient] = None

        logger.info(f"Email sensor initialized")
        logger.info(f"  Maildir: {self.maildir.base_path}")
        logger.info(f"  Database: {self._redact_db_url(self.db_url)}")

    @staticmethod
    def _resolve_backend_setting(
        configured_value: Optional[str],
        env_var_names: tuple[str, ...],
        default: Optional[str],
        required: bool,
        setting_name: str,
    ) -> str:
        """
        Resolve backend setting with env override support.

        Precedence:
        1. First non-empty env var in env_var_names
        2. configured_value from config.yaml
        3. default (if provided)
        """
        for env_var in env_var_names:
            env_value = os.getenv(env_var)
            if env_value:
                return env_value

        if configured_value:
            return configured_value

        if default:
            return default

        if required:
            env_hint = ', '.join(env_var_names)
            raise ValueError(
                f"Missing required setting '{setting_name}'. "
                f"Set it in config.yaml or one of: {env_hint}"
            )

        # For type safety; required=False call sites should always pass default.
        return ''

    @staticmethod
    def _redact_db_url(db_url: str) -> str:
        """Redact password in postgres URL before logging."""
        try:
            parsed = urlparse(db_url)
            if not parsed.password:
                return db_url

            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return urlunparse(parsed._replace(netloc=netloc))
        except Exception:
            return "<redacted>"

    async def connect(self):
        """Establish database and HTTP connections."""
        # Parse database URL for asyncpg
        db_url = self.db_url
        if not db_url:
            raise ValueError("Database URL is empty. Set PERSONAL_KOI_DB_URL or koi_backend.database_url.")

        if db_url.startswith('postgresql://'):
            db_url = db_url.replace('postgresql://', 'postgres://')

        self.db_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(timeout=60.0)
        logger.info("Database and HTTP connections established")

    async def close(self):
        """Close connections."""
        if self.db_pool:
            await self.db_pool.close()
        if self.http_client:
            await self.http_client.aclose()

    async def __aenter__(self):
        await self.connect()
        await self.embedder.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.embedder.__aexit__(exc_type, exc_val, exc_tb)
        await self.close()

    def _generate_rid(self, email_data: Dict[str, Any]) -> str:
        """Generate RID for email."""
        message_id = email_data.get('message_id', '')
        rid = GmailMessageRID.from_raw_message_id(message_id)
        return str(rid)

    def _generate_chunk_rid(self, email_rid: str, chunk_index: int) -> str:
        """Generate deterministic chunk RID."""
        return f"{email_rid}#chunk{chunk_index}"

    async def process_email(self, email_data: Dict[str, Any]) -> Optional[str]:
        """
        Process a single email and ingest into database.

        Args:
            email_data: Parsed email dict from MaildirParser

        Returns:
            RID of processed email, or None if skipped
        """
        message_id = email_data.get('message_id', '')

        # Check if already processed (using message_id hash as state key)
        state_key = hashlib.sha256(message_id.encode()).hexdigest()[:16]
        if self.state.is_processed(state_key):
            logger.debug(f"Skipping already processed email: {message_id}")
            return None

        # Check if content has changed
        content_hash = email_data.get('content_hash', '')
        old_hash = self.state.metadata.get(f"hash_{state_key}")

        if old_hash == content_hash:
            logger.debug(f"Skipping unchanged email: {message_id}")
            return None

        # Generate RID
        email_rid = self._generate_rid(email_data)
        logger.info(f"Processing email: {email_data.get('subject', '(no subject)')[:50]}")

        try:
            # Prepare email content for storage
            subject = email_data.get('subject', '')
            body = email_data.get('body_text', '')
            full_text = f"Subject: {subject}\n\n{body}" if subject else body

            # Create koi_memories record
            memory_id = await self._upsert_memory(email_rid, email_data, full_text, content_hash)

            if not memory_id:
                logger.error(f"Failed to create memory for: {message_id}")
                return None

            # Generate and store doc-level embedding
            doc_embedding = await self.embedder.embed_email_doc(email_data)
            if doc_embedding:
                await self._upsert_embedding(memory_id, doc_embedding)

            # Chunk and embed
            chunks = self.chunker.chunk_email(email_data)
            if chunks:
                await self._upsert_chunks(email_rid, memory_id, chunks)

            # Store email metadata
            await self._upsert_email_metadata(memory_id, email_rid, email_data)

            # ICS calendar attachments (mirrors proton_sensor wiring)
            attachments = email_data.get('attachments', []) or []
            has_ics_attachment = any(a.get('ics_payload') for a in attachments)
            has_inline_calendar = any(a.get('is_inline_calendar') for a in attachments)

            if has_inline_calendar:
                try:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE koi_memories SET metadata = jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{has_inline_calendar}', 'true'::jsonb
                            ) WHERE rid = $1
                            """,
                            email_rid,
                        )
                except Exception as e:
                    logger.error(f"Failed to set has_inline_calendar for {email_rid}: {e}")

            if has_ics_attachment:
                try:
                    import uuid as _uuid
                    pm_id = memory_id if isinstance(memory_id, _uuid.UUID) else _uuid.UUID(str(memory_id))
                    await process_ics_attachments(
                        self.db_pool, attachments, email_rid, pm_id,
                        'gmail', self.embedder, self.chunker,
                    )
                except Exception as e:
                    logger.error(f"ICS processing failed for {email_rid}: {e}")
                    import traceback
                    traceback.print_exc()

            # Extract and link entities (optional)
            if self.config['entity_extraction'].get('enabled', True):
                await self._extract_entities(email_rid, email_data, full_text)

            # Mark as processed
            self.state.mark_processed('email', state_key)
            self.state.metadata[f"hash_{state_key}"] = content_hash
            self.state.save()

            logger.info(f"  ✅ Processed: {email_rid}")
            return email_rid

        except Exception as e:
            logger.error(f"Error processing email {message_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _upsert_memory(
        self,
        rid: str,
        email_data: Dict[str, Any],
        full_text: str,
        content_hash: str,
    ) -> Optional[str]:
        """
        Insert or update email in koi_memories.

        Uses ON CONFLICT to handle updates.

        Returns:
            memory_id UUID as string
        """
        subject = email_data.get('subject', '')
        from_name = email_data.get('from_name', '')
        from_address = email_data.get('from_address', '')
        date_sent = email_data.get('date_sent')

        # Build content JSONB
        content = {
            'text': full_text,
            'title': subject,
        }

        # Build metadata JSONB
        metadata = {
            'source': 'email',
            'content_hash': content_hash,
            'from_address': from_address,
            'from_name': from_name,
            'subject': subject,
            'folder': email_data.get('folder', 'INBOX'),
            'labels': email_data.get('labels', []),
            'has_attachments': len(email_data.get('attachments', [])) > 0,
        }

        if date_sent:
            metadata['date_sent'] = date_sent.isoformat()

        # Upsert query with ON CONFLICT
        query = """
        INSERT INTO koi_memories (
            rid, event_type, source_sensor, content, metadata,
            is_private, access_source, created_at, updated_at
        ) VALUES (
            $1, 'NEW', $2, $3::jsonb, $4::jsonb,
            $5, $6, NOW(), NOW()
        )
        ON CONFLICT (rid) DO UPDATE SET
            content = EXCLUDED.content,
            metadata = EXCLUDED.metadata,
            is_private = EXCLUDED.is_private,
            access_source = EXCLUDED.access_source,
            event_type = 'UPDATE',
            updated_at = NOW()
        WHERE COALESCE(koi_memories.metadata->>'content_hash', '') !=
              COALESCE(EXCLUDED.metadata->>'content_hash', '')
        RETURNING id::text
        """

        try:
            row = await self.db_pool.fetchrow(
                query,
                rid,
                self.source_sensor,
                json.dumps(content),
                json.dumps(metadata),
                self.is_private,
                self.access_source,
            )

            if row:
                return row['id']

            # If no row returned, it means content_hash matched (no update needed)
            # Fetch existing memory_id
            existing = await self.db_pool.fetchrow(
                "SELECT id::text FROM koi_memories WHERE rid = $1",
                rid
            )
            return existing['id'] if existing else None

        except Exception as e:
            logger.error(f"Failed to upsert memory: {e}")
            return None

    async def _upsert_embedding(self, memory_id: str, embedding: List[float]):
        """Upsert doc-level embedding to koi_embeddings."""
        query = """
        INSERT INTO koi_embeddings (memory_id, dim_1024)
        VALUES ($1::uuid, $2::vector)
        ON CONFLICT (memory_id) DO UPDATE SET
            dim_1024 = EXCLUDED.dim_1024
        """

        try:
            # Format embedding for pgvector
            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
            await self.db_pool.execute(query, memory_id, embedding_str)
        except Exception as e:
            logger.error(f"Failed to upsert embedding: {e}")

    async def _upsert_chunks(
        self,
        document_rid: str,
        memory_id: str,
        chunks: List[Dict[str, Any]],
    ):
        """Upsert chunks to koi_memory_chunks."""
        # First, embed all chunks
        embeddings = await self.embedder.embed_chunks(chunks)

        for chunk, embedding in zip(chunks, embeddings):
            chunk_rid = self._generate_chunk_rid(document_rid, chunk['index'])
            total_chunks = chunk.get('total_chunks', len(chunks))

            content = {
                'text': chunk['text'],
                'context': f"Email chunk {chunk['index'] + 1}/{total_chunks}",
            }

            query = """
            INSERT INTO koi_memory_chunks (
                chunk_rid, document_rid, chunk_index, total_chunks,
                content, embedding, created_at
            ) VALUES (
                $1, $2, $3, $4, $5::jsonb, $6::vector, NOW()
            )
            ON CONFLICT (chunk_rid) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                total_chunks = EXCLUDED.total_chunks
            """

            try:
                embedding_str = None
                if embedding:
                    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'

                await self.db_pool.execute(
                    query,
                    chunk_rid,
                    document_rid,
                    chunk['index'],
                    total_chunks,
                    json.dumps(content),
                    embedding_str,
                )
            except Exception as e:
                logger.error(f"Failed to upsert chunk {chunk_rid}: {e}")

    async def _upsert_email_metadata(
        self,
        memory_id: str,
        rid: str,
        email_data: Dict[str, Any],
    ):
        """Upsert email metadata to email_metadata table."""
        query = """
        INSERT INTO email_metadata (
            memory_id, rid, message_id, thread_id,
            from_address, from_name, to_addresses, cc_addresses,
            subject, date_sent, labels, has_attachments, attachment_count,
            content_hash, folder, created_at, updated_at
        ) VALUES (
            $1::uuid, $2, $3, $4,
            $5, $6, $7, $8,
            $9, $10, $11, $12, $13,
            $14, $15, NOW(), NOW()
        )
        ON CONFLICT (rid) DO UPDATE SET
            thread_id = EXCLUDED.thread_id,
            labels = EXCLUDED.labels,
            has_attachments = EXCLUDED.has_attachments,
            attachment_count = EXCLUDED.attachment_count,
            content_hash = EXCLUDED.content_hash,
            folder = EXCLUDED.folder,
            updated_at = NOW()
        """

        attachments = email_data.get('attachments', [])
        date_sent = email_data.get('date_sent')

        try:
            await self.db_pool.execute(
                query,
                memory_id,
                rid,
                email_data.get('message_id', ''),
                email_data.get('thread_id'),
                email_data.get('from_address', ''),
                email_data.get('from_name'),
                email_data.get('to_addresses', []),
                email_data.get('cc_addresses', []),
                email_data.get('subject', ''),
                date_sent,
                email_data.get('labels', []),
                len(attachments) > 0,
                len(attachments),
                email_data.get('content_hash', ''),
                email_data.get('folder', 'INBOX'),
            )
        except Exception as e:
            logger.error(f"Failed to upsert email metadata: {e}")

    async def _extract_entities(
        self,
        email_rid: str,
        email_data: Dict[str, Any],
        full_text: str,
    ):
        """
        Extract entities from email and call /ingest endpoint.

        Extracts:
        - Person entities from From/To/Cc headers
        - Organization from email domains
        """
        entities = []

        # Extract sender as Person entity
        from_name = email_data.get('from_name', '')
        from_address = email_data.get('from_address', '')
        if from_name and from_name != from_address:
            entities.append({
                'name': from_name,
                'type': 'Person',
                'confidence': 0.95,
                'context': f'Email sender: {from_address}',
            })

        # Extract organization from domain
        if from_address and '@' in from_address:
            domain = from_address.split('@')[1].lower()
            # Skip common providers
            if domain not in ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com']:
                org_name = domain.split('.')[0].replace('-', ' ').title()
                entities.append({
                    'name': org_name,
                    'type': 'Organization',
                    'confidence': 0.7,
                    'context': f'Email domain: {domain}',
                })

        # Skip if no entities to extract
        if not entities:
            return

        # Call /ingest endpoint
        try:
            response = await self.http_client.post(
                f"{self.api_url}/ingest",
                json={
                    'document_rid': email_rid,
                    'content': full_text[:2000],  # Truncate for context
                    'entities': entities,
                    'source': 'email-sensor',
                },
                timeout=30.0,
            )

            if response.status_code == 200:
                logger.debug(f"  Extracted {len(entities)} entities")
            else:
                logger.warning(f"Entity extraction failed: {response.status_code}")

        except Exception as e:
            logger.error(f"Entity extraction error: {e}")

    async def run_scan(self, limit: Optional[int] = None) -> Dict[str, int]:
        """
        Run a full scan of the Maildir.

        Args:
            limit: Maximum number of emails to process (for testing)

        Returns:
            Stats dict with counts
        """
        stats = {
            'scanned': 0,
            'processed': 0,
            'skipped': 0,
            'errors': 0,
        }

        logger.info("Starting Maildir scan...")

        async with self:
            for email_data in self.maildir.scan_all():
                stats['scanned'] += 1

                if limit and stats['processed'] >= limit:
                    logger.info(f"Reached limit of {limit} emails")
                    break

                rid = await self.process_email(email_data)
                if rid:
                    stats['processed'] += 1
                else:
                    stats['skipped'] += 1

                # Log progress every 100 emails
                if stats['scanned'] % 100 == 0:
                    logger.info(f"Progress: {stats['scanned']} scanned, {stats['processed']} processed")

        logger.info(f"Scan complete: {stats}")
        return stats

    async def process_single_file(self, file_path: str) -> Optional[str]:
        """
        Process a single email file.

        Useful for real-time processing when new emails arrive.

        Args:
            file_path: Path to email file

        Returns:
            RID if processed, None if skipped
        """
        email_path = Path(file_path)
        if not email_path.exists():
            logger.error(f"Email file not found: {file_path}")
            return None

        email_data = self.maildir.parse_email(email_path)
        if not email_data:
            return None

        # Get folder from path
        try:
            rel_path = email_path.relative_to(self.maildir.base_path)
            parts = rel_path.parts[:-2]  # Remove cur/new and filename
            email_data['folder'] = '/'.join(parts) if parts else 'INBOX'
        except Exception:
            email_data['folder'] = 'INBOX'

        async with self:
            return await self.process_email(email_data)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Email Sensor for Personal-KOI')
    parser.add_argument('--config', type=str, help='Path to config.yaml')
    parser.add_argument('--limit', type=int, help='Limit number of emails to process')
    parser.add_argument('--file', type=str, help='Process single email file')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')

    args = parser.parse_args()

    sensor = EmailSensor(config_path=args.config)

    if args.file:
        # Process single file
        rid = await sensor.process_single_file(args.file)
        if rid:
            print(f"Processed: {rid}")
        else:
            print("Email skipped or failed")
    elif args.daemon:
        # Daemon mode - run periodic scans
        scan_interval = sensor.config['runtime'].get('scan_interval', 30) * 60
        logger.info(f"Running in daemon mode, scan interval: {scan_interval}s")

        while True:
            try:
                stats = await sensor.run_scan(limit=args.limit)
                logger.info(f"Scan complete: {stats['processed']} new emails processed")
            except Exception as e:
                logger.error(f"Scan failed: {e}")

            logger.info(f"Sleeping for {scan_interval}s until next scan...")
            await asyncio.sleep(scan_interval)
    else:
        # One-shot scan
        stats = await sensor.run_scan(limit=args.limit)
        print(f"\nScan complete:")
        print(f"  Scanned: {stats['scanned']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Skipped: {stats['skipped']}")


if __name__ == '__main__':
    asyncio.run(main())
