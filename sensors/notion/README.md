# KOI Notion Sensor

Polling of Notion databases, pages and unresolved comments for the KOI (Knowledge Organization Infrastructure) system.

## Features

- 🔍 **Workspace Discovery**: Automatically discovers accessible databases and pages
- 📊 **Database Monitoring**: Tracks changes in Notion databases
- 📄 **Content Extraction**: Extracts full page content including nested blocks
- 🔄 **Change Detection**: Identifies NEW and UPDATE events from filtered content and metadata
- 💬 **Discussion Records**: Separate comment RIDs with authorship, thread identity and explicit coverage
- 🏷️ **Property Extraction**: Captures supported properties, including status, people and relation IDs
- 🆔 **RID Generation**: Creates KOI-compliant Resource Identifiers
- 📡 **Event Emission**: Sends changes to KOI Coordinator/Event Bridge

See [polling behavior, access requirements and limitations](POLLING.md) for comment capability, unresolved-only coverage, bounded reconciliation and delivery semantics.

## Setup

### 1. Notion Integration

First, create a Notion integration to get API access:

1. Go to https://www.notion.so/my-integrations
2. Click "New integration"
3. Name it (e.g., "KOI Sensor")
4. Select the workspace
5. Copy the "Internal Integration Secret"

### 2. Grant Access to Content

For each database/page you want to monitor:

1. Open the database/page in Notion
2. Click "..." menu → "Add connections"
3. Select your integration
4. The sensor will now be able to access this content

### 3. Configure Environment

```bash
# Set your Notion integration secret
export NOTION_INTEGRATION_SECRET="ntn_your_secret_here"

# Optional: Set coordinator URL (default: http://localhost:8200)
export KOI_COORDINATOR_URL="http://localhost:8200"
```

## Usage

### Test Mode (Verify API Access)

```bash
# Test API connection and discover content
python test_notion_sensor.py

# Test specific database
python test_notion_sensor.py <database-id>
```

### Standalone Mode (No Coordinator)

```bash
# Run without coordinator for testing
python run_notion_sensor.py --standalone
```

### Production Mode (With KOI Coordinator)

```bash
# Start KOI Coordinator first (in another terminal)
cd ../../koi_protocol/coordinator
python run_coordinator.py

# Then start Notion sensor
python run_notion_sensor.py

# Or specify coordinator URL
python run_notion_sensor.py --coordinator-url http://localhost:8200
```

## Configuration

Edit `config.yaml` to customize monitoring:

```yaml
databases:
  - id: "your-database-id-here"
    name: "Governance Proposals"
    check_interval: 1800  # 30 minutes
    priority: high
    
  - id: "another-database-id"
    name: "Research Papers"  
    check_interval: 3600  # 1 hour
    priority: medium
```

## Output Format

The sensor generates KOI events with the following structure:

```json
{
  "event_type": "NEW",
  "source": "notion",
  "rid": "orn:notion.page:regen/abc123def456",
  "title": "Governance Proposal #42",
  "content": "Full page content here...",
  "metadata": {
    "database_id": "database-id",
    "database_title": "Governance Proposals",
    "page_url": "https://notion.so/...",
    "created_time": "2025-09-10T12:00:00Z",
    "last_edited_time": "2025-09-10T14:30:00Z",
    "properties": {
      "Status": "Published",
      "Category": "Governance",
      "Author": "John Doe"
    }
  }
}
```

## Supported Content Types

### Properties
- ✅ Title
- ✅ Rich Text
- ✅ Number
- ✅ Select / Multi-select / Status
- ✅ People (IDs and filtered display names)
- ✅ Relation (page IDs)
- ✅ Date
- ✅ Checkbox
- ✅ URL
- Contact properties (email/phone) are omitted

### Blocks
- ✅ Paragraphs
- ✅ Headings (H1, H2, H3)
- ✅ Lists (Bulleted, Numbered, To-do)
- ✅ Toggle lists
- ✅ Quotes
- ✅ Callouts
- ✅ Code blocks
- ✅ Dividers
- ✅ Nested blocks (recursive)

## Integration with KOI Pipeline

```
Notion API → Notion Sensor → KOI Coordinator → Event Bridge → BGE Embeddings → PostgreSQL → Eliza Agents
```

1. **Notion Sensor** monitors databases for changes
2. **KOI Coordinator** receives events and routes them
3. **Event Bridge** processes with deduplication
4. **BGE Server** generates embeddings
5. **PostgreSQL** stores for agent RAG queries

## Troubleshooting

### "Unauthorized" Error
- Check your integration secret is correct
- Verify the integration has access to the content
- Make sure you've shared databases/pages with the integration

### No Databases Found
- Ensure at least one database is shared with your integration
- Check workspace permissions

### Rate Limiting
- Notion API has rate limits (3 requests/second)
- Failed sources are revisited on later polling cycles; there is no immediate retry loop
- Adjust `check_interval` in config if needed

## Performance

- **Discovery**: Enumerates database page IDs at the configured interval
- **Reconciliation**: Rotates through known pages with a persisted per-cycle budget
- **Emission**: Emits only changed filtered content or metadata
- **Check Interval**: Configurable per database (default: 1 hour)
- **Content Hashing**: SHA-256 for change detection

## Examples

### Monitor Specific Databases

```python
async with NotionKOISensor(notion_token=token) as sensor:
    # Add specific databases to monitor
    await sensor.monitor_database("database-id-1", check_interval=1800)
    await sensor.monitor_database("database-id-2", check_interval=3600)
    
    # Run monitoring
    await sensor.run_monitoring_loop()
```

### Extract Content from Page

```python
async with NotionKOISensor(notion_token=token) as sensor:
    # Get full content
    content = await sensor.get_page_content("page-id")
    
    # Get properties
    page = await sensor.get_page("page-id")
    properties = sensor.extract_properties(page["properties"])
```

## Validation scope

Synthetic polling tests cover pagination, change detection, privacy filtering,
access failures and coordinator retries. Live comment ingestion additionally
requires the integration capability and accessible source pages; downstream
indexing must be verified after an authorized rollout. See [POLLING.md](POLLING.md).

---

Built for the RegenAI KOI Infrastructure