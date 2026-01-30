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
import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
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

        # Expand paths
        self.sessions_base = Path(
            os.path.expanduser(self.config['sessions']['base_path'])
        )

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
        db_url = self.config['koi_backend']['database_url']
        self.db_pool = await asyncpg.create_pool(
            db_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info(f"Connected to database")

        # Ensure schema exists
        await self._ensure_schema()

        # OpenAI client
        if OPENAI_AVAILABLE and self.config['embeddings']['enabled']:
            api_key = os.getenv('OPENAI_API_KEY')
            if api_key:
                self.openai_client = OpenAI(api_key=api_key)
                logger.info(f"OpenAI client initialized (model: {self.config['embeddings']['model']})")
            else:
                logger.warning("OPENAI_API_KEY not set. Embeddings disabled.")

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

    def discover_sessions(self) -> List[SessionMetadata]:
        """
        Discover all Claude Code session files.

        Returns list of SessionMetadata for each session found.
        """
        sessions = []

        # Find all project directories
        for project_dir in self.sessions_base.iterdir():
            if not project_dir.is_dir():
                continue

            # Check for sessions-index.json
            index_path = project_dir / 'sessions-index.json'
            if index_path.exists():
                sessions.extend(self._parse_sessions_index(index_path, project_dir))
            else:
                # Fallback: scan for JSONL files directly
                sessions.extend(self._scan_jsonl_files(project_dir))

        logger.info(f"Discovered {len(sessions)} sessions")
        return sessions

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

                # Get file mtime
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
            logger.error(f"Error parsing sessions index {index_path}: {e}")

        return sessions

    def _scan_jsonl_files(self, project_dir: Path) -> List[SessionMetadata]:
        """Fallback: scan for JSONL files directly."""
        sessions = []

        for jsonl_file in project_dir.glob('*.jsonl'):
            # Extract session ID from filename
            session_id = jsonl_file.stem

            # Skip if in exclude patterns
            if any(jsonl_file.match(pat) for pat in self.config['sessions'].get('exclude', [])):
                continue

            file_mtime = jsonl_file.stat().st_mtime

            sessions.append(SessionMetadata(
                session_id=session_id,
                transcript_path=str(jsonl_file),
                project_path=str(project_dir),
                file_mtime=file_mtime
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
        needs_processing = []
        for session in all_sessions:
            # Check minimum message count
            if session.message_count < self.config['processing']['min_messages']:
                continue

            ingestion_record = ingested.get(session.session_id)

            if ingestion_record is None:
                # Never processed
                needs_processing.append(session)
            elif session.file_mtime and session.file_mtime > ingestion_record['file_mtime']:
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
            if self.openai_client and chunks:
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
                         tools_used, tool_counts, mcp_servers, files_accessed, model, cwd, git_branch)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10, $11, $12, $13, $14, $15)
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
                        metadata['git_branch']
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

            logger.info(f"Processed session {session.session_id}: {len(chunks)} chunks")

            return ProcessingResult(
                session_id=session.session_id,
                success=True,
                chunks_created=len(chunks)
            )

        except Exception as e:
            logger.error(f"Error processing session {session.session_id}: {e}")
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
        """Generate embeddings for chunks using OpenAI."""
        if not self.openai_client:
            return chunks

        model = self.config['embeddings']['model']
        batch_size = self.config['embeddings']['batch_size']

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c.chunk_text for c in batch]

            try:
                response = self.openai_client.embeddings.create(
                    model=model,
                    input=texts
                )

                for j, embedding_data in enumerate(response.data):
                    batch[j].embedding = embedding_data.embedding

            except Exception as e:
                logger.error(f"Error generating embeddings: {e}")

        return chunks

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
        """Run a single scan of all sessions."""
        logger.info("Starting session scan...")

        sessions = await self.get_sessions_needing_processing()

        for session in sessions:
            result = await self.process_session(session)
            if not result.success:
                logger.warning(f"Failed to process {session.session_id}: {result.error}")

        logger.info(f"Scan complete. Stats: {self.stats}")

    async def backfill_embeddings(self, batch_size: int = 100):
        """
        Generate embeddings for chunks that don't have them.
        Used to backfill embeddings after initial scan without OpenAI key.
        """
        if not self.openai_client:
            logger.error("OpenAI client not available. Set OPENAI_API_KEY environment variable.")
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
                    response = self.openai_client.embeddings.create(
                        model=self.config['embeddings']['model'],
                        input=texts
                    )

                    # Update each chunk with its embedding
                    for i, embedding_data in enumerate(response.data):
                        embedding = embedding_data.embedding
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
