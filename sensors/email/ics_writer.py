"""
ICS Writer: shared ICS ingestion logic for email sensors.

Consumes parsed VEVENT dicts from ics_parser.parse_ics_bytes and writes:
- koi_memories row per VEVENT (source_sensor='ics-event')
- koi_memory_chunks + koi_embeddings for text search
- email_attachments marker row (idempotency)
- Metadata flags on the parent email koi_memories row

Shared between proton_sensor.py, email_sensor.py, and scripts/backfill_ics.py.
All callers import this via flat sys.path insert of sensors/email/.
"""

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

try:
    from sensors.email.ics_parser import format_event_text, parse_ics_bytes
except ImportError:
    from ics_parser import format_event_text, parse_ics_bytes

logger = logging.getLogger(__name__)


def _compute_att_rid(email_rid: str, att_index: int) -> str:
    digest = hashlib.sha256(f"{email_rid}{att_index}".encode()).hexdigest()[:16]
    return f"orn:ics.attachment:{digest}"


def _compute_chunk_rid(event_rid: str, chunk_index: int) -> str:
    return f"orn:ics.chunk:{event_rid}:{chunk_index}"


def _to_vector_literal(embedding: Optional[List[float]]) -> Optional[str]:
    if not embedding:
        return None
    return '[' + ','.join(str(x) for x in embedding) + ']'


def _incoming_is_newer(new_meta: Dict[str, Any], stored_meta: Optional[Dict[str, Any]]) -> bool:
    """Decide whether an incoming VEVENT should overwrite an existing row.

    Rules (from plan Assumptions "VEVENT version update rule"):
      1. Both SEQUENCE present, unequal → higher wins
      2. Both SEQUENCE present, equal → newer DTSTAMP wins (if equal → overwrite)
      3. Either SEQUENCE absent → compare DTSTAMP (newer or equal overwrites)
      4. Both absent → always overwrite (conservative)
    """
    if not stored_meta:
        return True
    new_seq = new_meta.get('sequence')
    stored_seq = stored_meta.get('sequence') if stored_meta else None
    if new_seq is not None and stored_seq is not None:
        try:
            new_seq_i = int(new_seq)
            stored_seq_i = int(stored_seq)
        except (TypeError, ValueError):
            new_seq_i = stored_seq_i = 0
        if new_seq_i != stored_seq_i:
            return new_seq_i > stored_seq_i
    new_dt = new_meta.get('dtstamp') or ''
    stored_dt = (stored_meta.get('dtstamp') or '') if stored_meta else ''
    return new_dt >= stored_dt


