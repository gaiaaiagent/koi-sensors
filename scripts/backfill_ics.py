#!/usr/bin/env python3
"""
Backfill ICS calendar attachments from already-indexed emails.

Modes:
  - Proton: DB → IMAP SEARCH HEADER Message-ID → extract → process_ics_attachments
  - Gmail: DB → Maildir scan (Message-ID match + content_hash fallback with
    uniqueness gate) → extract → process_ics_attachments
  - --embed-only: backfill embeddings for existing ICS events (no re-fetch;
    useful when the sensor ran while the embedder was down). Can use a direct
    embedder URL override via --embedder-url.
"""

import argparse
import asyncio
import email
import hashlib
import json
import logging
import os
import re
import ssl
import subprocess
import sys
from email import policy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "sensors" / "email"))

from proton_imap_fetcher import ProtonIMAPFetcher
from maildir_parser import MaildirParser
from chunker import SentenceAwareChunker
from embedder import EmailEmbedder
from ics_writer import process_ics_attachments

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('backfill_ics')


def load_proton_config() -> dict:
    path = REPO_ROOT / "sensors" / "email" / "proton_config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def load_gmail_config() -> dict:
    path = REPO_ROOT / "sensors" / "email" / "config.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


class DirectEmbedder:
    """Minimal drop-in replacement for EmailEmbedder that calls an override URL.

    Used by --embed-only when the sensor's configured bge_server_url is dead but
    an alternative embedder URL is reachable (e.g., the poly service).
    Supports both `/encode {text: ...}` and `/embed {texts: [...]}` shapes —
    detects by POST attempt.
    """

    def __init__(self, url: str, dimension: int = 1024):
        self.url = url
        self.dimension = dimension
        self._client = httpx.AsyncClient(timeout=30.0)
        self._shape = None  # 'singular' or 'batch'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self._client.aclose()

    async def _detect_shape(self):
        if self._shape is not None:
            return
        try:
            resp = await self._client.post(self.url, json={"texts": ["probe"]})
            if resp.status_code == 200:
                d = resp.json()
                if d.get('embeddings'):
                    self._shape = 'batch'
                    return
        except Exception:
            pass
        self._shape = 'singular'

    async def embed_text(self, text: str):
        result = await self.embed_batch([text])
        return result[0] if result else None

    async def embed_batch(self, texts):
        if not texts:
            return []
        await self._detect_shape()
        try:
            if self._shape == 'batch':
                resp = await self._client.post(self.url, json={"texts": list(texts)})
                resp.raise_for_status()
                d = resp.json()
                embs = d.get('embeddings') or []
                return [e if isinstance(e, list) and len(e) == self.dimension else None for e in embs]
            else:
                results = []
                for t in texts:
                    resp = await self._client.post(self.url, json={"text": t})
                    if resp.status_code != 200:
                        results.append(None)
                        continue
                    d = resp.json()
                    e = d.get('embedding')
                    results.append(e if isinstance(e, list) and len(e) == self.dimension else None)
                return results
        except Exception as exc:
            logger.error(f"DirectEmbedder failed: {exc}")
            return [None] * len(texts)

    async def embed_chunks(self, chunks):
        texts = [c.get('text', '') for c in chunks]
        return await self.embed_batch(texts)


def normalize_message_id(raw: Optional[str]) -> str:
    if not raw:
        return ''
    val = raw.strip()
    val = val.lstrip('<').rstrip('>').strip()
    return val


async def fetch_pending_proton(pool: asyncpg.Pool, scan_all: bool, only_rid: Optional[str]):
    if only_rid:
        query = """
            SELECT em.rid, em.message_id, em.memory_id
            FROM email_metadata em
            JOIN koi_memories km ON km.id = em.memory_id
            WHERE em.rid = $1
        """
        return await pool.fetch(query, only_rid)

    if scan_all:
        query = """
            SELECT em.rid, em.message_id, em.memory_id
            FROM email_metadata em
            JOIN koi_memories km ON km.id = em.memory_id
            WHERE em.rid LIKE 'orn:proton.message:%'
            ORDER BY em.date_sent DESC
        """
        return await pool.fetch(query)

    query = """
        SELECT em.rid, em.message_id, em.memory_id
        FROM email_metadata em
        JOIN koi_memories km ON km.id = em.memory_id
        WHERE em.rid LIKE 'orn:proton.message:%'
          AND (km.metadata->>'ics_processing_state' IS DISTINCT FROM 'done')
          AND (em.has_attachments = true
               OR km.metadata->>'has_inline_calendar' = 'true'
               OR km.metadata->>'ics_processing_state' = 'pending')
        ORDER BY em.date_sent DESC
    """
    return await pool.fetch(query)


