# Claude Sessions Sensor

Indexes Claude Code session transcripts into personal KOI for semantic search.

## Overview

This sensor enables searching across your Claude Code conversation history. It:

1. **Scans** Claude Code session JSONL files from `~/.claude/projects/`
2. **Chunks** conversations by turn pairs (user + assistant)
3. **Embeds** chunks using OpenAI embeddings
4. **Stores** in PostgreSQL with pgvector for semantic search
5. **Links** mentions to existing entities in personal KOI

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
            "command": "/Users/darrenzal/projects/RegenAI/koi-sensors/sensors/claude_sessions/notify_session_end.sh"
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
-- Track ingestion state
CREATE TABLE session_ingestion_log (
    session_id TEXT PRIMARY KEY,
    transcript_path TEXT NOT NULL,
    project_path TEXT,
    summary TEXT,
    first_prompt TEXT,
    message_count INT,
    chunk_count INT,
    file_mtime DOUBLE PRECISION,
    last_ingested_at TIMESTAMP
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
```

## Searching Sessions

Once indexed, sessions can be searched via the personal KOI MCP (after adding `search_sessions` tool):

```
"What did I discuss with Claude about pgvector?"
"Find sessions where I worked on entity resolution"
```

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
