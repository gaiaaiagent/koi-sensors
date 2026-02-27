# CLAUDE.md - KOI Sensors Project

This file provides guidance to Claude Code when working specifically in the koi-sensors project.

## 🚨 Current System State (Dec 23, 2025)

- **8 Active Sensors**: Website, GitHub, GitHub Activity, Discourse, Telegram, Twitter, Notion, YouTube
- **Disabled Sensors**: GitLab, Medium, Podcast (no longer needed)
- **All sensors run via systemd** with automatic restart on failure
- **Health Monitoring**: Smart Hybrid system with 30-min heartbeats and on-demand ping
- **Coordinator**: Running on port 8005 with event routing and sensor tracking
- **Dashboard**: Live at https://regen.gaiaai.xyz/koi showing real-time sensor status

### Systemd Sensor Management (Primary Method)
All sensors are managed via systemd template unit `koi-sensor@.service`:

```bash
# Check all sensor status
systemctl list-units 'koi-sensor@*'

# Manage individual sensor
sudo systemctl status koi-sensor@discourse
sudo systemctl restart koi-sensor@discourse
sudo systemctl stop koi-sensor@discourse

# View logs
journalctl -u koi-sensor@discourse -f

# Enable/disable sensor
sudo systemctl enable koi-sensor@notion
sudo systemctl disable koi-sensor@gitlab
```

### Currently Enabled Sensors (systemd)
| Sensor | Service Name | Status |
|--------|--------------|--------|
| Discourse | koi-sensor@discourse | ✅ Active |
| GitHub | koi-sensor@github | ✅ Active |
| GitHub Activity | koi-sensor@github_activity | ✅ Active |
| Notion | koi-sensor@notion | ✅ Active |
| Telegram | koi-sensor@telegram | ✅ Active |
| Twitter | koi-sensor@twitter | ✅ Active |
| Websites | koi-sensor@websites | ✅ Active |
| YouTube | koi-sensor@youtube | ✅ Active |

### Disabled Sensors
- **GitLab**: Disabled Dec 23, 2025 - not needed
- **Medium**: Disabled Dec 23, 2025 - HTTP 403 blocks + code bug
- **Podcast**: Disabled Dec 23, 2025 - no new podcasts being published

### Twitter Sensor Configuration
The Twitter sensor monitors these accounts (configurable via `TWITTER_ACCOUNTS` env var):
- `regen_network` - Main Regen Network account (works reliably)
- `RegenFdn` - Regen Foundation
- `Regentokenomics` - Tokenomics discussions
- `gregory_landua` - Co-founder

**Note**: Twitter's anti-scraping measures block some accounts for unauthenticated Playwright access. Only `@regen_network` works consistently.

### YouTube Sensor Configuration
The YouTube sensor monitors multiple channels and transcribes videos via remote Scribe API:
- `@RegenNetwork` - Main Regen Network channel
- `@FirstPrinciplesAI` - First Principles AI channel
- `@regenfoundation` - Regen Foundation channel

## 🔧 CRITICAL: Dependency Management Rules

**ALWAYS follow these rules when installing packages:**

1. **NEVER use `pip install --break-system-packages`**
2. **ALWAYS use the virtual environment**: `source venv/bin/activate`
3. **ALWAYS update requirements files** after installing:
   - Main dependencies → `requirements.txt`
   - Sensor-specific → `sensors/[sensor_name]/requirements.txt`
   - Dev dependencies → `requirements-dev.txt`

4. **Sensor-specific dependencies:**
   - Each sensor has its own `venv` and `requirements.txt`
   - Dependencies are installed via `./setup.sh` in each sensor directory
   - NEVER install globally or break system packages

## 🚀 Sensor Management

### Systemd Commands (Preferred)
```bash
# Check all sensors
systemctl list-units 'koi-sensor@*'

# Restart specific sensor
sudo systemctl restart koi-sensor@discourse

# View sensor logs
journalctl -u koi-sensor@discourse -f
```

### Legacy Scripts (for setup/debugging)
```bash
./setup_all.sh    # Setup all sensors (one-time)
./status.sh       # Show current status of all sensors

# Individual sensor operations (in sensors/<name>/)
./setup.sh        # Setup this sensor's environment
```

## 📝 Environment Variables

The `.env` file in the root contains API keys and configuration:
- Automatically sourced by systemd via `scripts/run-sensor.sh`
- Contains: NOTION_API_KEY, TELEGRAM_BOT_TOKEN, etc.
- DO NOT commit to git

## 🔍 Debugging

When sensors fail to start:
1. Check systemd status: `sudo systemctl status koi-sensor@[name]`
2. Check logs: `journalctl -u koi-sensor@[name] -n 50`
3. Check sensor log file: `tail -f sensors/[name]/[name]_sensor.log`
4. Verify dependencies: `cd sensors/[name] && ./setup.sh`

## ⚠️ Common Issues

1. **Sensor not starting**: Check `journalctl -u koi-sensor@[name]` for errors
2. **Missing dependencies**: Run `./setup.sh` in the sensor directory
3. **API key errors**: Check `.env` file has required keys
4. **Port conflicts**: KOI Coordinator runs on port 8005

Remember: **All sensors run via systemd** - use `systemctl` commands for management!

## 📅 Recent Updates

### Notion Author Extraction (2026-01-07)

The Notion sensor now extracts author metadata for author-based search:
- `author`: Name of page creator (fetched via `/users/{id}` API if not in page response)
- `author_id`: Notion user ID of creator
- `last_edited_by`: Name of last editor

This enables `person_activity` intent queries like "what is X working on" to find Notion pages authored by specific people.

### Claude Sessions Entity Extraction (2026-02-27)

The Claude sessions sensor now extracts named entities from session transcripts and links them to the personal knowledge graph.

**How it works**:
1. After chunking + embedding, first N turn-pair chunks are sent to OpenAI `gpt-4o-mini`
2. Text is redacted before LLM call (env vars, API keys, connection strings, private keys)
3. Extracted entities are sent to `POST /ingest` on the personal-koi backend
4. The 4-tier entity resolution pipeline handles deduplication
5. `document_entity_links` are created with `claude-session:{session_id}` RIDs

**Config** (`sensors/claude_sessions/config.personal.yaml`):
- `entity_extraction.enabled: true` — gate extraction
- `entity_extraction.link_existing: true` — gate `/ingest` call
- `entity_extraction.extract_new: false` — resolve to existing entities only (no Tier 3)
- `entity_extraction.model: gpt-4o-mini` — extraction model
- `entity_extraction.max_chunks: 5` — chunks sent to LLM

**Key files**: `sensors/claude_sessions/claude_session_sensor.py`, `sensors/claude_sessions/config.personal.yaml`

**Known limitation**: Secret redaction regex does not handle escaped quotes inside quoted env values. Accepted as impractical edge case.