def imap_search_fetch(fetcher: ProtonIMAPFetcher, message_id: str) -> Optional[bytes]:
    """SEARCH HEADER Message-ID across configured folders, prefer INBOX > Sent > Archive."""
    if not fetcher._conn:
        raise RuntimeError("fetcher not connected")

    folder_priority = ['INBOX', 'Sent', 'Archive']
    folders_to_try = [f for f in folder_priority if f in fetcher.folders]
    folders_to_try += [f for f in fetcher.folders if f not in folders_to_try]

    normalized = normalize_message_id(message_id)
    if not normalized:
        return None

    for folder in folders_to_try:
        try:
            status, _ = fetcher._conn.select(folder, readonly=True)
            if status != 'OK':
                continue
            status, uid_data = fetcher._conn.uid(
                'SEARCH', None, 'HEADER', 'Message-ID', f'<{normalized}>'
            )
            if status != 'OK' or not uid_data or not uid_data[0]:
                continue
            uids = uid_data[0].split()
            if not uids:
                continue
            uid = uids[-1]  # highest UID in folder
            status, msg_data = fetcher._conn.uid('FETCH', uid, '(BODY.PEEK[])')
            if status != 'OK' or not msg_data or not msg_data[0]:
                continue
            if isinstance(msg_data[0], tuple):
                raw = msg_data[0][1]
                # Post-FETCH verification
                try:
                    parsed = email.message_from_bytes(raw, policy=policy.default)
                    fetched_mid = normalize_message_id(parsed.get('Message-ID', ''))
                    if fetched_mid and fetched_mid != normalized:
                        logger.warning(
                            f"IMAP fetch returned wrong email (expected {normalized}, got {fetched_mid})"
                        )
                        continue
                except Exception:
                    continue
                return raw
        except Exception as e:
            logger.debug(f"SEARCH in {folder} failed: {e}")
            continue
    return None


async def main():
    parser = argparse.ArgumentParser(description="Backfill ICS attachments from indexed emails")
    parser.add_argument('--dry-run', action='store_true', help='List candidates, do not write')
    parser.add_argument('--provider', choices=['proton', 'gmail', 'both'], default='proton',
                        help='Provider to backfill')
    parser.add_argument('--scan-all', action='store_true',
                        help='Proton-only: skip idempotency filter, scan all proton emails')
    parser.add_argument('--only-rid', type=str, default=None,
                        help='Process a single email rid (for targeted backfill)')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--embed-only', action='store_true',
                        help='Backfill embeddings+chunks for existing ICS events; no re-fetch')
    parser.add_argument('--embedder-url', type=str, default=None,
                        help='Override embedder URL (bypasses sensor config)')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = load_proton_config()
    db_url = cfg['koi_backend']['database_url']
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgres://')

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)
    try:
        # --embed-only branch: no IMAP/Maildir, just regenerate chunks/embeddings
        if args.embed_only:
            return await run_embed_only(pool, cfg, args.embedder_url)

        # Gmail-only branch
        if args.provider == 'gmail':
            return await run_gmail_backfill(pool, args.dry_run, args.only_rid, args.embedder_url)

        # Default: Proton (or 'both')
        proton_rc = await run_proton_backfill(pool, cfg, args)
        if args.provider == 'both':
            gmail_rc = await run_gmail_backfill(pool, args.dry_run, args.only_rid, args.embedder_url)
            return proton_rc if proton_rc != 0 else gmail_rc
        return proton_rc
    finally:
        await pool.close()


