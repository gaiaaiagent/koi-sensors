#!/usr/bin/env python3
"""
KOI Claude Sessions Sensor - Indexes Claude Code session transcripts

This sensor:
1. Scans Claude Code session JSONL files
2. Chunks conversations by turn pairs
3. Generates embeddings via OpenAI
4. Links mentions to existing entities in personal KOI
5. Stores in PostgreSQL with pgvector for semantic search

Runs as:
- Daemon mode: Periodic scans to catch any missed sessions
- Hook mode: Real-time processing via SessionEnd hook
"""

import asyncio
import asyncpg
import json
import hashlib
import os
import re
import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import requests
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('claude_sessions_sensor')

# OpenAI for embeddings
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not available. Embeddings disabled.")


@dataclass
class SessionChunk:
    """A chunk from a Claude Code session"""
    session_id: str
    chunk_index: int
    chunk_text: str
    role: str  # 'user', 'assistant', 'context'
    timestamp: Optional[datetime] = None
    embedding: Optional[List[float]] = None


@dataclass
class SessionMetadata:
    """Metadata about a Claude Code session"""
    session_id: str
    transcript_path: str
    project_path: str
    summary: Optional[str] = None
    first_prompt: Optional[str] = None
    message_count: int = 0
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    file_mtime: Optional[float] = None
    source_host: str = 'macbook'


class EmbeddingTimeout(Exception):
    """Raised when poly embedding endpoint fails after all retry attempts."""
    pass


@dataclass
class ProcessingResult:
    """Result of processing a session"""
    session_id: str
    success: bool
    chunks_created: int = 0
    entities_linked: int = 0
    error: Optional[str] = None


