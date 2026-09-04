#!/usr/bin/env python3
"""
Proton Mail Sensor for Personal-KOI
Indexes Proton Mail emails via Proton Bridge IMAP into the personal knowledge graph.

Reuses the existing EmailSensor processing pipeline (chunking, embedding,
metadata, entity extraction). Only the transport layer differs: IMAP instead
of Maildir.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any
from urllib.parse import urlparse, urlunparse
import yaml

import asyncpg
import httpx

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.persistent_state import PersistentSensorState
from shared.rid_types.communication import ProtonMessage as ProtonMessageRID

from proton_imap_fetcher import ProtonIMAPFetcher
from chunker import SentenceAwareChunker
from embedder import EmailEmbedder
from ics_writer import process_ics_attachments
from email_entity_extractor import is_valid_person_name

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProtonEmailSensor:
    """
    Proton Mail sensor that fetches via Bridge IMAP and ingests into KOI.

    Reuses the same DB schema, chunker, embedder, and entity extraction
    as the Gmail EmailSensor. Distinguished by RID namespace (proton.message).
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "proton_config.yaml"

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        imap_cfg = self.config['imap']
        self.fetcher = ProtonIMAPFetcher(
            host=imap_cfg.get('host', '127.0.0.1'),
            port=imap_cfg.get('port', 1143),
            username=imap_cfg.get('username', ''),
            password=imap_cfg.get('password'),
            password_cmd=imap_cfg.get('password_cmd'),
            folders=imap_cfg.get('folders', ['INBOX']),
            exclude_folders=imap_cfg.get('exclude_folders', []),
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
            bge_server_url=self.config['embeddings'].get('bge_server_url', 'http://localhost:8091/encode'),
            dimension=self.config['embeddings'].get('dimension', 1024),
            batch_size=self.config['embeddings'].get('batch_size', 20),
            doc_embedding_tokens=self.config['embeddings'].get('doc_embedding_tokens', 512),
        )

        self.state = PersistentSensorState('proton-email', Path(__file__).parent)
        self.source_sensor = self.config['storage'].get('source_sensor', 'email-sensor')
        self.is_private = self.config['storage'].get('is_private', True)
        self.access_source = self.config['storage'].get('access_source', 'email-sensor')

        koi_backend = self.config.get('koi_backend', {})
        self.db_url = self._resolve_setting(
            configured_value=koi_backend.get('database_url'),
            env_var_names=('PERSONAL_KOI_DB_URL', 'KOI_DATABASE_URL', 'DATABASE_URL'),
            default=None, required=True, setting_name='koi_backend.database_url'
        )
        self.api_url = self._resolve_setting(
            configured_value=koi_backend.get('api_url'),
            env_var_names=('PERSONAL_KOI_API_URL', 'KOI_API_URL', 'KOI_BACKEND_URL'),
            default='http://localhost:8351', required=False, setting_name='koi_backend.api_url'
        )

        self.db_pool: Optional[asyncpg.Pool] = None
        self.http_client: Optional[httpx.AsyncClient] = None

        logger.info("Proton email sensor initialized")
        logger.info(f"  IMAP: {self.fetcher.host}:{self.fetcher.port}")
        logger.info(f"  Folders: {self.fetcher.folders}")
        logger.info(f"  Database: {self._redact_url(self.db_url)}")

    @staticmethod
    def _resolve_setting(configured_value, env_var_names, default, required, setting_name):
        for env_var in env_var_names:
            val = os.getenv(env_var)
            if val:
                return val
        if configured_value:
            return configured_value
        if default:
            return default
        if required:
            raise ValueError(f"Missing required setting '{setting_name}'")
        return ''

    @staticmethod
    def _redact_url(url: str) -> str:
        try:
            parsed = urlparse(url)
            if not parsed.password:
                return url
            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return urlunparse(parsed._replace(netloc=netloc))
        except Exception:
            return "<redacted>"

    async def connect(self):
        db_url = self.db_url
        if db_url.startswith('postgresql://'):
            db_url = db_url.replace('postgresql://', 'postgres://')
        self.db_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)
        self.http_client = httpx.AsyncClient(timeout=60.0)
        logger.info("Database and HTTP connections established")

    async def close(self):
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
        message_id = email_data.get('message_id', '')
        rid = ProtonMessageRID.from_raw_message_id(message_id)
        return str(rid)

    def _generate_chunk_rid(self, email_rid: str, chunk_index: int) -> str:
        return f"{email_rid}#chunk{chunk_index}"

    async def process_email(self, email_data: Dict[str, Any]) -> Optional[str]:
        """Process a single email and ingest into KOI."""
        message_id = email_data.get('message_id', '')
        state_key = hashlib.sha256(message_id.encode()).hexdigest()[:16]

        if self.state.is_processed(state_key):
            return None

        content_hash = email_data.get('content_hash', '')
        old_hash = self.state.metadata.get(f"hash_{state_key}")
        if old_hash == content_hash:
            return None

        email_rid = self._generate_rid(email_data)
        logger.info(f"Processing: {email_data.get('subject', '(no subject)')[:50]}")

        try:
            subject = email_data.get('subject', '')
            body = email_data.get('body_text', '')
            full_text = f"Subject: {subject}\n\n{body}" if subject else body

            memory_id = await self._upsert_memory(email_rid, email_data, full_text, content_hash)
            if not memory_id:
                logger.error(f"Failed to create memory for: {message_id}")
                return None

            doc_embedding = await self.embedder.embed_email_doc(email_data)
            if doc_embedding:
                await self._upsert_embedding(memory_id, doc_embedding)

            chunks = self.chunker.chunk_email(email_data)
            if chunks:
                await self._upsert_chunks(email_rid, memory_id, chunks)

            await self._upsert_email_metadata(memory_id, email_rid, email_data)

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
                        'proton', self.embedder, self.chunker,
                    )
                except Exception as e:
                    logger.error(f"ICS processing failed for {email_rid}: {e}")
                    import traceback
                    traceback.print_exc()

            if self.config['entity_extraction'].get('enabled', True):
                await self._extract_entities(email_rid, email_data, full_text)

            self.state.mark_processed('proton-email', state_key)
            self.state.metadata[f"hash_{state_key}"] = content_hash
            self.state.save()

            logger.info(f"  Processed: {email_rid}")
            return email_rid

        except Exception as e:
            logger.error(f"Error processing email {message_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _upsert_memory(self, rid, email_data, full_text, content_hash):
        subject = email_data.get('subject', '')
        from_name = email_data.get('from_name', '')
        from_address = email_data.get('from_address', '')
        date_sent = email_data.get('date_sent')

        content = {'text': full_text, 'title': subject}
        metadata = {
            'source': 'proton-email',
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
            is_private = (koi_memories.is_private OR EXCLUDED.is_private),
            access_source = COALESCE(koi_memories.access_source, EXCLUDED.access_source),
            event_type = 'UPDATE',
            updated_at = NOW()
        WHERE COALESCE(koi_memories.metadata->>'content_hash', '') !=
              COALESCE(EXCLUDED.metadata->>'content_hash', '')
        RETURNING id::text
        """
        try:
            row = await self.db_pool.fetchrow(
                query, rid, self.source_sensor,
                json.dumps(content), json.dumps(metadata),
                self.is_private, self.access_source,
            )
            if row:
                return row['id']
            existing = await self.db_pool.fetchrow(
                "SELECT id::text FROM koi_memories WHERE rid = $1", rid
            )
            return existing['id'] if existing else None
        except Exception as e:
            logger.error(f"Failed to upsert memory: {e}")
            return None

    async def _upsert_embedding(self, memory_id, embedding):
        query = """
        INSERT INTO koi_embeddings (memory_id, dim_1024)
        VALUES ($1::uuid, $2::vector)
        ON CONFLICT (memory_id) DO UPDATE SET dim_1024 = EXCLUDED.dim_1024
        """
        try:
            embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
            await self.db_pool.execute(query, memory_id, embedding_str)
        except Exception as e:
            logger.error(f"Failed to upsert embedding: {e}")

    async def _upsert_chunks(self, document_rid, memory_id, chunks):
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
                    query, chunk_rid, document_rid,
                    chunk['index'], total_chunks,
                    json.dumps(content), embedding_str,
                )
            except Exception as e:
                logger.error(f"Failed to upsert chunk {chunk_rid}: {e}")

    async def _upsert_email_metadata(self, memory_id, rid, email_data):
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
        try:
            attachments = email_data.get('attachments', [])
            await self.db_pool.execute(
                query,
                memory_id, rid,
                email_data.get('message_id', ''),
                email_data.get('thread_id'),
                email_data.get('from_address', ''),
                email_data.get('from_name'),
                email_data.get('to_addresses', []),
                email_data.get('cc_addresses', []),
                email_data.get('subject', ''),
                email_data.get('date_sent'),
                email_data.get('labels', []),
                len(attachments) > 0,
                len(attachments),
                email_data.get('content_hash', ''),
                email_data.get('folder', 'INBOX'),
            )
        except Exception as e:
            logger.error(f"Failed to upsert email metadata: {e}")

    async def _extract_entities(self, email_rid, email_data, full_text):
        if not self.http_client:
            return
        try:
            # Extract header entities (from, to, cc as Person entities)
            entities = []
            from_name = email_data.get('from_name', '')
            from_addr = email_data.get('from_address', '')
            # is_valid_person_name() is the shared guard hoisted in 368e759
            # (sensors/email/email_entity_extractor.py). That commit wired
            # email_sensor.py and its message says "BOTH call sites" -- there
            # are THREE Person-construction sites, and this one was missed, so
            # the proton path kept minting a Person from any display name that
            # merely differed from the address local-part.
            if (
                from_name
                and from_name != from_addr.split('@')[0]
                and is_valid_person_name(from_name)
            ):
                entities.append({
                    'name': from_name,
                    'type': 'Person',
                    'confidence': 0.9,
                    'context': f"Email sender: {from_addr}",
                    'mentions': [f"From: {from_name} <{from_addr}>"],
                })

            if entities:
                payload = {
                    'document_rid': email_rid,
                    'entities': entities,
                    'relationships': [],
                    'source': 'proton-email',
                }
                response = await self.http_client.post(
                    f"{self.api_url}/ingest", json=payload
                )
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"  Entities: {result.get('stats', {}).get('total_entities', 0)} extracted")
                else:
                    logger.warning(f"Entity extraction failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Entity extraction error: {e}")

    async def run_scan(self, limit: Optional[int] = None) -> Dict[str, int]:
        """Run a scan across all configured Proton folders."""
        stats = {'scanned': 0, 'processed': 0, 'skipped': 0, 'errors': 0}

        logger.info("Starting Proton Mail scan...")

        try:
            self.fetcher.connect()
        except ConnectionError as e:
            logger.error(f"Cannot connect to Proton Bridge: {e}")
            return stats

        try:
            async with self:
                for folder in self.fetcher.folders:
                    if folder.upper() in self.fetcher.exclude_folders:
                        continue

                    # Load per-folder state
                    uid_key = f"proton_uid_{folder}"
                    uidval_key = f"proton_uidvalidity_{folder}"
                    last_uid = int(self.state.metadata.get(uid_key, 0))

                    # Check UIDVALIDITY — reset if changed
                    current_uidval = self.fetcher.get_uidvalidity(folder)
                    stored_uidval = self.state.metadata.get(uidval_key)
                    if stored_uidval and current_uidval and int(stored_uidval) != current_uidval:
                        logger.warning(
                            f"UIDVALIDITY changed for {folder} "
                            f"({stored_uidval} -> {current_uidval}), resetting UID cursor"
                        )
                        last_uid = 0

                    logger.info(f"Scanning {folder} (UIDs > {last_uid})")

                    max_uid_seen = last_uid
                    for email_data in self.fetcher.fetch_new_emails(folder, last_uid):
                        stats['scanned'] += 1

                        if limit and stats['processed'] >= limit:
                            logger.info(f"Reached limit of {limit} emails")
                            break

                        email_data['folder'] = folder
                        uid = email_data.pop('uid', 0)

                        rid = await self.process_email(email_data)
                        if rid:
                            stats['processed'] += 1
                        else:
                            stats['skipped'] += 1

                        if uid > max_uid_seen:
                            max_uid_seen = uid

                        if stats['scanned'] % 50 == 0:
                            logger.info(f"Progress: {stats['scanned']} scanned, {stats['processed']} processed")

                    # Persist per-folder cursor
                    if max_uid_seen > last_uid:
                        self.state.metadata[uid_key] = str(max_uid_seen)
                    if current_uidval:
                        self.state.metadata[uidval_key] = str(current_uidval)
                    self.state.save()

                    if limit and stats['processed'] >= limit:
                        break

        finally:
            self.fetcher.disconnect()

        logger.info(f"Scan complete: {stats}")
        return stats


async def main():
    import argparse

    parser = argparse.ArgumentParser(description='Proton Mail Sensor for Personal-KOI')
    parser.add_argument('--config', type=str, help='Path to proton_config.yaml')
    parser.add_argument('--limit', type=int, help='Limit number of emails to process')
    parser.add_argument('--daemon', action='store_true', help='Run as daemon')
    parser.add_argument('--list-folders', action='store_true', help='List IMAP folders and exit')

    args = parser.parse_args()

    sensor = ProtonEmailSensor(config_path=args.config)

    if args.list_folders:
        sensor.fetcher.connect()
        folders = sensor.fetcher.get_folder_list()
        print("Available folders:")
        for f in folders:
            print(f"  {f}")
        sensor.fetcher.disconnect()
        return

    if args.daemon:
        scan_interval = sensor.config['runtime'].get('scan_interval', 15) * 60
        logger.info(f"Running in daemon mode, scan interval: {scan_interval}s")

        while True:
            try:
                stats = await sensor.run_scan(limit=args.limit)
                logger.info(f"Scan complete: {stats['processed']} new emails processed")
            except Exception as e:
                logger.error(f"Scan failed: {e}")
                import traceback
                traceback.print_exc()

            logger.info(f"Sleeping for {scan_interval}s until next scan...")
            await asyncio.sleep(scan_interval)
    else:
        stats = await sensor.run_scan(limit=args.limit)
        print(f"\nScan complete:")
        print(f"  Scanned: {stats['scanned']}")
        print(f"  Processed: {stats['processed']}")
        print(f"  Skipped: {stats['skipped']}")


if __name__ == '__main__':
    asyncio.run(main())