async def run_proton_backfill(pool, cfg, args) -> int:
    candidates = await fetch_pending_proton(pool, args.scan_all, args.only_rid)
    logger.info(f"Found {len(candidates)} candidate Proton emails")

    if args.dry_run:
        for row in candidates:
            logger.info(f"  [dry-run] {row['rid']} mid={row['message_id']}")
        return 0

    if not candidates:
        logger.info("No Proton candidates — nothing to do")
        return 0

    fetcher = ProtonIMAPFetcher(
        host=cfg['imap'].get('host', '127.0.0.1'),
        port=cfg['imap'].get('port', 1143),
        username=cfg['imap'].get('username', ''),
        password=cfg['imap'].get('password'),
        password_cmd=cfg['imap'].get('password_cmd'),
        folders=cfg['imap'].get('folders', ['INBOX']),
        exclude_folders=cfg['imap'].get('exclude_folders', []),
        max_age_years=cfg['filtering'].get('max_age_years', 5),
        min_body_length=cfg['filtering'].get('min_body_length', 50),
        max_email_size=cfg['filtering'].get('max_email_size', 10 * 1024 * 1024),
    )
    fetcher.connect()
    logger.info("Connected to Proton Bridge IMAP")

    chunker = SentenceAwareChunker(
        chunk_size=cfg['chunking'].get('chunk_size', 500),
        chunk_overlap=cfg['chunking'].get('chunk_overlap', 50),
        min_chunk_size=cfg['chunking'].get('min_chunk_size', 100),
    )
    embedder = _make_embedder(cfg, args.embedder_url if hasattr(args, 'embedder_url') else None)

    try:
        no_match = 0
        processed = 0
        async with embedder:
            for row in candidates:
                email_rid = row['rid']
                message_id = row['message_id']
                parent_memory_id = row['memory_id']
                logger.info(f"Processing {email_rid} (mid={message_id})")

                raw_bytes = imap_search_fetch(fetcher, message_id)
                if not raw_bytes:
                    logger.warning(f"  no IMAP match for {email_rid}")
                    no_match += 1
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE koi_memories SET metadata = jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{ics_processing_state}', '"pending"'::jsonb
                            ) WHERE rid = $1
                              AND (metadata->>'ics_processing_state' IS DISTINCT FROM 'done')
                            """,
                            email_rid,
                        )
                    continue

                msg = email.message_from_bytes(raw_bytes, policy=policy.default)
                attachments = ProtonIMAPFetcher._extract_attachments(msg)
                ics_atts = [a for a in attachments if a.get('ics_payload')]
                if not ics_atts:
                    logger.info(f"  no ICS MIME parts for {email_rid}")
                    continue

                logger.info(f"  {len(ics_atts)} ICS attachment(s) to process")
                had_exc, had_parse = await process_ics_attachments(
                    pool, attachments, email_rid, parent_memory_id,
                    'proton', embedder, chunker,
                )
                processed += 1
                logger.info(f"  result: had_exc={had_exc} had_parse_errors={had_parse}")

        logger.info(f"Proton done: processed={processed}, no_match={no_match}, total={len(candidates)}")
        if candidates:
            deno = len(candidates)
            if no_match / deno > 0.50:
                logger.error(f"HALT: >50% no-match rate ({no_match}/{deno} emails failed)")
                return 2
    finally:
        try:
            fetcher.disconnect()
        except Exception:
            pass
    return 0


def _make_embedder(cfg: dict, override_url: Optional[str]):
    """Return a DirectEmbedder if override_url is provided, else the sensor's EmailEmbedder."""
    if override_url:
        logger.info(f"Using DirectEmbedder at {override_url}")
        return DirectEmbedder(override_url, dimension=cfg.get('embeddings', {}).get('dimension', 1024))
    return EmailEmbedder(
        bge_server_url=cfg['embeddings'].get('bge_server_url', 'http://localhost:8091/encode'),
        dimension=cfg['embeddings'].get('dimension', 1024),
        batch_size=cfg['embeddings'].get('batch_size', 20),
        doc_embedding_tokens=cfg['embeddings'].get('doc_embedding_tokens', 512),
    )


def _normalize_mid(raw: Optional[str]) -> str:
    if not raw:
        return ''
    return raw.strip().lstrip('<').rstrip('>').strip()