def _dedup_by_uid(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        uid = ev.get('uid')
        if not uid:
            continue
        if uid not in best or _incoming_is_newer(ev, best[uid]):
            best[uid] = ev
    return list(best.values())


def _build_event_metadata(event: Dict[str, Any], parent_email_rid: str) -> Dict[str, Any]:
    def _iso(dt):
        return dt.isoformat() if dt is not None else None

    return {
        'uid': event['uid'],
        'dtstart': _iso(event.get('dtstart_utc')),
        'dtend': _iso(event.get('dtend_utc')),
        'status': event.get('status'),
        'location': event.get('location'),
        'organizer': event.get('organizer'),
        'attendees': event.get('attendees') or [],
        'sequence': event.get('sequence'),
        'dtstamp': event.get('dtstamp'),
        'rrule_text': event.get('rrule_text'),
        'email_rid': parent_email_rid,
        'method': event.get('method'),
    }


async def _store_event(
    conn: asyncpg.Connection,
    event: Dict[str, Any],
    parent_email_rid: str,
    embedder,
    chunker,
) -> Tuple[Optional[uuid.UUID], bool]:
    """Upsert a single VEVENT with version-gated semantics.

    Returns (row_id, version_written). version_written=False means stored version wins
    and chunk/embedding writes should be skipped.
    """
    event_rid = event['event_rid']
    new_meta = _build_event_metadata(event, parent_email_rid)
    summary = event.get('summary') or event['uid']
    event_text = format_event_text(event)
    content = {'text': event_text, 'title': summary}

    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id, metadata FROM koi_memories WHERE rid = $1 FOR UPDATE NOWAIT",
            event_rid,
        )
        if existing:
            stored_meta = existing['metadata']
            if isinstance(stored_meta, str):
                try:
                    stored_meta = json.loads(stored_meta)
                except Exception:
                    stored_meta = {}
            stored_uid = (stored_meta or {}).get('uid')
            if stored_uid and stored_uid != event['uid']:
                logger.error(
                    f"RID hash collision for rid={event_rid}: "
                    f"stored_uid={stored_uid!r} incoming_uid={event['uid']!r}"
                )
                return existing['id'], False
            if not _incoming_is_newer(new_meta, stored_meta):
                return existing['id'], False

        new_id = uuid.uuid4()
        row_id = await conn.fetchval(
            """
            INSERT INTO koi_memories
                (id, rid, content, metadata, source_sensor, access_source,
                 is_private, event_type, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, 'ics-event', 'email-ics',
                    false, 'NEW', NOW(), NOW())
            ON CONFLICT (rid) DO UPDATE SET
                content = EXCLUDED.content,
                metadata = EXCLUDED.metadata,
                event_type = 'UPDATE',
                updated_at = NOW()
            WHERE (
                (EXCLUDED.metadata->>'sequence' IS NULL
                 OR koi_memories.metadata->>'sequence' IS NULL)
                AND COALESCE(EXCLUDED.metadata->>'dtstamp','')
                    >= COALESCE(koi_memories.metadata->>'dtstamp','')
                OR (EXCLUDED.metadata->>'sequence' IS NOT NULL
                    AND koi_memories.metadata->>'sequence' IS NOT NULL
                    AND ((EXCLUDED.metadata->>'sequence')::int
                         > (koi_memories.metadata->>'sequence')::int
                         OR ((EXCLUDED.metadata->>'sequence')::int
                             = (koi_memories.metadata->>'sequence')::int
                             AND COALESCE(EXCLUDED.metadata->>'dtstamp','')
                                 >= COALESCE(koi_memories.metadata->>'dtstamp',''))))
            )
            RETURNING id
            """,
            new_id, event_rid, json.dumps(content), json.dumps(new_meta),
        )

        version_written = row_id is not None
        if not version_written:
            row_id = await conn.fetchval(
                "SELECT id FROM koi_memories WHERE rid = $1", event_rid
            )
        else:
            if existing:
                await conn.execute(
                    "DELETE FROM koi_memory_chunks WHERE document_rid = $1",
                    event_rid,
                )

    return row_id, version_written


async def _write_event_chunks_and_embedding(
    conn: asyncpg.Connection,
    event: Dict[str, Any],
    row_id: uuid.UUID,
    embedder,
    chunker,
) -> None:
    """Write doc-level embedding + sentence-aware chunks. Embedder/chunker calls are out-of-txn."""
    event_rid = event['event_rid']
    event_text = format_event_text(event)

    try:
        doc_embedding = await embedder.embed_text(event_text)
    except Exception as e:
        logger.warning(f"ics_writer: doc embed failed for {event_rid}: {e}")
        doc_embedding = None

    if doc_embedding:
        vec = _to_vector_literal(doc_embedding)
        try:
            await conn.execute(
                """
                INSERT INTO koi_embeddings (memory_id, dim_1024)
                VALUES ($1::uuid, $2::vector)
                ON CONFLICT (memory_id) DO UPDATE SET dim_1024 = EXCLUDED.dim_1024
                """,
                row_id, vec,
            )
        except Exception as e:
            logger.warning(f"ics_writer: doc embedding upsert failed for {event_rid}: {e}")

    chunks = chunker.chunk_text(event_text)
    if not chunks:
        return

    try:
        chunk_embeddings = await embedder.embed_chunks(chunks)
    except Exception as e:
        logger.warning(f"ics_writer: chunk embed failed for {event_rid}: {e}")
        chunk_embeddings = [None] * len(chunks)

    total = len(chunks)
    for chunk, emb in zip(chunks, chunk_embeddings):
        chunk_index = chunk.get('index', 0)
        chunk_rid = _compute_chunk_rid(event_rid, chunk_index)
        chunk_content = {
            'text': chunk.get('text', ''),
            'context': f"ICS event {chunk_index + 1}/{total}",
        }
        emb_literal = _to_vector_literal(emb)
        try:
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
                chunk_rid, event_rid, chunk_index, total,
                json.dumps(chunk_content), emb_literal,
            )
        except Exception as e:
            logger.warning(f"ics_writer: chunk upsert failed for {chunk_rid}: {e}")


async def _append_event_rid_to_parent(
    conn: asyncpg.Connection, parent_email_rid: str, event_rid: str
) -> None:
    await conn.execute(
        """
        UPDATE koi_memories SET metadata = jsonb_set(
            COALESCE(metadata, '{}'::jsonb),
            '{ics_event_rids}',
            COALESCE(metadata->'ics_event_rids', '[]'::jsonb) || to_jsonb($1::text)
        ) WHERE rid = $2
        """,
        event_rid, parent_email_rid,
    )


