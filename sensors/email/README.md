# Email Sensor for Personal-KOI

Indexes Gmail Maildir emails into the personal knowledge graph.

## Architecture

```
Gmail Server                    Local Machine                      Personal-KOI
    │                               │                                   │
    │◄──── mbsync (IMAP) ──────────►│                                   │
    │      (every 15 min)           │                                   │
    │                               ▼                                   │
    │                    ~/Mail/Gmail/ (Maildir)                        │
    │                         │                                         │
    │                         ▼                                         │
    │                    Email Sensor                                   │
    │                    ┌─────────────────┐                           │
    │                    │ 1. Scan Maildir │                           │
    │                    │ 2. Filter emails│                           │
    │                    │ 3. Create RIDs  │                           │
    │                    │ 4. Extract      │                           │
    │                    │    entities     │                           │
    │                    │ 5. Process      │                           │
    │                    │    attachments  │                           │
    │                    └────────┬────────┘                           │
    │                             │                                     │
    │                             ▼                                     │
    │                    PostgreSQL                                     │
    │                    ├── koi_memories                              │
    │                    ├── koi_embeddings                            │
    │                    ├── koi_memory_chunks                         │
    │                    └── email_metadata                            │
```

## Prerequisites

1. **mbsync** configured for Gmail (see `~/.mbsyncrc`)
2. **PostgreSQL** with personal_koi database
3. **Personal-KOI backend** running on port 8351

## Setup

```bash
# Install dependencies
./setup.sh

# Run database migration
psql personal_koi < /path/to/koi-processor/migrations/033_email_sensor_tables.sql
```

### Backend Configuration (recommended via env)

`config.yaml` includes sane localhost defaults, but environment overrides are preferred:

```bash
export PERSONAL_KOI_DB_URL="postgresql://postgres:postgres@localhost:5432/personal_koi"
export PERSONAL_KOI_API_URL="http://localhost:8351"
```

Supported DB env fallbacks (in priority order):
- `PERSONAL_KOI_DB_URL`
- `KOI_DATABASE_URL`
- `DATABASE_URL`

## Usage

### One-shot scan
```bash
./start.sh
```

### Limit emails processed
```bash
./start.sh --limit 100
```

### Daemon mode (continuous)
```bash
./start.sh --daemon
```

### Background mode
```bash
./start.sh --background
```

### Real-time file watcher
```bash
source venv/bin/activate
python file_watcher.py
```

## Configuration

Use `config.example.yaml` as the baseline.

Edit `config.yaml` to customize:

- **maildir**: Base path, excluded folders, categories
- **filtering**: Age limit, body length, email size
- **chunking**: Chunk size, overlap
- **embeddings**: BGE server URL, batch size
- **entity_extraction**: LLM settings
- **attachments**: Supported types, max size

## launchd Setup (macOS)

For automatic processing:

```bash
# Generate machine-specific plist files from templates
SENSOR_DIR="$(pwd)"
HOME_DIR="$HOME"
sed -e "s|__SENSOR_DIR__|$SENSOR_DIR|g" -e "s|__HOME__|$HOME_DIR|g" \
  com.personal-koi.email-sensor.plist.template > com.personal-koi.email-sensor.plist
sed -e "s|__SENSOR_DIR__|$SENSOR_DIR|g" -e "s|__HOME__|$HOME_DIR|g" \
  com.personal-koi.email-watcher.plist.template > com.personal-koi.email-watcher.plist

# Copy generated plist files to LaunchAgents
cp com.personal-koi.email-sensor.plist ~/Library/LaunchAgents/
cp com.personal-koi.email-watcher.plist ~/Library/LaunchAgents/

# Load the sensor (scheduled every 30 min)
launchctl load ~/Library/LaunchAgents/com.personal-koi.email-sensor.plist

# Load the watcher (real-time)
launchctl load ~/Library/LaunchAgents/com.personal-koi.email-watcher.plist

# Check status
launchctl list | grep email
```

## Database Schema

### email_metadata
Stores email-specific metadata:
- `from_address`, `from_name`, `to_addresses`, `cc_addresses`
- `subject`, `date_sent`, `thread_id`
- `labels`, `folder`, `content_hash`

### email_attachments
Tracks attachments:
- `filename`, `content_type`, `size_bytes`
- `extracted_text_rid` (link to extracted content)

## RID Format

- Email: `orn:gmail.message:{message_id_hash}`
- Attachment: `orn:gmail.attachment:{msg_hash}/{index}_{content_hash}`
- Chunk: `orn:gmail.message:{hash}#chunk{index}`

## Privacy

All emails are stored with `is_private=TRUE` and require authentication to access.

## Troubleshooting

### Check logs
```bash
tail -f email_sensor.log
tail -f email_watcher.log
```

### Reset processing state
```bash
rm email_sensor_state.json
```

### Test single email
```bash
source venv/bin/activate
python email_sensor.py --file ~/Mail/Gmail/INBOX/cur/FILENAME
```
