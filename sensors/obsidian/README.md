# KOI Obsidian Sensor

Monitor a local Obsidian vault and emit notes to the KOI knowledge graph.

## Features

- **YAML Frontmatter Parsing**: Extracts schema.org typed entities (`@type: Person`, `@type: Organization`, etc.)
- **Wikilink Extraction**: Converts `[[wikilinks]]` to graph relationships
- **Watch Mode**: Monitors vault for real-time changes
- **Relationship Extraction**: Extracts typed relationships from frontmatter fields (affiliation, attendees, project, etc.)
- **Content Hashing**: Only emits updates when content actually changes

## Quick Start

```bash
# Setup
./setup.sh

# Start (watches for changes)
./start.sh

# Or one-time scan
./start.sh --no-watch

# Custom vault path
./start.sh --vault /path/to/vault --vault-name my-vault
```

## Configuration

Set environment variables or use defaults:

```bash
export OBSIDIAN_VAULT_PATH=~/Documents/Notes
export OBSIDIAN_VAULT_NAME=personal
export KOI_COORDINATOR_URL=http://localhost:8005
```

## Expected Vault Structure

The sensor works best with notes that have YAML frontmatter:

```yaml
---
"@type": schema:Person
"@id": people/john-smith
name: John Smith
affiliation: [[Acme Corp]]
jobTitle: Developer
---

# John Smith

Works on [[Project X]] with [[Jane Doe]].
```

### Supported Schema Types

- `Person` - People notes
- `Organization` - Company/org notes
- `Meeting` - Meeting notes with attendees
- `Project` - Project notes

### Relationship Extraction

The sensor extracts relationships from:
1. **Wikilinks**: `[[Note Name]]` → `mentions` relationship
2. **Frontmatter fields**:
   - `affiliation` → `affiliatedWith`
   - `attendees` → `hasAttendee`
   - `project` → `relatedToProject`

## RID Format

Notes are identified by Resource Identifiers (RIDs):

- **Typed entities**: `orn:obsidian.entity:vault/Person/john-smith`
- **Generic notes**: `orn:obsidian.note:vault/path/to/note`

## Emitted Bundle Structure

```json
{
  "rid": "orn:obsidian.entity:personal/Person/john-smith",
  "source": "obsidian",
  "vault": "personal",
  "path": "People/John Smith.md",
  "title": "John Smith",
  "content": "...",
  "body": "...",
  "frontmatter": {
    "@type": "schema:Person",
    "name": "John Smith",
    ...
  },
  "entity_type": "Person",
  "entity_id": "people/john-smith",
  "wikilinks": ["Acme Corp", "Project X", "Jane Doe"],
  "relationships": [
    {"source": "...", "target": "Acme Corp", "relationship_type": "affiliatedWith"},
    {"source": "...", "target": "Project X", "relationship_type": "mentions"}
  ]
}
```

## Development

```bash
# Activate venv
source venv/bin/activate

# Run with debug output
python obsidian_sensor.py --vault ~/Documents/Notes -v

# Filter to specific types
python obsidian_sensor.py --vault ~/Documents/Notes --types Person Organization
```