async def _set_parent_flag(
    conn: asyncpg.Connection, parent_email_rid: str, key: str, value: Any,
    only_if_not_done: bool = False,
) -> None:
    """Set a metadata flag on the parent email koi_memories row.

    If only_if_not_done=True, won't overwrite ics_processing_state='done'.
    """
    if only_if_not_done:
        await conn.execute(
            """
            UPDATE koi_memories SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb), $1::text[], $2::jsonb
            ) WHERE rid = $3
              AND (metadata->>'ics_processing_state' IS DISTINCT FROM 'done')
            """,
            [key], json.dumps(value), parent_email_rid,
        )
    else:
        await conn.execute(
            """
            UPDATE koi_memories SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb), $1::text[], $2::jsonb
            ) WHERE rid = $3
            """,
            [key], json.dumps(value), parent_email_rid,
        )


async def process_ics_attachments(
    pool: asyncpg.Pool,
    attachments: List[Dict[str, Any]],
    email_rid: str,
    parent_memory_id: uuid.UUID,
    provider: str,
    embedder,
    chunker,
) -> Tuple[bool, bool]:
    """Process ICS attachments for one email.

    Args:
        pool: asyncpg pool (we acquire connections internally per-attachment)
        attachments: list of dicts from _extract_attachments() with ics_payload bytes
        email_rid: RID of the parent email koi_memories row
        parent_memory_id: UUID of the parent email koi_memories row
        provider: 'proton' or 'gmail'
        embedder: EmailEmbedder instance
        chunker: SentenceAwareChunker instance

    Returns:
        (had_exception, had_parse_errors)
    """
    had_exception = False
    had_parse_errors = False
    any_ics = False

    for att in attachments:
        ics_payload = att.get('ics_payload')
        if not ics_payload:
            continue
        any_ics = True
        att_index = att.get('index', 0)
        att_rid = _compute_att_rid(email_rid, att_index)

        try:
            async with pool.acquire() as conn:
                existing_marker = await conn.fetchrow(
                    "SELECT 1 FROM email_attachments WHERE rid = $1", att_rid
                )
            if existing_marker:
                logger.info(f"ics_writer: attachment {att_rid} already processed (idempotency skip)")
                continue
        except Exception as e:
            logger.error(f"ics_writer: idempotency check failed for {att_rid}: {e}")
            had_exception = True
            continue

        try:
            events, parse_errs = parse_ics_bytes(ics_payload, provider, email_rid, att_index)
            if parse_errs:
                had_parse_errors = True
            events = _dedup_by_uid(events)

            first_event_rid: Optional[str] = None
            async with pool.acquire() as conn:
                for event in events:
                    row_id, version_written = await _store_event(
                        conn, event, email_rid, embedder, chunker
                    )
                    if first_event_rid is None:
                        first_event_rid = event['event_rid']
                    if version_written and row_id is not None:
                        await _write_event_chunks_and_embedding(
                            conn, event, row_id, embedder, chunker
                        )
                    await _append_event_rid_to_parent(
                        conn, email_rid, event['event_rid']
                    )

                await conn.execute(
                    """
                    INSERT INTO email_attachments
                        (rid, parent_memory_id, filename, content_type, size_bytes,
                         content_hash, extracted_text_rid, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                    ON CONFLICT (rid) DO NOTHING
                    """,
                    att_rid, parent_memory_id,
                    att.get('filename'),
                    att.get('content_type'),
                    att.get('size'),
                    att.get('content_hash'),
                    first_event_rid,
                )

        except Exception as e:
            logger.error(f"ics_writer: failed processing attachment {att_rid}: {e}")
            had_exception = True

    if any_ics:
        try:
            async with pool.acquire() as conn:
                if had_exception:
                    await _set_parent_flag(
                        conn, email_rid, 'ics_processing_state', 'pending',
                        only_if_not_done=True,
                    )
                else:
                    await _set_parent_flag(
                        conn, email_rid, 'ics_processing_state', 'done',
                    )
                if had_parse_errors:
                    await _set_parent_flag(
                        conn, email_rid, 'ics_has_parse_errors', True,
                    )
        except Exception as e:
            logger.error(f"ics_writer: state flag update failed for {email_rid}: {e}")

    return had_exception, had_parse_errors