class ClaudeSessionSensor:
    """
    Sensor that indexes Claude Code session transcripts into personal KOI.
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize sensor with configuration."""
        self.config = self._load_config(config_path)
        self.db_pool: Optional[asyncpg.Pool] = None
        self.openai_client: Optional[OpenAI] = None
        self.poly_embed_url: Optional[str] = None
        self.db_url = self._resolve_backend_setting(
            configured_value=self.config.get('koi_backend', {}).get('database_url'),
            env_var_names=('PERSONAL_KOI_DB_URL', 'KOI_DATABASE_URL', 'DATABASE_URL'),
            default=None,
            required=True,
            setting_name='koi_backend.database_url'
        )

        # Back-compat: some legacy call paths still reference self.sessions_base
        # (the singular macbook path). The authoritative iterator is
        # _iter_base_paths(), which reads config.sessions.base_paths (list) or
        # config.sessions.base_path (string). This field is advisory only.
        sessions_cfg = self.config.get('sessions', {})
        legacy_path = sessions_cfg.get('base_path')
        if legacy_path is None and 'base_paths' in sessions_cfg:
            legacy_path = sessions_cfg['base_paths'][0]['path']
        self.sessions_base = Path(os.path.expanduser(legacy_path or '~/.claude/projects'))

        # Stats
        self.stats = {
            'sessions_processed': 0,
            'chunks_created': 0,
            'entities_linked': 0,
            'errors': 0
        }

    def _load_config(self, config_path: Optional[str] = None) -> Dict:
        """Load configuration from YAML file."""
        if config_path is None:
            config_path = Path(__file__).parent / 'config.personal.yaml'

        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    async def initialize(self):
        """Initialize database connection and OpenAI client."""
        # Database connection
        self.db_pool = await asyncpg.create_pool(
            self.db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info(f"Connected to database ({self._redact_db_url(self.db_url)})")

        # Ensure schema exists
        await self._ensure_schema()

        # Poly embedding client (direct HTTP to custom FastAPI service at /embed)
        if self.config['embeddings']['enabled']:
            embed_cfg = self.config.get('embeddings', {})
            api_base = embed_cfg.get('api_base')
            if api_base:
                self.poly_embed_url = api_base
                logger.info(f"Poly embed client initialized (model: {embed_cfg.get('model')}, url: {api_base})")
            else:
                logger.warning("embeddings.api_base not set. Embeddings disabled.")

    @staticmethod
    def _resolve_backend_setting(
        configured_value: Optional[str],
        env_var_names: tuple[str, ...],
        default: Optional[str],
        required: bool,
        setting_name: str,
    ) -> str:
        """Resolve backend settings with env override support."""
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
                f"Set it in config.personal.yaml or one of: {env_hint}"
            )

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

    async def _ensure_schema(self):
        """Ensure required tables exist."""
        async with self.db_pool.acquire() as conn:
            # Session ingestion tracking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_ingestion_log (
                    session_id TEXT PRIMARY KEY,
                    transcript_path TEXT NOT NULL,
                    project_path TEXT,
                    summary TEXT,
                    first_prompt TEXT,
                    message_count INT DEFAULT 0,
                    chunk_count INT DEFAULT 0,
                    file_mtime DOUBLE PRECISION,
                    last_ingested_at TIMESTAMP DEFAULT NOW(),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # Session chunks with embeddings
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_chunks (
                    id SERIAL PRIMARY KEY,
                    session_rid TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chunk_index INT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    role TEXT,
                    timestamp TIMESTAMP,
                    embedding vector(1536),
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(session_id, chunk_index)
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_chunks_session_id
                ON session_chunks(session_id)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_chunks_rid
                ON session_chunks(session_rid)
            """)

            # Vector similarity index (HNSW)
            try:
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_chunks_embedding
                    ON session_chunks USING hnsw (embedding vector_cosine_ops)
                """)
            except Exception as e:
                logger.warning(f"Could not create HNSW index (may already exist): {e}")

            # Session-entity links (reuse document_entity_links pattern)
            # Sessions use RID format: claude-session:{session_id}

            # Add metadata columns to session_ingestion_log (if not exist)
            await conn.execute("""
                DO $$
                BEGIN
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS tools_used TEXT[];
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS tool_counts JSONB;
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS mcp_servers TEXT[];
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS files_accessed TEXT[];
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS model TEXT;
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS cwd TEXT;
                    ALTER TABLE session_ingestion_log ADD COLUMN IF NOT EXISTS git_branch TEXT;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            """)

            # Tool usage detail table for queryability
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_tool_usage (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES session_ingestion_log(session_id) ON DELETE CASCADE,
                    tool_name TEXT NOT NULL,
                    call_count INT DEFAULT 1,
                    is_mcp BOOLEAN DEFAULT FALSE,
                    mcp_server TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(session_id, tool_name)
                )
            """)

            # Indexes for tool usage queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_tool_usage_session
                ON session_tool_usage(session_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_tool_usage_tool
                ON session_tool_usage(tool_name)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_tool_usage_mcp
                ON session_tool_usage(mcp_server) WHERE mcp_server IS NOT NULL
            """)

            logger.info("Schema verified/created")

    async def close(self):
        """Close database connections."""
        if self.db_pool:
            await self.db_pool.close()

    # =========================================================================
    # Session Discovery
    # =========================================================================

    def _iter_base_paths(self):
        """Yield (base_path, host_tag) tuples.

        Phase 1: single macbook path from config.sessions.base_path.
        Phase 5b will populate this from config.sessions.base_paths list
        without changing callers. A legacy `base_path` key continues to
        work to avoid a forced config migration on deploy.
        """
        sessions_cfg = self.config['sessions']
        if 'base_paths' in sessions_cfg:
            for entry in sessions_cfg['base_paths']:
                yield (entry['path'], entry.get('host_tag', 'macbook'))
        else:
            base_path = sessions_cfg.get('base_path', '~/.claude/projects')
            yield (base_path, 'macbook')

    def _dead_letter(
        self,
        session_id: str,
        project: str,
        reason: str,
        error: Optional[str] = None,
    ) -> None:
        """Append one JSON line to the session-sensor dead-letter log.

        See plan §1e for the canonical `reason` taxonomy.
        """
        log_dir = Path.home() / '.claude' / 'local' / 'darren-workflow' / 'logs'
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
                'session_id': session_id,
                'project': project,
                'reason': reason,
            }
            if error:
                entry['error'] = error
            with open(log_dir / 'session-sensor-skipped.jsonl', 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            logger.warning(f"Dead-letter write failed: {e}")

    def discover_sessions(self) -> List[SessionMetadata]:
        """Discover all Claude Code sessions across configured base paths.

        Disk scan is authoritative for path/mtime/message_count/content.
        sessions-index.json is overlay-only for advisory fields (summary,
        first_prompt). A stale index cannot cause a disk-resident session
        to be dropped. Collision policy: first base_path wins (plan §
        Session-ID collision policy).
        """
        seen: Dict[str, SessionMetadata] = {}

        for base_path, host_tag in self._iter_base_paths():
            base = Path(base_path).expanduser()
            if not base.exists():
                logger.warning(f"Base path does not exist: {base}")
                continue

            for project_dir in base.iterdir():
                if not project_dir.is_dir():
                    continue

                for sm in self._scan_jsonl_files(project_dir):
                    if sm.session_id in seen:
                        logger.warning(
                            f"Session ID collision for {sm.session_id}: "
                            f"{seen[sm.session_id].transcript_path} vs {sm.transcript_path}"
                        )
                        continue
                    sm.source_host = host_tag
                    seen[sm.session_id] = sm

                index_path = project_dir / 'sessions-index.json'
                if index_path.exists():
                    for sm in self._parse_sessions_index(index_path, project_dir):
                        existing = seen.get(sm.session_id)
                        if existing:
                            if sm.summary:
                                existing.summary = sm.summary
                            if sm.first_prompt:
                                existing.first_prompt = sm.first_prompt
                        else:
                            sm.source_host = host_tag
                            seen[sm.session_id] = sm

        logger.info(f"Discovered {len(seen)} sessions")
        return list(seen.values())

    def _parse_sessions_index(
        self,
        index_path: Path,
        project_dir: Path
    ) -> List[SessionMetadata]:
        """Parse sessions-index.json for session metadata."""
        sessions = []

        try:
            with open(index_path, 'r') as f:
                index_data = json.load(f)

            if not isinstance(index_data, dict):
                raise ValueError(
                    f"sessions-index.json is not a dict: got {type(index_data).__name__}"
                )

            for entry in index_data.get('entries', []):
                session_id = entry.get('sessionId')
                if not session_id:
                    continue

                # Get transcript path
                transcript_path = entry.get('fullPath')
                if not transcript_path or not Path(transcript_path).exists():
                    # Try constructing path
                    transcript_path = str(project_dir / f"{session_id}.jsonl")
                    if not Path(transcript_path).exists():
                        continue

                # Get file mtime (disk is authoritative; index values are advisory)
                file_mtime = Path(transcript_path).stat().st_mtime

                # Parse dates
                created_at = None
                modified_at = None
                if entry.get('created'):
                    try:
                        created_at = datetime.fromisoformat(
                            entry['created'].replace('Z', '+00:00')
                        )
                    except:
                        pass
                if entry.get('modified'):
                    try:
                        modified_at = datetime.fromisoformat(
                            entry['modified'].replace('Z', '+00:00')
                        )
                    except:
                        pass

                sessions.append(SessionMetadata(
                    session_id=session_id,
                    transcript_path=transcript_path,
                    project_path=entry.get('projectPath', str(project_dir)),
                    summary=entry.get('summary'),
                    first_prompt=entry.get('firstPrompt'),
                    message_count=entry.get('messageCount', 0),
                    created_at=created_at,
                    modified_at=modified_at,
                    file_mtime=file_mtime
                ))

        except Exception as e:
            logger.warning(
                f"Parse failed for {index_path}: {e} — falling back to glob"
            )
            self._dead_letter(
                session_id=f"index:{index_path.parent.name}",
                project=str(project_dir),
                reason='index_parse_error',
                error=str(e),
            )
            return self._scan_jsonl_files(project_dir)

        return sessions

    def _scan_jsonl_files(self, project_dir: Path) -> List[SessionMetadata]:
        """Disk scan: the authoritative source for discoverable sessions.

        Recursive (rglob) and populates message_count by line-counting the
        JSONL. An uncounted session (message_count=0 dataclass default) used
        to be silently dropped by the min_messages filter downstream.
        """
        sessions = []

        for jsonl_file in project_dir.rglob('*.jsonl'):
            # Skip scratchpads and subagent transcripts (subagents live at
            # <project>/<sid>/subagents/agent-*.jsonl and are not primary
            # sessions — indexing them would pollute the session corpus).
            if 'scratchpad' in jsonl_file.parts or 'subagents' in jsonl_file.parts:
                continue
            if any(jsonl_file.match(pat) for pat in self.config['sessions'].get('exclude', [])):
                continue

            session_id = jsonl_file.stem

            try:
                file_mtime = jsonl_file.stat().st_mtime
            except OSError as e:
                self._dead_letter(session_id, str(project_dir), 'jsonl_read_error', error=str(e))
                continue

            try:
                with open(jsonl_file, 'rb') as f:
                    message_count = sum(1 for _ in f)
            except Exception as e:
                logger.warning(f"Could not count lines in {jsonl_file}: {e}")
                message_count = 0

            sessions.append(SessionMetadata(
                session_id=session_id,
                transcript_path=str(jsonl_file),
                project_path=str(project_dir),
                message_count=message_count,
                file_mtime=file_mtime,
            ))

        return sessions

    # =========================================================================
    # Session Processing
    # =========================================================================

    async def get_sessions_needing_processing(self) -> List[SessionMetadata]:
        """
        Get sessions that need processing (new or modified).

        Compares file mtime against last_ingested_at in database.
        """
        all_sessions = self.discover_sessions()

        if not all_sessions:
            return []

        # Get ingestion status from database
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT session_id, file_mtime, last_ingested_at
                FROM session_ingestion_log
            """)
            ingested = {row['session_id']: row for row in rows}

        # Filter to sessions needing processing
        min_messages = self.config['processing']['min_messages']
        needs_processing = []
        for session in all_sessions:
            # Let message_count == 0 through (disk scan authoritative; the
            # transcript parser handles truly empty files). Only skip when
            # we have a positive count below the threshold.
            if 0 < session.message_count < min_messages:
                continue

            ingestion_record = ingested.get(session.session_id)

            if ingestion_record is None:
                # Never processed
                needs_processing.append(session)
            elif session.file_mtime and session.file_mtime > (ingestion_record['file_mtime'] or 0):
                # File modified since last ingestion
                needs_processing.append(session)

        logger.info(f"Found {len(needs_processing)} sessions needing processing")
        return needs_processing

    async def process_session(self, session: SessionMetadata) -> ProcessingResult:
        """
        Process a single session: parse, chunk, embed, store.
        """
        logger.info(f"Processing session: {session.session_id}")

        try:
            # Parse session transcript
            messages = self._parse_transcript(session.transcript_path)

            if not messages:
                return ProcessingResult(
                    session_id=session.session_id,
                    success=True,
                    chunks_created=0
                )

            # Extract metadata (tools, files, model, etc.)
            metadata = self._extract_metadata(session.transcript_path)

            # Create chunks
            chunks = self._create_chunks(session.session_id, messages)

            # Generate embeddings
            if self.poly_embed_url and chunks:
                chunks = await self._generate_embeddings(chunks)

            # Store chunks
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    # Delete existing chunks for this session (replace strategy)
                    await conn.execute("""
                        DELETE FROM session_chunks WHERE session_id = $1
                    """, session.session_id)

                    # Insert new chunks
                    for chunk in chunks:
                        session_rid = f"claude-session:{session.session_id}"

                        if chunk.embedding:
                            await conn.execute("""
                                INSERT INTO session_chunks
                                (session_rid, session_id, chunk_index, chunk_text, role, timestamp, embedding)
                                VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
                            """,
                                session_rid,
                                chunk.session_id,
                                chunk.chunk_index,
                                chunk.chunk_text,
                                chunk.role,
                                chunk.timestamp,
                                str(chunk.embedding)
                            )
                        else:
                            await conn.execute("""
                                INSERT INTO session_chunks
                                (session_rid, session_id, chunk_index, chunk_text, role, timestamp)
                                VALUES ($1, $2, $3, $4, $5, $6)
                            """,
                                session_rid,
                                chunk.session_id,
                                chunk.chunk_index,
                                chunk.chunk_text,
                                chunk.role,
                                chunk.timestamp
                            )

                    # Update ingestion log with metadata
                    await conn.execute("""
                        INSERT INTO session_ingestion_log
                        (session_id, transcript_path, project_path, summary, first_prompt,
                         message_count, chunk_count, file_mtime, last_ingested_at,
                         tools_used, tool_counts, mcp_servers, files_accessed, model, cwd, git_branch,
                         source_host)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10, $11, $12, $13, $14, $15, $16)
                        ON CONFLICT (session_id) DO UPDATE SET
                            transcript_path = EXCLUDED.transcript_path,
                            summary = EXCLUDED.summary,
                            first_prompt = EXCLUDED.first_prompt,
                            message_count = EXCLUDED.message_count,
                            chunk_count = EXCLUDED.chunk_count,
                            file_mtime = EXCLUDED.file_mtime,
                            tools_used = EXCLUDED.tools_used,
                            tool_counts = EXCLUDED.tool_counts,
                            mcp_servers = EXCLUDED.mcp_servers,
                            files_accessed = EXCLUDED.files_accessed,
                            model = EXCLUDED.model,
                            cwd = EXCLUDED.cwd,
                            git_branch = EXCLUDED.git_branch,
                            source_host = EXCLUDED.source_host,
                            last_ingested_at = NOW()
                    """,
                        session.session_id,
                        session.transcript_path,
                        session.project_path,
                        session.summary,
                        session.first_prompt,
                        len(messages),
                        len(chunks),
                        session.file_mtime,
                        metadata['tools_used'],
                        json.dumps(metadata['tool_counts']),
                        metadata['mcp_servers'],
                        metadata['files_accessed'],
                        metadata['model'],
                        metadata['cwd'],
                        metadata['git_branch'],
                        session.source_host,
                    )

                    # Store tool usage details
                    if metadata['tool_counts']:
                        # Delete existing tool usage for this session
                        await conn.execute("""
                            DELETE FROM session_tool_usage WHERE session_id = $1
                        """, session.session_id)

                        # Insert tool usage records
                        for tool_name, count in metadata['tool_counts'].items():
                            is_mcp = tool_name.startswith('mcp__')
                            mcp_server = None
                            if is_mcp:
                                parts = tool_name.split('__')
                                if len(parts) >= 2:
                                    mcp_server = parts[1]

                            await conn.execute("""
                                INSERT INTO session_tool_usage
                                (session_id, tool_name, call_count, is_mcp, mcp_server)
                                VALUES ($1, $2, $3, $4, $5)
                            """, session.session_id, tool_name, count, is_mcp, mcp_server)

            self.stats['sessions_processed'] += 1
            self.stats['chunks_created'] += len(chunks)

            # Entity extraction and knowledge graph linking (legacy OpenAI path).
            # Skipped when Phase 2 extractor_prompt is configured — extraction
            # runs as a separate batch phase in run_scan() instead of inline.
            entities_linked = 0
            extraction_config = self.config.get('entity_extraction', {})
            use_legacy = (extraction_config.get('enabled', False)
                          and extraction_config.get('link_existing', True)
                          and not extraction_config.get('extractor_prompt'))
            if use_legacy:
                entities, extraction_success = self._extract_entities(chunks)

                if extraction_success:
                    # Valid extraction (even if empty) — call /ingest with replace_existing
                    # Always call /ingest on valid extraction — even empty lists
                    # clear stale links via replace_existing=True
                    link_existing_only = not extraction_config.get('extract_new', False)
                    ingest_result = await asyncio.to_thread(
                        self._call_ingest,
                        session.session_id,
                        entities,
                        session,
                        link_existing_only,
                    )
                    if ingest_result:
                            stats = ingest_result.get('stats', {})
                            entities_linked = stats.get('resolved_entities', 0) + stats.get('new_entities', 0)
                            self.stats['entities_linked'] += entities_linked
                else:
                    # Extraction failed — preserve existing links (don't call /ingest)
                    logger.warning(f"Entity extraction failed for session {session.session_id} — preserving existing links")

            logger.info(f"Processed session {session.session_id}: {len(chunks)} chunks, {entities_linked} entities linked")

            return ProcessingResult(
                session_id=session.session_id,
                success=True,
                chunks_created=len(chunks),
                entities_linked=entities_linked
            )

        except EmbeddingTimeout as e:
            logger.warning(
                f"Embedding timeout for session {session.session_id}: {e} "
                f"— skipping ingestion log write (next scan will retry)"
            )
            self._dead_letter(
                session_id=session.session_id,
                project=session.project_path,
                reason='embed_timeout',
                error=str(e),
            )
            self.stats['errors'] += 1
            return ProcessingResult(
                session_id=session.session_id,
                success=False,
                error=f"embed_timeout: {e}",
            )
        except Exception as e:
            logger.error(f"Error processing session {session.session_id}: {e}")
            self._dead_letter(
                session_id=session.session_id,
                project=session.project_path,
                reason='processing_error',
                error=str(e),
            )
            self.stats['errors'] += 1
            return ProcessingResult(
                session_id=session.session_id,
                success=False,
                error=str(e)
            )

    def _parse_transcript(self, transcript_path: str) -> List[Dict]:
        """
        Parse JSONL transcript file into list of messages.
        """
        messages = []

        try:
            with open(transcript_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        # Filter to actual conversation messages
                        if msg.get('type') in ['user', 'assistant']:
                            messages.append(msg)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading transcript {transcript_path}: {e}")

        return messages

    def _extract_metadata(self, transcript_path: str) -> Dict:
        """
        Extract structured metadata from transcript.

        Returns dict with:
        - tools_used: list of unique tool names
        - tool_counts: dict of tool_name -> count
        - mcp_servers: list of MCP server names
        - files_accessed: list of file paths (read/edit/write)
        - model: model name used
        - cwd: working directory
        - git_branch: git branch name
        """
        tool_counts: Dict[str, int] = {}
        mcp_servers: set = set()
        files_accessed: set = set()
        model = None
        cwd = None
        git_branch = None

        try:
            with open(transcript_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)

                        # Extract metadata from assistant messages
                        if msg.get('type') == 'assistant':
                            # Get model, cwd, git_branch from first assistant message
                            if model is None:
                                inner_msg = msg.get('message', {})
                                model = inner_msg.get('model')
                            if cwd is None:
                                cwd = msg.get('cwd')
                            if git_branch is None:
                                git_branch = msg.get('gitBranch')

                            # Extract tool usage from content blocks
                            inner_msg = msg.get('message', {})
                            content = inner_msg.get('content', [])
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                                        tool_name = block.get('name', '')
                                        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

                                        # Extract MCP server name
                                        if tool_name.startswith('mcp__'):
                                            parts = tool_name.split('__')
                                            if len(parts) >= 2:
                                                mcp_servers.add(parts[1])

                                        # Extract file paths from Read/Edit/Write tools
                                        tool_input = block.get('input', {})
                                        if tool_name in ('Read', 'Edit', 'Write', 'NotebookEdit'):
                                            file_path = tool_input.get('file_path') or tool_input.get('notebook_path')
                                            if file_path:
                                                files_accessed.add(file_path)

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"Error extracting metadata from {transcript_path}: {e}")

        return {
            'tools_used': list(tool_counts.keys()),
            'tool_counts': tool_counts,
            'mcp_servers': list(mcp_servers),
            'files_accessed': list(files_accessed)[:100],  # Limit to prevent huge arrays
            'model': model,
            'cwd': cwd,
            'git_branch': git_branch
        }

    # =========================================================================
    # Entity Extraction (Session → Knowledge Graph)
    # =========================================================================

    # Regex patterns for redacting secrets before LLM extraction
    _REDACT_PATTERNS = [
        # Environment variable assignments: KEY=value, KEY='val ue', KEY="val ue"
        (re.compile(r"""\b[A-Z_]{2,}=(?:"[^"]*"|'[^']*'|\S+)"""), '[REDACTED_ENV]'),
        # API keys: sk-..., ghp_..., ghu_..., Bearer tokens
        (re.compile(r'\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|ghu_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,})'), '[REDACTED_KEY]'),
        (re.compile(r'Bearer\s+[a-zA-Z0-9._\-]{20,}'), 'Bearer [REDACTED]'),
        # Private keys
        (re.compile(r'-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----'), '[REDACTED_PRIVATE_KEY]'),
        # Connection strings with credentials
        (re.compile(r'(postgresql|postgres|mongodb|mysql|redis)://[^\s]+'), '[REDACTED_CONN_STRING]'),
        # URLs with embedded credentials (user:pass@host)
        (re.compile(r'https?://[^:]+:[^@]+@[^\s]+'), '[REDACTED_URL_CREDS]'),
        # Base64 blobs longer than 50 chars (likely encoded secrets)
        (re.compile(r'[A-Za-z0-9+/]{50,}={0,2}'), '[REDACTED_BASE64]'),
        # File paths containing sensitive filenames
        (re.compile(r'[^\s]*(?:\.env|credentials|secrets|\.pem|\.key)[^\s]*'), '[REDACTED_PATH]'),
    ]

    @staticmethod
    def _redact_for_extraction(text: str) -> str:
        """
        Redact secrets from text before sending to external LLM for entity extraction.

        Strips API keys, tokens, connection strings, private keys, and base64 blobs.
        Returns redacted text with substitution markers.
        """
        redaction_count = 0
        for pattern, replacement in ClaudeSessionSensor._REDACT_PATTERNS:
            text, count = pattern.subn(replacement, text)
            redaction_count += count

        if redaction_count > 0:
            logger.info(f"Redacted {redaction_count} potential secrets before extraction")

        return text

    def _extract_entities(self, chunks: List['SessionChunk']) -> Tuple[List[Dict], bool]:
        """
        Extract named entities from session chunks using OpenAI gpt-4o-mini.

        Returns:
            (entities, success): List of entity dicts matching /ingest schema,
            and bool indicating whether extraction succeeded.
            On failure, returns ([], False) — caller should preserve existing links.
        """
        if not self.openai_client:
            logger.warning("OpenAI client not available — skipping entity extraction")
            return [], False

        extraction_config = self.config.get('entity_extraction', {})
        max_chunks = extraction_config.get('max_chunks', 5)
        model = extraction_config.get('model', 'gpt-4o-mini')

        # Take first N chunks (covers main conversation)
        selected_chunks = chunks[:max_chunks]
        if not selected_chunks:
            return [], True  # Valid empty — no chunks to process

        # Concatenate and redact chunk text
        raw_text = "\n\n---\n\n".join(c.chunk_text for c in selected_chunks)
        redacted_text = self._redact_for_extraction(raw_text)

        # Truncate to ~10k chars to stay within reasonable token limits
        if len(redacted_text) > 10000:
            redacted_text = redacted_text[:10000] + "\n\n[truncated]"

        prompt = """Extract named entities mentioned in this Claude Code session transcript.
Return a JSON array of objects with: name, type, confidence.

Types: Person, Organization, Project, Concept
Confidence: 1.0 = explicitly named, 0.7 = inferred from context

Rules:
- Only extract entities explicitly mentioned by proper name
- Skip generic references ("the project", "the team", "the user")
- Skip tool names, file paths, and code identifiers (tracked separately)
- Skip the AI assistant itself (Claude, GPT, etc.)
- For ambiguous names, include the most specific form used

Session text:
"""

        try:
            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You extract named entities from text. Always respond with valid JSON arrays."},
                    {"role": "user", "content": prompt + redacted_text}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            if not content:
                logger.warning("Empty response from entity extraction LLM")
                return [], True  # Valid empty response

            parsed = json.loads(content)

            # Handle {"entities": [...]} or bare [...] — reject unrecognized shapes
            if isinstance(parsed, dict) and ('entities' in parsed or 'results' in parsed):
                entities_raw = parsed.get('entities', parsed.get('results'))
                if not isinstance(entities_raw, list):
                    logger.warning(f"Extraction response 'entities' key is not a list: {type(entities_raw)}")
                    return [], False
            elif isinstance(parsed, list):
                entities_raw = parsed
            else:
                logger.warning(f"Unrecognized extraction response shape (keys={list(parsed.keys()) if isinstance(parsed, dict) else type(parsed)}), treating as failure")
                return [], False

            # Convert to /ingest schema format
            entities = []
            seen_names = set()
            for ent in entities_raw:
                name = ent.get('name', '').strip()
                ent_type = ent.get('type', 'Concept').strip()
                confidence = float(ent.get('confidence', 0.7))

                if not name or name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                # Validate entity type
                if ent_type not in ('Person', 'Organization', 'Project', 'Concept'):
                    ent_type = 'Concept'

                entities.append({
                    'name': name,
                    'type': ent_type,
                    'confidence': confidence,
                    'context': f"Mentioned in Claude Code session"
                })

            logger.info(f"Extracted {len(entities)} entities from {len(selected_chunks)} chunks")
            return entities, True

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse entity extraction response: {e}")
            return [], False
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return [], False

    def _call_ingest(
        self,
        session_id: str,
        entities: List[Dict],
        session: 'SessionMetadata',
        link_existing_only: bool = True
    ) -> Optional[Dict]:
        """
        Call the personal-koi /ingest endpoint to resolve entities and create document links.

        Uses replace_existing=True for idempotent reprocessing.
        Returns the API response dict, or None on failure.
        """
        api_url = self.config.get('koi_backend', {}).get('api_url', 'http://localhost:8351')
        ingest_url = f"{api_url}/ingest"

        # Build request matching IngestRequest schema
        payload = {
            "document_rid": f"claude-session:{session_id}",
            "entities": entities,
            "source": "claude-sessions-sensor",
            "replace_existing": True,
            "link_existing_only": link_existing_only,
            "context": {
                "project": session.project_path,
                "topics": [session.first_prompt[:100]] if session.first_prompt else []
            }
        }

        try:
            req = Request(
                ingest_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                stats = result.get('stats', {})
                logger.info(
                    f"Ingest result for session {session_id}: "
                    f"resolved={stats.get('resolved_entities', 0)}, "
                    f"new={stats.get('new_entities', 0)}, "
                    f"skipped={stats.get('skipped_entities', 0)}, "
                    f"failed={stats.get('failed_entities', 0)}"
                )
                return result
        except HTTPError as e:
            logger.error(f"Ingest API HTTP error for session {session_id}: {e.code} {e.reason}")
            return None
        except URLError as e:
            logger.error(f"Ingest API connection error for session {session_id}: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Ingest API call failed for session {session_id}: {e}")
            return None

    def _create_chunks(
        self,
        session_id: str,
        messages: List[Dict]
    ) -> List[SessionChunk]:
        """
        Create chunks from session messages.

        Strategy: Turn pairs (user message + assistant response)
        """
        chunks = []
        chunk_index = 0

        strategy = self.config['processing']['chunk_strategy']

        if strategy == 'turn_pair':
            # Group user + assistant messages as pairs
            i = 0
            while i < len(messages):
                msg = messages[i]

                if msg.get('type') == 'user':
                    # Start a turn pair
                    user_text = self._extract_text(msg)
                    assistant_text = ""

                    # Look for following assistant message
                    if i + 1 < len(messages) and messages[i + 1].get('type') == 'assistant':
                        assistant_text = self._extract_text(messages[i + 1])
                        i += 1

                    # Create chunk
                    chunk_text = f"User: {user_text}\n\nAssistant: {assistant_text}"

                    # Get timestamp (convert to naive datetime for PostgreSQL)
                    timestamp = None
                    if msg.get('timestamp'):
                        try:
                            ts = datetime.fromisoformat(
                                msg['timestamp'].replace('Z', '+00:00')
                            )
                            # Convert to naive datetime (remove timezone)
                            timestamp = ts.replace(tzinfo=None)
                        except:
                            pass

                    chunks.append(SessionChunk(
                        session_id=session_id,
                        chunk_index=chunk_index,
                        chunk_text=chunk_text[:8000],  # Limit chunk size
                        role='turn_pair',
                        timestamp=timestamp
                    ))
                    chunk_index += 1

                i += 1

        else:
            # Token count strategy (simpler: just concat and split)
            full_text = "\n\n".join(
                f"{msg.get('type', 'unknown').title()}: {self._extract_text(msg)}"
                for msg in messages
            )

            chunk_size = self.config['processing']['chunk_size']
            overlap = self.config['processing']['chunk_overlap']

            # Simple character-based chunking (could improve with tiktoken)
            pos = 0
            while pos < len(full_text):
                chunk_end = min(pos + chunk_size, len(full_text))
                chunk_text = full_text[pos:chunk_end]

                chunks.append(SessionChunk(
                    session_id=session_id,
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                    role='context'
                ))
                chunk_index += 1
                pos += chunk_size - overlap

        return chunks

    def _extract_text(self, msg: Dict) -> str:
        """Extract text content from a message."""
        # Handle different message formats
        if isinstance(msg.get('message'), str):
            return msg['message']
        elif isinstance(msg.get('message'), dict):
            # Could be structured content
            content = msg['message'].get('content', '')
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Extract text from content blocks
                texts = []
                for block in content:
                    if isinstance(block, str):
                        texts.append(block)
                    elif isinstance(block, dict) and block.get('type') == 'text':
                        texts.append(block.get('text', ''))
                return '\n'.join(texts)
        elif msg.get('content'):
            return str(msg['content'])

        return ""

    async def _generate_embeddings(
        self,
        chunks: List[SessionChunk]
    ) -> List[SessionChunk]:
        """Generate embeddings for chunks using poly embedding service.

        Raises EmbeddingTimeout if any batch fails all 3 retry attempts.
        The caller (process_session) dead-letters and skips the session
        without marking it ingested, so the next scan cycle retries.
        """
        if not self.poly_embed_url:
            return chunks

        batch_size = self.config['embeddings']['batch_size']
        delays = [1, 4, 16]

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c.chunk_text for c in batch]
            last_err: Optional[Exception] = None

            for attempt in range(3):
                try:
                    resp = requests.post(
                        f"{self.poly_embed_url}/embed",
                        json={"texts": texts, "is_query": False},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    embeddings = resp.json()["embeddings"]
                    for j, emb in enumerate(embeddings):
                        batch[j].embedding = emb
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(
                        f"Embed attempt {attempt + 1}/3 failed: {e}"
                    )
                    if attempt < 2:
                        await asyncio.sleep(delays[attempt])
            else:
                raise EmbeddingTimeout(
                    f"poly embed failed after 3 attempts: {last_err}"
                )

        return chunks

    # =========================================================================
    # Phase 2: claude -p Entity/Fact Extraction (runs as a batch phase in
    # run_scan, NOT inline in process_session — plan §2d).
    # =========================================================================

    def _build_extraction_text(self, transcript_path: str) -> str:
        """Read session JSONL and build turn-pair text for the extractor.

        Caps at ~60,000 chars (first 20k + middle 20k + last 20k for very
        long sessions). Redacts secrets before returning.
        """
        messages = self._parse_transcript(transcript_path)
        pairs: List[str] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.get('type') == 'user':
                user_text = self._extract_text(msg)
                asst_text = ''
                if i + 1 < len(messages) and messages[i + 1].get('type') == 'assistant':
                    asst_text = self._extract_text(messages[i + 1])
                    i += 1
                pairs.append(f"User: {user_text}\n\nAssistant: {asst_text}")
            i += 1

        full_text = '\n\n---\n\n'.join(pairs)

        # Cap and redact
        cap = 60000
        if len(full_text) > cap:
            third = cap // 3
            mid_start = len(full_text) // 2 - third // 2
            full_text = (
                full_text[:third]
                + '\n\n[...middle...]\n\n'
                + full_text[mid_start:mid_start + third]
                + '\n\n[...end...]\n\n'
                + full_text[-third:]
            )

        return self._redact_for_extraction(full_text)

    async def _extract_via_claude(self, prompt_text: str) -> Tuple[Optional[dict], Optional[str]]:
        """Call claude -p subprocess with the extraction prompt.

        Returns (parsed_json, None) on success or (None, error_string) on failure.
        """
        ext_cfg = self.config.get('entity_extraction', {})
        claude_bin = ext_cfg.get('claude_binary', '/Users/darrenzal/.local/bin/claude')
        timeout_s = ext_cfg.get('timeout', 120)

        try:
            proc = await asyncio.create_subprocess_exec(
                claude_bin, '-p', '--output-format', 'json',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt_text.encode('utf-8')),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            return None, 'extract_timeout'
        except FileNotFoundError:
            return None, f'extract_auth_error: {claude_bin} not found'
        except Exception as e:
            return None, f'extract_timeout: {e}'

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode('utf-8', errors='replace')[:500]
            if '401' in stderr_text or 'auth' in stderr_text.lower():
                return None, f'extract_auth_error: {stderr_text}'
            return None, f'extract_parse_error: exit {proc.returncode}: {stderr_text}'

        try:
            raw = stdout_bytes.decode('utf-8').strip()
            # claude -p --output-format json wraps in {"result": ...} — extract
            outer = json.loads(raw)
            if isinstance(outer, dict) and 'result' in outer:
                inner = outer['result']
                if isinstance(inner, str):
                    parsed = json.loads(inner)
                else:
                    parsed = inner
            else:
                parsed = outer

            # Validate required keys
            if not isinstance(parsed, dict) or 'entities' not in parsed:
                return None, f'extract_parse_error: missing "entities" key'
            return parsed, None
        except json.JSONDecodeError as e:
            return None, f'extract_parse_error: {e}'

    async def _post_extraction(
        self,
        session_id: str,
        source_host: str,
        project_path: str,
        transcript_path: str,
        extracted: dict,
    ) -> Tuple[bool, Optional[str]]:
        """POST extraction results to /knowledge/episodes + /ingest.

        Returns (True, None) on success or (False, error_reason) on failure.
        """
        api_url = self.config.get('koi_backend', {}).get('api_url', 'http://localhost:8351')
        entities = extracted.get('entities', [])
        facts = extracted.get('facts', [])

        # 1. POST /knowledge/episodes (episode + facts + entity resolution)
        episode_payload = {
            'name': extracted.get('episode_name', f'Session {session_id[:8]}'),
            'content': extracted.get('episode_summary', ''),
            'source_description': 'claude_session',
            'source_document': session_id,
            'metadata': {
                'session_id': session_id,
                'source_host': source_host or 'macbook',
                'transcript_path': transcript_path,
            },
            'facts': facts,
            'create_entities': True,
        }
        try:
            req = Request(
                f'{api_url}/knowledge/episodes',
                data=json.dumps(episode_payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urlopen(req, timeout=60) as resp:
                episode_result = json.loads(resp.read().decode('utf-8'))
                logger.info(
                    f"Episode created for {session_id[:8]}: "
                    f"episode_id={episode_result.get('episode_id')}, "
                    f"facts_created={episode_result.get('facts_created', 0)}"
                )
        except HTTPError as e:
            reason = 'episode_write_error' if e.code >= 500 else 'extract_parse_error'
            return False, f'{reason}: {e.code} {e.reason}'
        except Exception as e:
            return False, f'episode_write_error: {e}'

        # 2. POST /ingest (document_entity_links for search_sessions_by_entity)
        if entities:
            ingest_payload = {
                'document_rid': f'claude-session:{session_id}',
                'entities': [{'name': e['name'], 'type': e.get('type', 'Concept')}
                             for e in entities],
                'source': 'extract-session-entities',
                'replace_existing': True,
                'context': {'project': project_path},
            }
            try:
                req = Request(
                    f'{api_url}/ingest',
                    data=json.dumps(ingest_payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urlopen(req, timeout=30) as resp:
                    ingest_result = json.loads(resp.read().decode('utf-8'))
                    stats = ingest_result.get('stats', {})
                    logger.info(
                        f"Entity links for {session_id[:8]}: "
                        f"resolved={stats.get('resolved_entities', 0)}, "
                        f"new={stats.get('new_entities', 0)}"
                    )
            except HTTPError as e:
                if e.code >= 500:
                    return False, f'entity_resolve_error: {e.code} {e.reason}'
                logger.warning(f"Ingest 4xx for {session_id[:8]}: {e.code} — continuing")
            except Exception as e:
                return False, f'entity_resolve_error: {e}'

        return True, None

    async def _extract_single_session(
        self,
        session_id: str,
        transcript_path: str,
        source_host: str,
        project_path: str,
    ) -> bool:
        """Run full extraction pipeline on one session. Returns True on success."""
        ext_cfg = self.config.get('entity_extraction', {})
        prompt_path = ext_cfg.get('extractor_prompt', '')

        if not prompt_path or not Path(prompt_path).exists():
            logger.error(f"Extractor prompt not found: {prompt_path}")
            return False

        # Build prompt: template + session text
        with open(prompt_path, 'r') as f:
            prompt_template = f.read()

        session_text = self._build_extraction_text(transcript_path)
        if not session_text.strip():
            # Empty session — mark extracted with empty results
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE session_ingestion_log
                    SET entities_extracted_at = NOW(),
                        extraction_attempts = extraction_attempts + 1,
                        extraction_last_error = NULL
                    WHERE session_id = $1
                """, session_id)
            return True

        full_prompt = prompt_template + '\n' + session_text

        # Call claude -p
        extracted, error = await self._extract_via_claude(full_prompt)

        if error:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE session_ingestion_log
                    SET extraction_attempts = extraction_attempts + 1,
                        extraction_last_error = $2
                    WHERE session_id = $1
                """, session_id, error)
            self._dead_letter(session_id, project_path, error.split(':')[0], error=error)
            logger.warning(f"Extraction failed for {session_id[:8]}: {error}")
            return False

        # POST results (uses synchronous urlopen — acceptable for serial sensor)
        success, post_error = await self._post_extraction(
            session_id, source_host, project_path, transcript_path, extracted
        )

        async with self.db_pool.acquire() as conn:
            if success:
                await conn.execute("""
                    UPDATE session_ingestion_log
                    SET entities_extracted_at = NOW(),
                        extraction_attempts = extraction_attempts + 1,
                        extraction_last_error = NULL
                    WHERE session_id = $1
                """, session_id)
                n_ent = len(extracted.get('entities', []))
                n_fact = len(extracted.get('facts', []))
                logger.info(
                    f"Extracted {session_id[:8]}: "
                    f"{n_ent} entities, {n_fact} facts"
                )
                return True
            else:
                await conn.execute("""
                    UPDATE session_ingestion_log
                    SET extraction_attempts = extraction_attempts + 1,
                        extraction_last_error = $2
                    WHERE session_id = $1
                """, session_id, post_error)
                self._dead_letter(session_id, project_path, (post_error or '').split(':')[0], error=post_error)
                logger.warning(f"Post-extraction failed for {session_id[:8]}: {post_error}")
                return False

    async def _run_extraction_batch(self, limit: Optional[int] = None, time_budget: Optional[float] = None) -> int:
        """Run extraction on eligible sessions.

        Called from run_scan (with limit + time_budget from config) and from
        backfill_session_entities.py (with limit=None for exhaustive mode).

        Uses FOR UPDATE SKIP LOCKED (plan §2d) so concurrent runs don't race.
        """
        ext_cfg = self.config.get('entity_extraction', {})
        if not ext_cfg.get('enabled', False) or not ext_cfg.get('extractor_prompt'):
            return 0

        max_attempts = ext_cfg.get('max_attempts', 5)
        effective_limit = limit or ext_cfg.get('max_per_cycle', 5)
        budget_end = (datetime.now(timezone.utc).timestamp() + time_budget) if time_budget else None

        extracted_count = 0
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT session_id, transcript_path, source_host, project_path
                FROM session_ingestion_log
                WHERE (entities_extracted_at IS NULL AND extraction_attempts < $1)
                   OR (entities_extracted_at IS NOT NULL AND entities_extracted_at < last_ingested_at)
                ORDER BY last_ingested_at DESC
                LIMIT $2
            """, max_attempts, effective_limit)

        if not rows:
            return 0

        logger.info(f"Extraction batch: {len(rows)} sessions eligible")

        for row in rows:
            if budget_end and datetime.now(timezone.utc).timestamp() > budget_end:
                logger.info(f"Extraction batch: time budget exceeded after {extracted_count} sessions")
                break

            success = await self._extract_single_session(
                row['session_id'],
                row['transcript_path'],
                row['source_host'] or 'macbook',
                row['project_path'] or '',
            )
            if success:
                extracted_count += 1

        logger.info(f"Extraction batch complete: {extracted_count}/{len(rows)} succeeded")
        return extracted_count

    # =========================================================================
    # Real-time Hook Processing
    # =========================================================================

    async def process_session_by_id(self, session_id: str, transcript_path: str) -> ProcessingResult:
        """
        Process a specific session (called from hook).
        """
        # Get file mtime
        file_mtime = None
        if Path(transcript_path).exists():
            file_mtime = Path(transcript_path).stat().st_mtime

        session = SessionMetadata(
            session_id=session_id,
            transcript_path=transcript_path,
            project_path=str(Path(transcript_path).parent),
            file_mtime=file_mtime
        )

        # Try to get metadata from sessions-index.json
        index_path = Path(transcript_path).parent / 'sessions-index.json'
        if index_path.exists():
            try:
                with open(index_path, 'r') as f:
                    index_data = json.load(f)
                for entry in index_data.get('entries', []):
                    if entry.get('sessionId') == session_id:
                        session.summary = entry.get('summary')
                        session.first_prompt = entry.get('firstPrompt')
                        session.message_count = entry.get('messageCount', 0)
                        break
            except:
                pass

        return await self.process_session(session)

    # =========================================================================
    # Daemon Mode
    # =========================================================================

    async def run_daemon(self):
        """Run sensor in daemon mode with periodic scans."""
        interval = self.config['runtime']['scan_interval'] * 60  # Convert to seconds

        logger.info(f"Starting daemon mode (scan interval: {interval}s)")

        while True:
            try:
                await self.run_scan()
            except Exception as e:
                logger.error(f"Error during scan: {e}")

            logger.info(f"Sleeping for {interval}s until next scan...")
            await asyncio.sleep(interval)

    async def run_scan(self):
        """Run a single scan: two sequential phases (plan §2d).

        Phase 1: chunk ingestion (discover → process → embed → store).
        Phase 2: entity/fact extraction batch (claude -p, capped at
                 max_per_cycle sessions, 2-min time budget).
        """
        logger.info("Starting session scan...")

        # Phase 1: chunk ingestion
        sessions = await self.get_sessions_needing_processing()
        for session in sessions:
            result = await self.process_session(session)
            if not result.success:
                logger.warning(f"Failed to process {session.session_id}: {result.error}")

        logger.info(f"Chunk phase complete. Stats: {self.stats}")

        # Phase 2: extraction batch (plan §2d — separate from chunk writes)
        ext_cfg = self.config.get('entity_extraction', {})
        if ext_cfg.get('enabled', False) and ext_cfg.get('extractor_prompt'):
            extracted = await self._run_extraction_batch(
                limit=ext_cfg.get('max_per_cycle', 5),
                time_budget=120,  # 2 min budget for extraction phase
            )
            self.stats['entities_extracted'] = self.stats.get('entities_extracted', 0) + extracted

        logger.info(f"Scan complete. Stats: {self.stats}")

    async def backfill_embeddings(self, batch_size: int = 100):
        """
        Generate embeddings for chunks that don't have them.
        Used to backfill embeddings after initial scan without OpenAI key.
        """
        if not self.poly_embed_url:
            logger.error("Poly embed URL not configured. Set embeddings.api_base in config.")
            return

        async with self.db_pool.acquire() as conn:
            # Count chunks needing embeddings
            total_missing = await conn.fetchval("""
                SELECT COUNT(*) FROM session_chunks WHERE embedding IS NULL
            """)
            logger.info(f"Found {total_missing} chunks needing embeddings")

            if total_missing == 0:
                logger.info("All chunks have embeddings!")
                return

            processed = 0
            while processed < total_missing:
                # Fetch batch of chunks without embeddings
                rows = await conn.fetch("""
                    SELECT id, chunk_text FROM session_chunks
                    WHERE embedding IS NULL
                    ORDER BY id
                    LIMIT $1
                """, batch_size)

                if not rows:
                    break

                # Generate embeddings for batch
                texts = [row['chunk_text'] for row in rows]
                ids = [row['id'] for row in rows]

                try:
                    resp = requests.post(
                        f"{self.poly_embed_url}/embed",
                        json={"texts": texts, "is_query": False},
                        timeout=30
                    )
                    resp.raise_for_status()
                    embeddings_list = resp.json()["embeddings"]

                    # Update each chunk with its embedding
                    for i, embedding in enumerate(embeddings_list):
                        await conn.execute("""
                            UPDATE session_chunks
                            SET embedding = $1::vector
                            WHERE id = $2
                        """, str(embedding), ids[i])

                    processed += len(rows)
                    logger.info(f"Backfilled {processed}/{total_missing} embeddings...")

                except Exception as e:
                    logger.error(f"Error generating embeddings: {e}")
                    break

            logger.info(f"Backfill complete. Generated {processed} embeddings.")

    async def refresh_metadata(self, batch_size: int = 50):
        """
        Refresh metadata for existing sessions without re-chunking.
        Extracts tools, files, model info from transcripts and updates database.
        """
        async with self.db_pool.acquire() as conn:
            # Get all ingested sessions
            rows = await conn.fetch("""
                SELECT session_id, transcript_path FROM session_ingestion_log
                ORDER BY last_ingested_at DESC
            """)

            logger.info(f"Refreshing metadata for {len(rows)} sessions...")

            processed = 0
            for row in rows:
                session_id = row['session_id']
                transcript_path = row['transcript_path']

                if not transcript_path or not os.path.exists(transcript_path):
                    continue

                # Extract metadata
                metadata = self._extract_metadata(transcript_path)

                # Update session record
                await conn.execute("""
                    UPDATE session_ingestion_log SET
                        tools_used = $2,
                        tool_counts = $3,
                        mcp_servers = $4,
                        files_accessed = $5,
                        model = $6,
                        cwd = $7,
                        git_branch = $8
                    WHERE session_id = $1
                """,
                    session_id,
                    metadata['tools_used'],
                    json.dumps(metadata['tool_counts']),
                    metadata['mcp_servers'],
                    metadata['files_accessed'],
                    metadata['model'],
                    metadata['cwd'],
                    metadata['git_branch']
                )

                # Update tool usage table
                if metadata['tool_counts']:
                    await conn.execute("""
                        DELETE FROM session_tool_usage WHERE session_id = $1
                    """, session_id)

                    for tool_name, count in metadata['tool_counts'].items():
                        is_mcp = tool_name.startswith('mcp__')
                        mcp_server = None
                        if is_mcp:
                            parts = tool_name.split('__')
                            if len(parts) >= 2:
                                mcp_server = parts[1]

                        await conn.execute("""
                            INSERT INTO session_tool_usage
                            (session_id, tool_name, call_count, is_mcp, mcp_server)
                            VALUES ($1, $2, $3, $4, $5)
                        """, session_id, tool_name, count, is_mcp, mcp_server)

                processed += 1
                if processed % batch_size == 0:
                    logger.info(f"Refreshed {processed}/{len(rows)} sessions...")

            logger.info(f"Metadata refresh complete. Updated {processed} sessions.")


# =============================================================================
# CLI Entry Point
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description='Claude Sessions Sensor')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--mode', choices=['daemon', 'scan', 'session', 'backfill', 'refresh'],
                        default='scan', help='Run mode (refresh = update metadata only)')
    parser.add_argument('--session-id', type=str, help='Session ID (for session mode)')
    parser.add_argument('--transcript-path', type=str, help='Transcript path (for session mode)')

    args = parser.parse_args()

    sensor = ClaudeSessionSensor(config_path=args.config)
    await sensor.initialize()

    try:
        if args.mode == 'daemon':
            await sensor.run_daemon()
        elif args.mode == 'scan':
            await sensor.run_scan()
        elif args.mode == 'session':
            if not args.session_id or not args.transcript_path:
                logger.error("--session-id and --transcript-path required for session mode")
                return
            result = await sensor.process_session_by_id(args.session_id, args.transcript_path)
            logger.info(f"Result: {result}")
        elif args.mode == 'backfill':
            await sensor.backfill_embeddings()
        elif args.mode == 'refresh':
            await sensor.refresh_metadata()
    finally:
        await sensor.close()


if __name__ == '__main__':
    asyncio.run(main())
