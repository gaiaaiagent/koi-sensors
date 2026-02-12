# Claude Sessions Sensor

Indexes Claude Code session transcripts into personal KOI for semantic search and metadata queries.

## Overview

This sensor enables searching across your Claude Code conversation history. It:

1. **Scans** Claude Code session JSONL files from `~/.claude/projects/`
2. **Chunks** conversations by turn pairs (user + assistant)
3. **Embeds** chunks using OpenAI embeddings for semantic search
4. **Extracts metadata**: tools used, MCP servers, files accessed, model, cwd
5. **Stores** in PostgreSQL with pgvector for semantic search
6. **Links** mentions to existing entities in personal KOI

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code Session                      │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     SessionEnd Hook                   Sensor (periodic)
     (real-time, best effort)         (catch-up, robust)
              │                               │
              │  notify_session_end.sh        │  ./start.sh scan
              └───────────────┬───────────────┘
                              ▼
                    Personal KOI Database
                    (session_chunks table)
```

**Hybrid approach:**
- **Hook**: Fast path for immediate indexing when sessions end normally
- **Sensor**: Safety net that catches missed sessions (crashes, hook failures)

## Setup

### 1. Install Dependencies

```bash
cd sensors/claude_sessions
./setup.sh
```

### 2. Configure

Edit `config.personal.yaml` if needed. Defaults work for standard Claude Code setup.

Recommended env overrides:
```bash
export PERSONAL_KOI_DB_URL="postgresql://postgres:postgres@localhost:5432/personal_koi"
export PERSONAL_KOI_API_URL="http://localhost:8351"
```

### 3. Ensure Database is Ready

The sensor will create tables automatically in `personal_koi` database:
- `session_ingestion_log` - Tracks what's been processed
- `session_chunks` - Stores chunks with embeddings

### 4. Install SessionEnd Hook (Optional but Recommended)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/koi-sensors/sensors/claude_sessions/notify_session_end.sh"
          }
        ]
      }
    ]
  }
}
```

## Usage

### One-shot Scan (Process All Pending)

```bash
./start.sh scan
```

### Daemon Mode (Continuous)

```bash
./start.sh daemon
# or
./start.sh --background
```

### Backfill Embeddings

If you initially ran without `OPENAI_API_KEY`, backfill embeddings later:

```bash
OPENAI_API_KEY="sk-..." python claude_session_sensor.py --mode backfill
```

### Refresh Metadata Only

Re-extract metadata (tools, files, etc.) without re-chunking:

```bash
python claude_session_sensor.py --mode refresh
```

### Process Specific Session

```bash
source venv/bin/activate
python claude_session_sensor.py \
    --mode session \
    --session-id "abc123" \
    --transcript-path "~/.claude/projects/.../abc123.jsonl"
```

## Configuration

See `config.personal.yaml`:

| Setting | Description | Default |
|---------|-------------|---------|
| `sessions.base_path` | Claude Code projects directory | `~/.claude/projects` |
| `processing.chunk_strategy` | How to chunk sessions | `turn_pair` |
| `processing.min_messages` | Min messages to process | `2` |
| `embeddings.enabled` | Generate embeddings | `true` |
| `embeddings.model` | OpenAI embedding model | `text-embedding-ada-002` |
| `runtime.scan_interval` | Minutes between scans (daemon) | `10` |

## Database Schema

```sql
-- Track ingestion state with metadata
CREATE TABLE session_ingestion_log (
    session_id TEXT PRIMARY KEY,
    transcript_path TEXT NOT NULL,
    project_path TEXT,
    summary TEXT,
    first_prompt TEXT,
    message_count INT,
    chunk_count INT,
    file_mtime DOUBLE PRECISION,
    last_ingested_at TIMESTAMP,
    -- Metadata columns
    tools_used TEXT[],              -- ["Bash", "Read", "Edit", ...]
    tool_counts JSONB,              -- {"Bash": 50, "Read": 10, ...}
    mcp_servers TEXT[],             -- ["personal-koi", "regen-ledger"]
    files_accessed TEXT[],          -- ["/path/to/file.ts", ...]
    model TEXT,                     -- "claude-opus-4-5-20251101"
    cwd TEXT,                       -- Working directory
    git_branch TEXT                 -- Git branch if available
);

-- Session chunks with embeddings
CREATE TABLE session_chunks (
    id SERIAL PRIMARY KEY,
    session_rid TEXT NOT NULL,      -- "claude-session:{uuid}"
    session_id TEXT NOT NULL,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    role TEXT,                       -- 'turn_pair', 'context'
    timestamp TIMESTAMP,
    embedding vector(1536),
    UNIQUE(session_id, chunk_index)
);

-- Tool usage for queryability
CREATE TABLE session_tool_usage (
    id SERIAL PRIMARY KEY,
    session_id TEXT REFERENCES session_ingestion_log(session_id),
    tool_name TEXT NOT NULL,
    call_count INT DEFAULT 1,
    is_mcp BOOLEAN DEFAULT FALSE,
    mcp_server TEXT,
    UNIQUE(session_id, tool_name)
);
```

## Searching Sessions

Once indexed, use the personal KOI MCP tools:

### Semantic Search (conversation content)
```
search_sessions(query="entity resolution pgvector")
```

### Tool Usage Queries
```
# Find sessions using a specific MCP
search_sessions_by_tool(mcp_server="regen-ledger")

# Find heavy Bash usage
search_sessions_by_tool(tool="Bash")

# Overall tool statistics (no filter)
search_sessions_by_tool()
```

### File Access Queries
```
# Sessions that edited koi-processor
search_sessions_by_files(path_contains="koi-processor")

# Sessions with most files accessed
search_sessions_by_files()
```

### API Endpoints

The personal KOI API exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/search-sessions` | POST | Semantic search over chunks |
| `/session-stats` | GET | Index statistics |
| `/session-tools` | GET | Query by tool/MCP usage |
| `/session-files` | GET | Query by files accessed |

## Troubleshooting

### Hook not firing
- Check `~/.claude/settings.json` syntax
- Check `hook.log` in sensor directory
- Ensure script is executable: `chmod +x notify_session_end.sh`

### Sessions not being indexed
- Check sensor logs: `./start.sh scan`
- Verify database connection in `config.personal.yaml`
- Check `session_ingestion_log` table for errors

### Missing embeddings
- Verify `OPENAI_API_KEY` is set in environment or `.env`
- Check OpenAI API quota
