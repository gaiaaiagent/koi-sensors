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

                    # Update ingestion log
                    await conn.execute("""
                        INSERT INTO session_ingestion_log
                        (session_id, transcript_path, project_path, summary, first_prompt,
                         message_count, chunk_count, file_mtime, last_ingested_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                        ON CONFLICT (session_id) DO UPDATE SET
                            transcript_path = EXCLUDED.transcript_path,
                            summary = EXCLUDED.summary,
                            first_prompt = EXCLUDED.first_prompt,
                            message_count = EXCLUDED.message_count,
                            chunk_count = EXCLUDED.chunk_count,
                            file_mtime = EXCLUDED.file_mtime,
                            last_ingested_at = NOW()
                    """,
                        session.session_id,
                        session.transcript_path,
                        session.project_path,
                        session.summary,
                        session.first_prompt,
                        len(messages),
                        len(chunks),
                        session.file_mtime
                    )

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


# =============================================================================
# CLI Entry Point
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description='Claude Sessions Sensor')
    parser.add_argument('--config', type=str, help='Path to config file')
    parser.add_argument('--mode', choices=['daemon', 'scan', 'session'],
                        default='scan', help='Run mode')
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
    finally:
        await sensor.close()


if __name__ == '__main__':
    asyncio.run(main())
