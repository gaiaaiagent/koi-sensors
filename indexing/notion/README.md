# Notion Workspace Knowledge Base

## Overview
This directory contains the complete indexed content from the Regen Network Notion workspace, crawled and extracted on August 19, 2025.

## 📊 Statistics

- **Total Pages Discovered:** 729
- **Pages Successfully Extracted:** 585 (80.2%)
- **Databases Discovered:** 17
- **Databases Successfully Extracted:** 10
- **Total Data Size:** ~45MB
- **Total Content Items:** 595

## 📁 Directory Structure

```
notion/
├── README.md                 # This file
├── manifest.json            # Master index of all discovered content
├── crawl_summary.md         # Summary report from the crawl
├── discovery_report.md      # Initial discovery phase report
├── databases/               # Database exports (10 databases)
│   ├── KOI_Repo/           # 202 Knowledge Object Index entries
│   ├── PRP_Regen_Network_Series_Episodes/  # 7 podcast episodes
│   ├── Podcast_Management/  # 35 podcast management entries
│   ├── Research_Library_for_Terrasos_Whitepaper/  # 17 research items
│   ├── Science_Team_Sprint_Board/  # 195 sprint items
│   └── [other databases...]
├── pages/                   # 585 markdown files with page content
│   ├── *.md                # Page content in markdown format
│   └── *_metadata.json     # Metadata for each page
├── logs/                    # Crawl logs
└── crawler/                 # Crawler scripts and tools
    ├── notion_crawler.py    # Initial discovery crawler
    ├── full_crawler.py      # Full content extraction
    ├── complete_crawl.py    # Complete crawl with batching
    └── monitor_crawl.sh     # Monitoring script
```

## 🔑 Key Content Categories

### Knowledge Object Index (KOI)
- **Location:** `databases/KOI_Repo/`
- **Items:** 202 entries
- **Description:** Core knowledge repository with RIDs, strategies, narratives, and organizational data

### Podcast Content (PRP)
- **Location:** `databases/PRP_Regen_Network_Series_Episodes/`
- **Items:** 7 episodes + 35 management entries
- **Description:** Planetary Regeneration Podcast episodes and management data

### Research & Documentation
- **Location:** `databases/Research_Library_for_Terrasos_Whitepaper/`
- **Items:** 17 research documents
- **Description:** Research library for ecological and economic models

### Project Management
- **Location:** `databases/Science_Team_Sprint_Board/`
- **Items:** 195 sprint items
- **Description:** Historical project management and sprint data

## 🔧 Data Formats

### Databases
Each database folder contains:
- `schema.json` - Database schema and property definitions
- `entries.json` - Raw JSON export of all database entries
- `entries.csv` - CSV export (where successful)

### Pages
- **Markdown Files:** Human-readable content with formatting preserved
- **Metadata Files:** JSON files with page properties, timestamps, and structure

## 📋 Integration Points

### For AI Agents
1. **Knowledge RAG:** Use `manifest.json` as index for all content
2. **KOI Integration:** Parse `databases/KOI_Repo/entries.json` for RIDs and knowledge objects
3. **Content Search:** Index markdown files in `pages/` for full-text search
4. **Structured Data:** Use database JSON files for structured queries

### Access Patterns
```python
# Example: Load KOI database
import json
with open('databases/KOI_Repo/entries.json', 'r') as f:
    koi_entries = json.load(f)

# Example: Load all page titles
with open('manifest.json', 'r') as f:
    manifest = json.load(f)
    page_titles = [p['title'] for p in manifest['pages']]
```

## 🔄 Refresh Schedule

- **Last Crawl:** August 19, 2025 at 18:32 UTC
- **Next Scheduled:** To be determined based on update frequency
- **Refresh Command:** `python crawler/complete_crawl.py`

## ⚠️ Known Limitations

1. **Missing Pages (144):** Some pages were not accessible due to:
   - Permission restrictions
   - Empty/deleted pages
   - API limitations

2. **Missing Databases (7):** Some databases couldn't be extracted due to:
   - Access permissions
   - Complex property types that failed CSV conversion

3. **Child Blocks:** Nested content blocks were flattened for simplicity

## 🚀 Usage Examples

### Search for KOI-related content
```bash
grep -r "KOI" pages/*.md
```

### List all databases
```bash
ls -d databases/*/
```

### Count total pages
```bash
ls pages/*.md | wc -l
```

### Find recent content (last 30 days)
```python
from datetime import datetime, timedelta
import json

with open('manifest.json', 'r') as f:
    manifest = json.load(f)
    
recent = datetime.now() - timedelta(days=30)
recent_pages = [
    p for p in manifest['pages'] 
    if datetime.fromisoformat(p['last_edited'].replace('Z', '')) > recent
]
```

## 📄 License & Access

This content is extracted from the Regen Network Notion workspace under the Joint Development Agreement between Regen Network and partner organizations. Access is restricted to authorized team members.

## 🔗 Related Documentation

- [`/home/regenai/project/indexing/README.md`](../README.md) - Main indexing documentation
- [`/home/regenai/project/CLAUDE.md`](../../CLAUDE.md) - AI assistant guidelines
- [`/home/regenai/project/docs/`](../../docs/) - Project documentation

## 📞 Support

For issues or questions about the Notion data:
1. Check the crawl logs in `logs/`
2. Review the `manifest.json` for content inventory
3. Run `python crawler/analyze_fixed.py` for analysis

---

Last Updated: August 20, 2025