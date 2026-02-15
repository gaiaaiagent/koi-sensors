# Feature Request: Business Development Workflow - Prospect Intelligence Pipeline

**Status:** Proposed
**Priority:** High
**Author:** Gaia Team
**Date:** 2025-01-19

## Summary

Build an automated pipeline to support business development outreach by ingesting prospect data from multiple sources (Otter transcripts, Gmail, Notion), unifying it via entity extraction, and enabling AI-assisted communication drafting.

## User Story

As a business development team member, I want to:
1. Ask "Generate a prospect brief for [Company]" and receive a 1-page summary (stakeholders, pain points, objections, stage, next steps)
2. Ask "Draft a follow-up email to [Contact] after our call" and get a personalized draft based on transcript + prior context
3. Query "What does [Prospect] care about most?" and get synthesized insights from all conversations

**Constraint:** System generates *drafts* for human review—nothing auto-sends.

## Interface Options

All three options hit the same backend—choose based on user preference:

### Option 1: Claude Desktop + KOI MCP
- Full MCP tool support, most powerful
- User adds MCP server config to Claude Desktop (quick config file edit)
- Works immediately once sensors are running
- Requires Claude Desktop installed

### Option 2: Custom GPT (ChatGPT)
- Build a GPT with API actions calling our REST endpoints
- Share via link—users click and start using
- Requires ChatGPT Plus subscription ($20/mo)
- Lower friction for non-technical users

### Option 3: Custom Web UI
- Build a simple chat interface (similar to registry review agent)
- No subscription needed, just go to a URL
- Can tailor UX to BD workflow specifically
- Medium development effort

### Not Viable: Gmail's Embedded Gemini
- Google's Gemini in Gmail is a closed system
- Cannot inject custom tools or MCP connections

### API Compatibility
All interfaces use the same backend:
```
REST API: https://regen.gaiaai.xyz/api/koi/*
MCP: regen-koi-mcp package (for Claude Desktop)
```

## Scope

### New Sensors Needed

#### 1. Gmail Sensor (Priority: HIGH)
- OAuth2 authentication for Google Workspace accounts
- Label-scoped ingestion (e.g., only emails labeled "Prospects")
- Thread-aware: capture full conversation context
- Extract metadata: sender, recipients, date, subject
- Map email addresses to known entities
- **Privacy:** Only ingest labeled threads, audit logging required

**Label Automation (Gmail-native, no development needed):**
Users can set up Gmail filters to auto-apply the "Prospects" label:
```
From: *@prospectcompany.com → Apply label "Prospects"
From: john@specificprospect.com → Apply label "Prospects"
Subject contains "follow up" AND To: user@regen.network → Apply label "Prospects"
```
Setup: Gmail → Settings → Filters and Blocked Addresses → Create new filter

This eliminates manual labeling for known prospect domains/contacts. Users only manually label one-off emails from new prospects.

#### 2. Otter.ai Sensor (Priority: HIGH)
- Otter API integration (or Drive-based fallback for exports)
- Capture meeting metadata: date, attendees, duration
- Speaker diarization mapping to known contacts
- Historical transcript backfill support
- Naming convention: `[Date]-[Company]-[Topic]`
- Chunking strategy optimized for entity linking

#### 3. Google Drive Sensor (Priority: MEDIUM)
- Fallback for Otter exports if API not available
- Folder-scoped ingestion with configurable paths
- File type support: .txt, .docx, .pdf transcripts
- Metadata extraction from filenames

### Cross-Repo Dependencies

#### koi-processor
- [ ] Prospect-specific entity extraction prompts
- [ ] Derived artifacts pipeline: store generated briefs/drafts back to KOI
- [ ] Speaker-to-entity mapping for transcript diarization

#### regen-koi-mcp
- [ ] New tool: `generate_prospect_brief` (structured output)
- [ ] New tool: `draft_outreach_email` (with tone/template options)
- [ ] Enhanced `vault_find_person` for cross-source prospect lookup

## Design Decisions Needed

### MVP Deliverable per Prospect
- **1-page brief**: Stakeholders, pain points, objections, pipeline stage, next steps
- **Follow-up draft**: Post-call email with action items
- **Success metrics**: Time saved per prospect, % of briefs used, reply rate lift

### Data Governance
- [ ] Gmail ingestion scoped to specific labels only
- [ ] Retention rules defined before ingestion
- [ ] Access controls: who can see which prospect data
- [ ] Audit logging for compliance
- [ ] **Never auto-send** policy enforced at tool level