async def run_gmail_backfill(pool, dry_run: bool, only_rid: Optional[str],
                             embedder_url: Optional[str]) -> int:
    """Backfill ICS from Gmail Maildir. Match by Message-ID, fallback to content_hash."""
    cfg = load_gmail_config()
    maildir_base = os.path.expanduser(cfg['maildir']['base_path'])
    if not os.path.isdir(maildir_base):
        logger.error(f"Gmail maildir not found: {maildir_base}")
        return 1

    # Query DB
    if only_rid:
        q = """SELECT em.rid, em.message_id, em.memory_id, em.content_hash
               FROM email_metadata em WHERE em.rid = $1"""
        rows = await pool.fetch(q, only_rid)
    else:
        q = """
            SELECT em.rid, em.message_id, em.memory_id, em.content_hash
            FROM email_metadata em
            JOIN koi_memories km ON km.id = em.memory_id
            WHERE em.rid LIKE 'orn:gmail.message:%'
              AND (km.metadata->>'ics_processing_state' IS DISTINCT FROM 'done')
              AND (em.has_attachments = true
                   OR km.metadata->>'has_inline_calendar' = 'true'
                   OR km.metadata->>'ics_processing_state' = 'pending')
            ORDER BY em.date_sent DESC NULLS LAST
        """
        rows = await pool.fetch(q)
    logger.info(f"Found {len(rows)} candidate Gmail emails")

    if dry_run:
        for row in rows:
            logger.info(f"  [dry-run] {row['rid']} mid={row['message_id']}")
        return 0
    if not rows:
        return 0

    # Build a Message-ID → [paths] index of maildir once
    logger.info(f"Scanning Gmail maildir {maildir_base} ...")
    mid_index: Dict[str, List[str]] = {}
    all_files: List[str] = []
    for root, dirs, files in os.walk(maildir_base):
        for f in files:
            # Maildir files have no extension; cur/new/tmp dirs
            p = os.path.join(root, f)
            if not os.path.isfile(p):
                continue
            all_files.append(p)
            try:
                with open(p, 'rb') as fh:
                    # Read only headers (first 16KB) for Message-ID
                    head = fh.read(16384)
                msg = email.message_from_bytes(head, policy=policy.default)
                mid = _normalize_mid(msg.get('Message-ID', ''))
                if mid:
                    mid_index.setdefault(mid, []).append(p)
            except Exception:
                continue
    logger.info(f"Indexed {sum(len(v) for v in mid_index.values())} files by Message-ID out of {len(all_files)} total")

    # MaildirParser instance for body extraction (content_hash fallback)
    mp = MaildirParser.__new__(MaildirParser)
    mp.min_body_length = 50

    # Embedder + chunker
    chunker = SentenceAwareChunker(
        chunk_size=cfg.get('chunking', {}).get('chunk_size', 500),
        chunk_overlap=cfg.get('chunking', {}).get('chunk_overlap', 50),
        min_chunk_size=cfg.get('chunking', {}).get('min_chunk_size', 100),
    )
    embedder = _make_embedder(cfg, embedder_url)

    no_match = 0
    processed = 0
    async with embedder:
        for row in rows:
            email_rid = row['rid']
            mid = _normalize_mid(row['message_id'])
            content_hash = row['content_hash']
            parent_memory_id = row['memory_id']
            candidates_paths: List[str] = []

            # Primary match by Message-ID
            if mid and mid in mid_index:
                for p in mid_index[mid]:
                    try:
                        with open(p, 'rb') as fh:
                            msg = email.message_from_bytes(fh.read(), policy=policy.default)
                        fmid = _normalize_mid(msg.get('Message-ID', ''))
                        # Uniqueness gate: match confirmed
                        if fmid and fmid == mid:
                            candidates_paths.append(p)
                    except Exception:
                        continue

            # Fallback: content_hash (only if MID lookup failed and content_hash present)
            if not candidates_paths and content_hash:
                for p in all_files:
                    try:
                        with open(p, 'rb') as fh:
                            msg = email.message_from_bytes(fh.read(), policy=policy.default)
                        fmid = _normalize_mid(msg.get('Message-ID', ''))
                        # Uniqueness gate fail-closed:
                        #  REJECT if em.message_id non-empty but file lacks Message-ID
                        if mid and not fmid:
                            continue
                        #  REJECT if both non-empty and mismatch
                        if mid and fmid and fmid != mid:
                            continue
                        body_text, body_html = mp._extract_body(msg)
                        if len(body_text) < mp.min_body_length and body_html:
                            body_text = mp._html_to_text(body_html)
                        h = hashlib.sha256(body_text.encode('utf-8')).hexdigest()
                        if h == content_hash:
                            candidates_paths.append(p)
                    except Exception:
                        continue

            if not candidates_paths:
                logger.warning(f"  no Maildir match for {email_rid} (mid={mid})")
                no_match += 1
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE koi_memories SET metadata = jsonb_set(
                            COALESCE(metadata, '{}'::jsonb),
                            '{ics_processing_state}', '"pending"'::jsonb
                        ) WHERE rid = $1
                          AND (metadata->>'ics_processing_state' IS DISTINCT FROM 'done')
                        """,
                        email_rid,
                    )
                continue

            # Ambiguity resolution
            if len(candidates_paths) > 1:
                # All confirmed-MID-match (unique by MID) → pick most-recently modified
                picked = max(candidates_paths, key=lambda p: os.path.getmtime(p))
                logger.info(f"  {len(candidates_paths)} candidates, picked most-recent: {picked}")
            else:
                picked = candidates_paths[0]

            # Parse + process
            try:
                with open(picked, 'rb') as fh:
                    msg = email.message_from_bytes(fh.read(), policy=policy.default)
                attachments = mp._extract_attachments(msg)
                ics_atts = [a for a in attachments if a.get('ics_payload')]
                if not ics_atts:
                    logger.info(f"  no ICS MIME parts for {email_rid}")
                    continue
                logger.info(f"  {len(ics_atts)} ICS attachment(s) to process from {picked}")
                had_exc, had_parse = await process_ics_attachments(
                    pool, attachments, email_rid, parent_memory_id,
                    'gmail', embedder, chunker,
                )
                processed += 1
                logger.info(f"  result: had_exc={had_exc} had_parse_errors={had_parse}")
            except Exception as exc:
                logger.error(f"  failed processing {email_rid} from {picked}: {exc}")

    logger.info(f"Gmail done: processed={processed}, no_match={no_match}, total={len(rows)}")
    if rows:
        deno = len(rows)
        if no_match / deno > 0.50:
            logger.error(f"HALT: Gmail >50% no-match rate ({no_match}/{deno})")
            return 2
    return 0


async def run_embed_only(pool, cfg: dict, embedder_url: Optional[str]) -> int:
    """Backfill doc-level embeddings + chunk embeddings for existing ics-event rows.

    No re-fetch; uses stored content text. Idempotent (ON CONFLICT DO UPDATE).
    """
    if not embedder_url:
        # Use sensor config
        embedder_url_cfg = cfg.get('embeddings', {}).get('bge_server_url')
        # Probe configured URL
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.post(embedder_url_cfg, json={"text": "probe"})
                if r.status_code != 200:
                    raise RuntimeError(f"status {r.status_code}")
        except Exception as e:
            logger.error(f"Embedder unreachable at {embedder_url_cfg}: {e}")
            logger.error("Pass --embedder-url <url> to override (e.g. http://10.100.0.1:8352/embed)")
            return 1

    chunker = SentenceAwareChunker(
        chunk_size=cfg.get('chunking', {}).get('chunk_size', 500),
        chunk_overlap=cfg.get('chunking', {}).get('chunk_overlap', 50),
        min_chunk_size=cfg.get('chunking', {}).get('min_chunk_size', 100),
    )
    embedder = _make_embedder(cfg, embedder_url)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.id, m.rid, m.content->>'text' AS event_text
            FROM koi_memories m
            WHERE m.source_sensor = 'ics-event'
              AND (
                NOT EXISTS (SELECT 1 FROM koi_embeddings e
                            WHERE e.memory_id = m.id AND e.dim_1024 IS NOT NULL)
                OR NOT EXISTS (SELECT 1 FROM koi_memory_chunks c
                               WHERE c.document_rid = m.rid AND c.embedding IS NOT NULL)
              )
            ORDER BY m.created_at
        """)
    logger.info(f"Found {len(rows)} ics-event rows needing embeddings")
    if not rows:
        return 0

    def _vec_literal(v):
        if not v:
            return None
        return '[' + ','.join(str(x) for x in v) + ']'

    updated = 0
    async with embedder:
        for row in rows:
            memory_id = row['id']
            event_rid = row['rid']
            event_text = row['event_text'] or ''
            if not event_text.strip():
                continue
            # Doc-level
            doc_emb = await embedder.embed_text(event_text)
            if doc_emb:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO koi_embeddings (memory_id, dim_1024)
                        VALUES ($1::uuid, $2::vector)
                        ON CONFLICT (memory_id) DO UPDATE SET dim_1024 = EXCLUDED.dim_1024
                        """,
                        memory_id, _vec_literal(doc_emb),
                    )
            # Chunks
            chunks = chunker.chunk_text(event_text)
            if chunks:
                chunk_embs = await embedder.embed_chunks(chunks)
                total = len(chunks)
                async with pool.acquire() as conn:
                    for chunk, emb in zip(chunks, chunk_embs):
                        ci = chunk.get('index', 0)
                        chunk_rid = f"orn:ics.chunk:{event_rid}:{ci}"
                        chunk_content = {
                            'text': chunk.get('text', ''),
                            'context': f"ICS event {ci + 1}/{total}",
                        }
                        await conn.execute(
                            """
                            INSERT INTO koi_memory_chunks
                              (chunk_rid, document_rid, chunk_index, total_chunks,
                               content, embedding, created_at)
                            VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector, NOW())
                            ON CONFLICT (chunk_rid) DO UPDATE SET
                              content = EXCLUDED.content,
                              embedding = EXCLUDED.embedding,
                              total_chunks = EXCLUDED.total_chunks,
                              created_at = NOW()
                            """,
                            chunk_rid, event_rid, ci, total,
                            json.dumps(chunk_content), _vec_literal(emb),
                        )
            updated += 1
            if updated % 5 == 0:
                logger.info(f"  ... embedded {updated}/{len(rows)}")

    logger.info(f"Embed-only done: {updated}/{len(rows)} rows updated")
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