### Prospect Schema / System of Record
- Option A: Notion-as-lightweight-CRM (template with stages, contacts, notes)
- Option B: Internal "Prospect" entity type in KOI with Notion as user-facing surface
- **Recommendation:** Start with Notion template, sync to KOI for entity linking

### Derived Artifacts Pipeline
- Store generated briefs back to Notion (and KOI) with versioning
- Store outreach drafts with edit history
- Store meeting follow-up summaries
- Artifacts should be findable without re-asking

### Otter/Drive Details That Matter
- Meeting metadata: date, attendees, speaker mapping
- Naming conventions: `[Date]-[Company]-[Topic].txt`
- Transcript chunking strategy (affects entity linking quality)
- Speaker diarization mapping to known contacts

### CRM Integration Consideration
- If users already live in HubSpot/Salesforce, consider earlier integration
- Otherwise Notion-first approach is fine for MVP

## Questions to Resolve with Users

### 1. Source of truth for pipeline stage?
Where do they currently track where each prospect is in the sales funnel?
- **Stage examples:** Lead → Contacted → Meeting Scheduled → Proposal Sent → Negotiating → Closed
- **Possible answers:**
  - "We use HubSpot/Salesforce" → Consider CRM integration
  - "We have a Notion database with stages" → Great, already ingest Notion
  - "It's in our heads / scattered in emails" → Help them set up a simple system
- **Why it matters:** Prospect briefs should show current stage and recommended next action

### 2. Per-company rollups or per-contact only?
- **Per-contact:** "Tell me about John Smith" → individual profile
- **Per-company:** "Tell me about Acme Corp" → all contacts, all conversations, company-level pain points
- Most BD workflows need both

### 3. PII/compliance constraints?
- Any policies on storing call transcripts?
- Consent requirements for recording?
- Data retention limits?
- Access controls (who can see which prospect data)?

### 4. First priority format?
What type of communication to focus on generating FIRST:

| Format | Example | Value |
|--------|---------|-------|
| **Follow-up email after call** | "Thanks for the call, here's what we discussed..." | **Highest ROI** - most time-consuming, most personalized |
| **Initial outreach** | Cold email to new prospect | Needs good research/personalization |
| **Meeting prep brief** | Summary before a call | Saves prep time |
| **Pitch deck** | Slides for presentation | Needs templates, more complex |

**Recommendation:** Start with follow-up emails - tedious to write, require referencing specific conversation details.

### 5. CRM usage?
Do they use HubSpot/Salesforce/other? If yes, may want to integrate earlier. If no, Notion-first approach is fine.

## Technical Notes

### Existing Infrastructure to Leverage
- Notion sensor already running
- Entity extraction pipeline (99.7% quality, 10 entity types)
- 3-tier entity deduplication (exact → fuzzy → semantic)
- Cross-source entity linking
- MCP tools for search, entity lookup, neighborhood queries

### Sensor Implementation Pattern
All sensors follow the established pattern:
```python
self.koi_node = KOIPartialNode(
    node_name="<sensor>-sensor",
    coordinator_url="http://localhost:8005",
    poll_interval=30
)
```

Reference implementations:
- Notion sensor (complex, API-based): `/sensors/notion/`
- Discourse sensor (REST API): `/sensors/discourse/`

### RID Conventions for New Sensors

```
Gmail:  orn:gmail.thread:<account>/<thread_id>
Otter:  orn:otter.transcript:<workspace>/<transcript_id>
Drive:  orn:gdrive.file:<drive_id>/<file_id>
```

## Acceptance Criteria

- [ ] Gmail sensor ingests labeled emails with full thread context
- [ ] Otter sensor ingests transcripts with speaker metadata
- [ ] Entities extracted and linked across all three sources (Notion, Gmail, Otter)
- [ ] User can query "everything about [Prospect]" and get unified results
- [ ] User can request prospect brief and receive structured output
- [ ] User can request draft email and receive personalized content
- [ ] All generated content requires human approval before sending
- [ ] Audit log captures all data access and generation events

## Timeline Estimate

**Phase 1 (2 weeks):**
- Gmail sensor MVP (label-scoped)
- Otter sensor MVP (API or Drive fallback)
- Basic prospect search via existing MCP tools

**Phase 2 (2 weeks):**
- Derived artifacts pipeline
- New MCP tools for brief/draft generation
- Notion integration for artifact storage

**Phase 3 (ongoing):**
- CRM integration if needed
- Template library for outreach
- Analytics dashboard

## Related Issues

- koi-processor: Entity extraction enhancements
- regen-koi-mcp: New prospect-focused tools
