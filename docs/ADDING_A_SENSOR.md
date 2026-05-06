# Adding a KOI Sensor

A reference guide for extending the `koi-sensors` framework with a new ingestion path.

**Audience.** Technical contributors who want to add a sensor for a new data
source (an email account, a forum, an API, an RSS-shaped feed, a chat, a
calendar) without first having to read every other sensor's source. Worked
examples reference real production code paths so you can copy-and-modify
rather than reverse-engineer.

**Status.** Written 2026-05-06 against `koi-sensors/main`. Reflects
post-`c3a8013` `document_to_bundle` behaviour and the post-`2026-01-02`
forwarder routing — see [Architecture](#2-architecture-overview) for the
known regression caveat that affects what your sensor produces downstream.

---

## Table of Contents

- [Quick start](#quick-start)
- [1. What is a sensor?](#1-what-is-a-sensor)
- [2. Architecture overview](#2-architecture-overview)
- [3. Decisions to make BEFORE writing code](#3-decisions-to-make-before-writing-code)
- [4. Minimum viable sensor — the newsletters walkthrough](#4-minimum-viable-sensor--the-newsletters-walkthrough)
- [5. Privacy and access control](#5-privacy-and-access-control)
- [6. Configuration patterns](#6-configuration-patterns)
- [7. Deploy and run](#7-deploy-and-run)
- [8. Idempotency and state](#8-idempotency-and-state)
- [9. Testing](#9-testing)
- [10. Observability](#10-observability)
- [11. Common pitfalls](#11-common-pitfalls)
- [12. Reference: existing sensors at a glance](#12-reference-existing-sensors-at-a-glance)
- [13. Adding to deployment](#13-adding-to-deployment)
- [14. When your data shape doesn't fit](#14-when-your-data-shape-doesnt-fit)
- [15. Future: SDK direction](#15-future-sdk-direction)

---

## Quick start

If you've added a sensor before, here's the minimum sequence. Everyone else,
skip to [Section 1](#1-what-is-a-sensor).

```bash
# 1. Clone the cleanest reference sensor as a starting point
cp -r koi-sensors/sensors/newsletters koi-sensors/sensors/<your-name>
cd koi-sensors/sensors/<your-name>
mv newsletters_sensor.py <your-name>_sensor.py

# 2. Edit the sensor module:
#    - rename the class (NewslettersKOISensor -> YourSensor)
#    - replace the IMAP polling logic with your source's polling logic
#    - keep the bundle-emit shape: document dict -> document_to_bundle -> emit_new_event
#    - keep PersistentSensorState for idempotency
#    - keep the heartbeat + main loop scaffolding

# 3. Edit config.yaml: source-specific config, per-route privacy, env-var refs

# 4. Add your sensor name to scripts/run-sensor.sh case statement

# 5. Local test
./setup.sh
./start.sh   # foreground; Ctrl-C to stop

# 6. Deploy (see Section 13)
git add -A && git commit -m "feat(<name>): initial sensor"
git push origin main
ssh darren@202.61.196.119
cd /opt/projects/koi-sensors && git pull origin main
cd sensors/<your-name>/ && ./setup.sh
sudo systemctl enable --now koi-sensor@<your-name>.service
journalctl -u koi-sensor@<your-name> -f
```

The reference sensor for "what good looks like in 2026" is
`koi-sensors/sensors/newsletters/newsletters_sensor.py`. It was written most
recently (2026-05-05), follows current conventions strictly, and documents
non-obvious behaviour inline.

---

## 1. What is a sensor?

A **KOI sensor** is a long-running Python service that:

1. **Polls or listens** to one external data source (an IMAP mailbox, a
   Notion workspace, an RSS feed, a GitHub repo, a chat channel, an API).
2. **Wraps each new item** as a normalised `document` dict.
3. **Builds a KOI Bundle** via `document_to_bundle()` (manifest + content +
   stable RID).
4. **Emits the bundle** as a `NEW` event to the local KOI coordinator.
5. **Persists state** (which items it has already emitted) so it is
   idempotent across restarts.

The sensor framework lives in this repo (`koi-sensors`); the consumers live
in `koi-processor` (the bridges that write to PostgreSQL). Each sensor runs
under systemd as `koi-sensor@<name>.service`.

What sensors are NOT:

- They do **not** chunk text. (The bridge does.)
- They do **not** compute embeddings. (The bridge does.)
- They do **not** extract entities. (The v2 bridge runs `PassAExtractor`
  on each ingested doc.)
- They do **not** write to PostgreSQL directly. (Always via the
  coordinator + bridge.)
- They do **not** generally talk to other sensors. (Independent processes.)

A sensor's job is narrow on purpose: **fan in one source's content as a
stream of bundles, with stable RIDs and accurate provenance metadata**.
Everything else is downstream.

---

## 2. Architecture overview

### Data flow

```
                                                       ┌────────────────────────┐
External source                                        │ Team prod PostgreSQL   │
(Gmail / Notion / GitHub /                             │ (gaia-postgres-1, 5433)│
 RSS / chat / API / ...)                               │ DB: eliza              │
       │                                               └───────────┬────────────┘
       │ poll/webhook                                               │
       ▼                                                            │
┌─────────────┐    NEW event   ┌──────────────┐   POST /events  ┌─────────────────┐
│   sensor    │  ───────────▶  │ coordinator  │  ────────────▶  │   forwarder     │
│ (this repo) │   bundle       │ (port 8005)  │   bundle        │ (koi-processor) │
└─────────────┘                └──────────────┘                  └────────┬────────┘
       │                              ▲                                   │
       ▼                              │                                   ▼
┌──────────────────────┐               │                          ┌─────────────────────┐
│ <name>_sensor_state  │               │                          │ koi-event-bridge    │
│ .json (idempotency)  │               │                          │ v2 (port 8100)      │
└──────────────────────┘               │                          │  - chunks via       │
                                       │                          │    chunk_text       │
       systemd: koi-sensor@<name>      │                          │  - BGE embeddings   │
       wrapper: scripts/run-sensor.sh  │                          │  - writes to        │
                                       │                          │    koi_memories +   │
                                       │                          │    koi_embeddings   │
                                       │                          └──────────┬──────────┘
                                       │                                     │
                                       │                                     ▼
                                       │                          ┌─────────────────────┐
                                       │                          │ koi_memories table  │
                                       │                          │ (RAG corpus)        │
                                       │                          └──────────┬──────────┘
                                       │                                     │
                                       │ /events/poll                        │
                                       └─────────────────────────────────────┘
                                       (events durable until confirmed)
                                                                             │
                                                                             ▼
                                                                ┌──────────────────────┐
                                                                │ Search-side          │
                                                                │  - koi-query-api.ts  │
                                                                │    (port 8301)       │
                                                                │  - regen-koi-mcp     │
                                                                │  - browser portal    │
                                                                └──────────────────────┘
```

### Component contracts

- **Sensor** — emits `NEW`/`UPDATE`/`FORGET` events to the coordinator. Owns
  RID stability and bundle metadata correctness. Idempotent.
- **Coordinator** (`koi_protocol/coordinator/`, port `8005`) — receives
  events, queues them with delivery tracking, forwards to subscribed nodes,
  exposes `/health` and `/events/broadcast` and `/events/poll`. Persists
  events until all subscribers confirm receipt.
- **Forwarder** — coordinator subprocess that POSTs each event to the
  configured `EVENT_BRIDGE_URL`.
- **Bridge** — receives the event, materialises the bundle into PostgreSQL
  rows (chunking, embeddings, and Pass-A entity extraction). **As of
  2026-01-02**, all events route to `koi_event_bridge_v2.py` on port
  `8100`. A second bridge (`koi_event_bridge_semantic.py` on port `8004`)
  exists but has been unfed since the routing flip; v2 covers extraction.
- **Search side** — separate processes that read from the same DB.

### Historical incident: URI fragmentation (resolved 2026-05-06)

Between 2026-01-02 and 2026-05-06, entity-driven retrieval over post-Jan
content was silently degraded. Vector + keyword search worked the whole
time (BGE pipeline never broke), but entity-name lookups returned shallow
results for content ingested in that window.

Original hypothesis (now overturned): "v2 bridge stopped running entity
extraction." Phase 0 audit on 2026-05-06 confirmed v2 IS running
`PassAExtractor` (see `koi_event_bridge_v2.py::trigger_kg_extraction`); the
real issue was **URI fragmentation** — `koi_entity_chunk_links.entity_uri`
and `entity_registry.fuseki_uri` had drifted into three coexisting URI
shapes, so 99.997% of chunk-link URIs had no matching registry row. The
overnight Option C run canonicalized 1.2M chunk_link rows against the
5-tier resolver; orphan rate is now 0.02%.

**What this means for sensor authors:** your job hasn't changed — emit
doc-shaped bundles with accurate metadata. Entity-driven retrieval now
works across all post-Jan cohorts (newsletter / notion / github / forum /
web / youtube). If you see an entity-search miss on freshly ingested
content, file a bug rather than working around it.

See memory entries `project_entity_registry_canonicalization.md` and
`project_v2_bridge_pipeline_regression.md` for full audit + resolution.

---

## 3. Decisions to make BEFORE writing code

Half of "this sensor is hard to add" comes from re-litigating these in
mid-implementation. Decide once, document in the sensor's `README.md`,
move on.

### 3.1 Privacy posture

Will the content be **public** (visible to unauthenticated `/api/koi/query`
callers) or **private** (only visible to authenticated `@regen.network`
sessions)?

- **Public** — leave `is_private` and `access_source` out of the document
  metadata. The bridge defaults the column to `FALSE` and the read-side
  privacy filter passes the row through.
- **Private** — set `metadata.is_private = True` and
  `metadata.access_source = "<stable-string-tag>"`. The string tag should
  identify the cohort cleanly enough to bulk-update or audit later
  (examples: `notion-main-workspace`, `substack-nate-jones-paid`,
  `slack-team`).

If the source has multiple cohorts with different privacy postures (a
public Notion workspace and a private one in the same sensor), make the
privacy decision **per route**, not per sensor. The Notion sensor is the
canonical multi-cohort example; the newsletters sensor uses
per-`newsletters[]` entries.

### 3.2 Polling cadence

Three regimes in current sensors:

| Cadence | When to use | Examples |
|---|---|---|
| 30 s – 5 min | Real-time-ish (chat, social) | telegram, discord, twitter |
| 5 min – 1 hour | Standard (API polling, RSS) | github, github_activity, notion |
| 6 – 24 hours | Slow sources (blog archives) | medium, podcast |

Pick the longest cadence that meets your freshness need; rate-limited APIs
will punish over-polling. The newsletter sensor polls every 600 s (10 min)
because newsletters arrive a few times per day at most.

### 3.3 Authentication

Where does your sensor's secret live? Three patterns:

- **API key / token** — store in `/opt/projects/koi-sensors/.env` as a
  KEY=VALUE pair. Reference from `config.yaml` as `${VAR_NAME}` and have
  the sensor's config loader expand it. NEVER commit secrets.
- **OAuth refresh token** — same as above, store in `.env`. Sensor refreshes
  access tokens at runtime.
- **Browser session storage** — for sources without a clean API (paid
  Substack archive, some private forums). Persist a Playwright
  `storage_state` JSON file outside the repo (`chmod 600`). Newsletter
  sensor's `--scrape-substack-archive` mode is the canonical example.

### 3.4 Per-source vs single-source config

If your sensor will likely watch **one** source forever, hardcode less.
Single config block, `enabled: true|false`, done.

If your sensor will watch **N** sources of the same shape (multiple
newsletter senders, multiple Notion workspaces, multiple RSS feeds, etc.),
build the config as a **list of routes/sources** at the top level. This is
the harder pattern but pays off the moment Greg or anyone else wants to
add the second source without touching Python.

The newsletters sensor has it right: top-level `newsletters: [...]` list,
each entry has `match`, `slug`, `is_private`, `access_source`, `tags`. Adding
a new newsletter is a one-line config edit, no code change.

### 3.5 RID shape

The RID is the durable identity for an item. **It must be stable across
re-runs and (ideally) across systems.** Patterns by source type:

| Source | Pattern | Example |
|---|---|---|
| Email | `orn:newsletter.<slug>.<sha256-of-message-id+from+subject+date>` | `orn:newsletter.nate-jones-substack.a1b2c3d4e5f67890` |
| Notion | `orn:notion.page:<workspace>/<page_id>` | `orn:notion.page:regen/abc123...` |
| GitHub | `orn:github.file:<owner>/<repo>/<branch>/<path>` | uses `rid_lib`'s `GitHubFile` |
| RSS / blog | `orn:medium.article.<id-from-url-or-hash>` | extracted from the URL slug |
| Chat | `orn:<platform>.message:<channel>/<msg_id>` | telegram/discord patterns |

Hard rules:

- **Never** include `now()` or any per-run timestamp in the RID. Re-runs
  will collide-fail or produce duplicates.
- **Never** use a content hash alone. Edits to the same item should keep
  the RID and update the content; content-hash RIDs treat every edit as a
  new entity.
- **Prefer** the source's own primary key (Notion's `page_id`, the email's
  `Message-ID`, the GitHub file path on a branch). Fall back to a stable
  digest of identifying headers/URL/title.
- **Persist** the RID format choice. Once your sensor has emitted RIDs
  shaped one way, every subsequent run must produce identical RIDs for the
  same source items.

---

## 4. Minimum viable sensor — the newsletters walkthrough

This section walks through `sensors/newsletters/newsletters_sensor.py` as
the worked example. It's the cleanest current sensor (~1,400 lines, but
the daemon path is ~250 lines; the rest is `--ingest-mbox` and
`--scrape-substack-archive` one-shot modes you may not need).

### 4.1 Imports

```python
import argparse, asyncio, email, hashlib, imaplib, json, logging, mailbox
import os, re, ssl, urllib.parse
from datetime import datetime, timezone, timedelta
from email import policy
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import html2text
import yaml

from koi_protocol.nodes.koi_node import KOIPartialNode
from koi_protocol.core.rid_system import RID
from koi_protocol.core.bundle_system import document_to_bundle
from shared.persistent_state import PersistentSensorState
```

The four framework imports — `KOIPartialNode`, `RID`, `document_to_bundle`,
`PersistentSensorState` — are the entire framework surface a sensor needs.

### 4.2 RID class

```python
class NewsletterEntryRID(RID):
    """Newsletter entry RID: orn:newsletter.<slug>.<digest>."""

    def __init__(self, slug: str, digest: str):
        super().__init__("orn", f"newsletter.{slug}.{digest}")
```

Subclass `RID` (or `ORN`) for your namespace. `RID.__init__(context,
reference)` builds the canonical `<context>:<reference>` string. For
sources backed by `rid-lib` (GitHub, Notion, Twitter, YouTube, Web,
Discourse, Gmail), import from `shared/rid_types/` rather than rolling
your own — there's already a wire-compatible class.

### 4.3 Sensor class init

```python
class NewslettersKOISensor:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.cfg, self.imap_cfg, self.routes, self.filtering = self._load(config_path)
        self.logger = self._setup_logging()

        self.koi_node = KOIPartialNode(
            node_name=self.cfg["name"],
            coordinator_url=self.cfg["coordinator_url"],
            poll_interval=30,
        )
        self.state = PersistentSensorState("newsletters", Path(__file__).parent)
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
```

Key points:

- `KOIPartialNode` is the framework's sensor-side node. It generates a
  stable, key-derived node identity (or loads it from a persisted private
  key) and provides `start()`, `stop()`, `emit_new_event(bundle)`. The
  `coordinator_url` is `http://localhost:8005` on prod; sensors run on the
  same host as the coordinator.
- `PersistentSensorState` reads `<sensor_dir>/<name>_sensor_state.json` if
  present and exposes a `processed: Set[str]` of RIDs already emitted.
  This is the idempotency primitive.
- `_main_loop` is captured in `start()` so blocking IO threads (IMAP
  polling) can schedule coroutines back onto the asyncio loop.

### 4.4 Polling loop

```python
async def start(self) -> None:
    self._main_loop = asyncio.get_running_loop()
    await self.koi_node.start()
    await self.send_heartbeat_event()
    asyncio.create_task(self.send_periodic_heartbeats())

    while getattr(self.koi_node, "running", True):
        try:
            await self.poll_once()
            self.state.save()
        except Exception as e:
            self.logger.error(f"poll error: {e}", exc_info=True)
        await asyncio.sleep(self.cfg["poll_interval"])
```

The skeleton every daemon-mode sensor follows:

1. Capture the running asyncio loop.
2. Start the KOI node (registers identity, opens HTTP session).
3. Send an initial heartbeat (so the coordinator knows you're alive).
4. Spawn a background task to send heartbeats every 30 minutes.
5. Loop forever: poll once, save state, sleep, repeat. Catch and log
   per-iteration errors so a single bad poll doesn't kill the daemon.

### 4.5 Heartbeats

```python
async def send_heartbeat_event(self, response_to: Optional[str] = None) -> None:
    heartbeat_data = {
        "type": "sensor_heartbeat",
        "sensor_id": self.cfg["name"],
        "sensor_type": "newsletters",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "monitoring": [r["slug"] for r in self.routes],
        "items_tracked": len(self.state.processed),
    }
    heartbeat_document = {
        "id": f"newsletters_heartbeat_{int(datetime.now().timestamp())}",
        "title": "Newsletters Sensor Heartbeat",
        "url": "",
        "type": "heartbeat",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content": json.dumps(heartbeat_data),
        "metadata": {
            "sensor_type": "newsletters",
            "sensor_id": self.cfg["name"],
            "event_type": "HEARTBEAT",
        },
    }
    bundle = document_to_bundle(heartbeat_document)
    await self.koi_node.emit_new_event(bundle)
```

The dashboard at `regen.gaiaai.xyz/koi` reads heartbeats to show liveness;
absent heartbeats trigger the "stale sensor" alert. Send one on startup
and one every 30 min. **Don't skip heartbeats** — the only signal that
your sensor is alive between polls is the heartbeat.

### 4.6 Per-message processing — the document → bundle conversion

This is the load-bearing function. Annotated tightly:

```python
def _process_message(self, folder: str, uid: int, raw: bytes, cutoff: datetime) -> bool:
    msg = email.message_from_bytes(raw, policy=policy.default)

    # ---- 1. Pull source-specific headers/fields
    from_addr = parseaddr(str(msg.get("From", "")))[1].lower()
    subject = str(msg.get("Subject", "(No Subject)")).strip()
    message_id = str(msg.get("Message-ID", "")).strip()
    date = parsedate_to_datetime(str(msg.get("Date", "")))
    # ... body extraction, age filter, etc.

    # ---- 2. Resolve the route (per-source config)
    route = _match_sender(self.routes, from_addr, list_id)
    if route is None:
        return False

    # ---- 3. Compute stable RID
    digest = _stable_digest(message_id, from_addr, subject, date)
    rid_obj = NewsletterEntryRID(route["slug"], digest)
    rid_str = rid_obj.to_string()

    # ---- 4. Idempotency check
    if self.state.is_processed(rid_str):
        return True   # already emitted; advance watermark

    # ---- 5. Build the document dict
    document = {
        "id": f"newsletter_{route['slug']}_{digest}",
        "source": f"newsletters:{route['slug']}",
        "source_type": "newsletter",
        "rid": rid_str,
        "url": url,
        "title": subject,
        "content": full_text,
        "metadata": {
            "title": subject,
            "url": url,
            "newsletter_slug": route["slug"],
            "tags": list(route.get("tags") or []),
            # Privacy / access control — see Section 5
            "is_private": bool(route["is_private"]),
            "access_source": route["access_source"],
            # Dates
            "published_at": published_iso,
            "published_confidence": 0.95 if published_iso else 0.0,
            # Bookkeeping
            "collection_method": "newsletters_sensor",
            "koi_sensor": self.cfg["name"],
        },
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "last_modified": published_iso,
        "tags": list(route.get("tags") or []),
    }

    # ---- 6. Emit
    self.state.mark_pending(route["slug"], rid_str)
    try:
        bundle = document_to_bundle(document, self.koi_node.node_id)
        success = self._emit_blocking(bundle)
    except Exception as e:
        self.state.clear_pending(route["slug"], rid_str)
        return False

    # ---- 7. Mark processed on success
    if success:
        self.state.mark_processed(route["slug"], rid_str)
        return True
    self.state.clear_pending(route["slug"], rid_str)
    return False
```

The seven-step shape is the pattern. Whatever your source, the per-item
flow is: pull fields → match route → RID → idempotency check → build
document → emit → mark processed.

### 4.7 The document dict — what fields matter

The `document` dict has a few load-bearing keys:

- `id` (str) — local identifier; used as the original_id passthrough.
- `source` (str) — short tag, e.g. `"newsletters:nate-jones-substack"`.
- `source_type` (str) — categorical, e.g. `"newsletter"`, `"notion-page"`,
  `"github-file"`. Search/filter consumers key off this.
- `url` (str) — canonical URL of the item. Populates `metadata.url` in the
  bundle and gets promoted to the `koi_memories.metadata->>'url'` column.
- `title` (str) — used in search snippets and in the digest UI.
- `content` (str) — the chunk-able body. The bridge chunks this directly.
- `metadata` (dict) — arbitrary fields. **But see Section 11: most fields
  here get stripped before they reach the bridge.**
- `collected_at` / `last_modified` — ISO-8601 strings.
- `tags` (list[str]) — surfaced in `koi_memories.metadata.tags`.

The bridge ultimately writes a row into `koi_memories` with columns:
`rid`, `source`, `content` (chunk text), `metadata` (JSONB), `is_private`,
`access_source`, `created_at`. Plus a row in `koi_embeddings.dim_1024` per
chunk.

---

## 5. Privacy and access control

### 5.1 The data flow

```
sensor                       document_to_bundle           bridge                       koi_memories columns
─────────────────────────    ─────────────────────────    ──────────────────────────   ────────────────────
metadata.is_private = True   bundle.manifest.metadata     event.bundle.manifest        koi_memories.is_private
metadata.access_source =     .is_private = True           .metadata['is_private']      = TRUE  (column)
  "<source-tag>"             .access_source = "<tag>"     promoted to dedicated        access_source = "<tag>"
                                                          columns at INSERT            (column)
                                                          (sticky-OR ON CONFLICT)
```

Three things to know:

1. **Sensor-side**: set `metadata.is_private` (bool) and
   `metadata.access_source` (str) in the document dict. Choose the
   `access_source` string to identify the cohort cleanly (so you can
   audit/bulk-update later).
2. **Bundle conversion**: `document_to_bundle()` passes both fields
   through to `bundle.manifest.metadata`. **This is a whitelist**, not a
   passthrough — see [Section 11](#11-common-pitfalls).
3. **Bridge-side**: `koi_event_bridge_v2.py` reads `bundle.manifest.metadata
   ['is_private']` and writes it to a dedicated column on `koi_memories`.
   The ON CONFLICT clause is sticky-OR: once a row is private, re-emitting
   the same content with `is_private=False` does NOT flip it back.

### 5.2 The read-side filter

`koi-query-api.ts` (port 8301, bun) has a
`buildPrivacyFilter(isAuthenticated)` that adds:

```sql
WHERE m.is_private = false OR m.is_private IS NULL
```

for unauthenticated callers. Authenticated `@regen.network` Bearer
sessions see all rows. The same filter applies to `/rid-lookup`, `/rids`,
`/stats`, and the weekly digest endpoint.

### 5.3 Choosing `access_source` strings

Stable, kebab-cased, scoped tags. Examples in production:

```
notion-main-workspace
notion-regentokenomics
substack-nate-jones-paid
substack-other
slack-team
github-private
```

**Don't use** raw URLs, free-form descriptions, or per-document tokens.
The string is a **cohort identifier**, not a per-item label. You should
be able to write `WHERE access_source = 'X'` and get back exactly the set
of rows you'd hand-roll-bulk-update if you needed to revoke or audit
that cohort.

### 5.4 Per-route privacy (multi-cohort sensors)

If your sensor has cohorts with mixed privacy, configure it in `config.yaml`
per route, not per sensor. The newsletter sensor's pattern:

```yaml
newsletters:
  - match: natesnewsletter
    slug: nate-jones-substack
    access_source: substack-nate-jones-paid
    is_private: true
  - match: somepublicfeed
    slug: public-feed
    access_source: public-blog-mirror
    is_private: false
```

The route lookup happens per item (`_match_sender`), and the privacy
fields land in the document `metadata` from the matched route.

### 5.5 Don't lie to yourself about privacy

If your sensor handles secrets (paid newsletters, private notion
workspaces, internal Slack channels), **default to private**. It is much
cheaper to flip a public default to private later than to recall a
leaked private cohort. The newsletter sensor's `_load` enforces
`r.setdefault("is_private", True)` so a forgotten config field defaults
to private.

---

## 6. Configuration patterns

### 6.1 The standard `config.yaml` shape

```yaml
sensor:
  name: <name>-sensor                    # used as koi_node.node_name
  type: <name>                           # informational, used in heartbeat
  node_id: koi-sensor-<name>-001         # stable identifier
  coordinator_url: http://localhost:8005
  poll_interval: <seconds>

# Source-specific config (varies wildly by sensor)
imap:                                    # or: api, http, websocket, files, ...
  host: imap.gmail.com
  port: 993
  ssl: true
  username: darrenainews@gmail.com
  password_env: GMAIL_NEWSLETTERS_APP_PASSWORD
  folders:
    - "KOI/Substack"

# Per-source routing (the "cookbook" of what to ingest)
newsletters:                             # or: workspaces, repos, feeds, channels, ...
  - match: natesnewsletter
    slug: nate-jones-substack
    access_source: substack-nate-jones-paid
    tags: [substack, ai, newsletter, paid]
    is_private: true

# Shared knobs
filtering:
  max_age_days: 365
  min_body_length: 200
  default_route: null
```

### 6.2 Secret references

**Don't put secrets in `config.yaml`.** Two patterns:

**Pattern A** (preferred): name an env var, expand at load time.

```yaml
imap:
  password_env: GMAIL_NEWSLETTERS_APP_PASSWORD
```

```python
def _expand_env(value: str) -> str:
    name = match.group(1)
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"config references unset env var: {name}")
    return val
```

**Pattern B**: inline `${VAR}` placeholders. Same idea, more flexible —
useful when a config field embeds a secret in a longer string.

```yaml
api_url: "https://api.example.com/?token=${EXAMPLE_API_TOKEN}"
```

The actual values live in `/opt/projects/koi-sensors/.env` on prod (and
in your local `.env` for testing). `run-sensor.sh` sources `.env` before
exec-ing your script.

### 6.3 What goes in `.env`

Each sensor's secrets get a unique env-var name to avoid collisions.
Convention: `<UPPER_SNAKE_SENSOR_NAME>_<PURPOSE>`. Examples currently in
production:

```
NOTION_API_KEY=secret_xxx
REGENTOKENOMICS_NOTION_API_KEY=secret_yyy
GMAIL_NEWSLETTERS_APP_PASSWORD=zzz
TELEGRAM_BOT_TOKEN=12345:ABC
DISCORD_BOT_TOKEN=...
GITHUB_TOKEN=ghp_...
```

`.env` is `chmod 600` and gitignored. Never commit it.

### 6.4 The standard `requirements.txt`

Three layers:

```
# Sensor-specific
PyYAML>=6.0
pydantic>=2.0.0
python-dotenv>=1.0.0
html2text>=2020.1.16
aiohttp>=3.8.0

# Shared koi-sensors framework deps (run-sensor.sh preflight expects these)
rid-lib==3.2.12
cryptography>=42.0.0

# Optional one-shot mode deps
playwright>=1.40.0
asyncpg>=0.28.0
```

**Pin `rid-lib==3.2.12`** explicitly — `run-sensor.sh` does a preflight
import check on it before exec, and a missing/wrong version will burn
through systemd's restart limit silently.

Avoid heavy deps unless you need them. Playwright + chromium adds ~300 MB
per sensor venv.

### 6.5 setup.sh and start.sh

Both are boilerplate. Copy from `sensors/newsletters/`:

`setup.sh`:

```bash
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
[ ! -d "venv" ] && python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "Setup complete."
```

`start.sh`:

```bash
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
source venv/bin/activate
export PYTHONPATH="$SCRIPT_DIR/../..:$PYTHONPATH"

# Source root .env so ${VAR} placeholders resolve
if [ -f "$SCRIPT_DIR/../../.env" ]; then
    set -a
    source "$SCRIPT_DIR/../../.env"
    set +a
fi

python3 <name>_sensor.py
```

`start.sh` is for foreground local testing. Production uses
`scripts/run-sensor.sh` via systemd — see [Section 7](#7-deploy-and-run).

---

## 7. Deploy and run

### 7.1 The wrapper: `scripts/run-sensor.sh`

When systemd starts `koi-sensor@<name>.service`, it executes
`/opt/projects/koi-sensors/scripts/run-sensor.sh <name>`. The wrapper:

1. `cd`s into `/opt/projects/koi-sensors/sensors/<name>/`.
2. Activates the per-sensor venv (`./venv/bin/activate`).
3. Sets `PYTHONPATH=/opt/projects/koi-sensors:$PYTHONPATH` so the
   `koi_protocol` and `shared` packages are importable.
4. Sources `/opt/projects/koi-sensors/.env` — every line becomes an env
   var.
5. **Critical override:** sets `KOI_ENVELOPE_SIGN=false` (overriding the
   `.env` value of `true`) for local sensors. See
   [Section 11](#11-common-pitfalls).
6. Resolves which Python file to run via a `case` statement (or a
   convention-fallback). Add your sensor's case here:

```bash
case $SENSOR in
    ...
    newsletters)
        SCRIPT="newsletters_sensor.py"
        ;;
    <your-name>)
        SCRIPT="<your-name>_sensor.py"
        ;;
    ...
esac
```

7. Runs a preflight import check on `rid_lib` and `cryptography` to fail
   fast on a broken venv.
8. `exec`s `python3 $SCRIPT`.

### 7.2 The systemd template

`/etc/systemd/system/koi-sensor@.service`:

```ini
[Unit]
Description=KOI %i Sensor
After=network.target
Wants=network.target
OnFailure=koi-sensor-alert@%i.service

[Service]
Type=simple
User=darren
Group=gaia-devs
WorkingDirectory=/opt/projects/koi-sensors/sensors/%i
ExecStart=/opt/projects/koi-sensors/scripts/run-sensor.sh %i
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=600
StartLimitBurst=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=koi-sensor-%i
TimeoutStopSec=60
KillMode=mixed
KillSignal=SIGTERM
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/projects/koi-sensors

[Install]
WantedBy=multi-user.target
```

The `%i` is the sensor name, instantiated by enabling
`koi-sensor@<name>.service`. You don't need to edit this template — the
template handles every sensor uniformly. Adding a new sensor is purely a
matter of:

1. Creating `sensors/<name>/`.
2. Adding the `case` to `run-sensor.sh`.
3. `sudo systemctl enable --now koi-sensor@<name>.service`.

### 7.3 Local testing without systemd

For dev/debug:

```bash
cd /Users/darrenzal/projects/RegenAI/koi-sensors/sensors/<name>
./setup.sh    # one-time
./start.sh    # foreground
```

`start.sh` activates the venv, sources `.env`, and runs the sensor in the
foreground so you can see output and Ctrl-C cleanly.

### 7.4 One-shot script invocations (the KOI_ENVELOPE_SIGN gotcha)

If you bypass `run-sensor.sh` (for example, a one-off backfill) you must
manually replicate the override:

```bash
cd /opt/projects/koi-sensors/sensors/<name>
source venv/bin/activate
set -a; source ../../.env; set +a
export KOI_ENVELOPE_SIGN=false              # ← this line is critical
export PYTHONPATH=/opt/projects/koi-sensors:$PYTHONPATH
python3 <name>_sensor.py --your-flag
```

Without `KOI_ENVELOPE_SIGN=false`, the sensor reads the `.env` value
(`true`), generates an ephemeral keypair, signs envelopes with a public
key the coordinator doesn't know, and every event fails with
`No public key registered for orn:koi-net.node:...`. The sensor logs
"skipped" (not "errored"), which is easy to misread as "no matching
routes."

This was diagnosed during the 2026-05-05 Nate Substack backfill: first
run skipped 39 messages with no per-message log lines preceding the
skips; re-run with the override produced `emitted=38, skipped=1`.

---

## 8. Idempotency and state

### 8.1 The state file

Each sensor writes `<sensor_dir>/<name>_sensor_state.json` containing:

```json
{
  "queues": {"<source>": ["rid1", "rid2", ...]},
  "processed": ["rid_a", "rid_b", ...],
  "pending": {"<source>": ["rid_c"]},
  "counters": {"<source>": 1234},
  "metadata": {"folder:INBOX:uidvalidity:5:max_uid": 12345},
  "last_saved": "2026-05-05T08:00:00Z",
  "sensor": "newsletters"
}
```

The `processed` set is the authoritative record of "which RIDs have we
emitted". `is_processed(rid)` is the one check that gates idempotency.

`metadata` is a free-form dict for sensor-specific watermarks (IMAP
UIDVALIDITY-scoped max-UIDs, last-page tokens, last-poll timestamps,
etc.).

### 8.2 The pending pattern

The state machine is:

```
queue → pending (mark_pending)  → processed (mark_processed on emit success)
                                ↓ on emit failure
                                queue (clear_pending so we retry next poll)
```

The `pending` set is small and exists to handle the case where the
process dies between `emit_new_event` returning success and the state
file being saved. On restart, `pending` items are still candidates;
either the duplicate-emit is harmless (the bridge dedups by content
hash) or you'll catch the dup in `is_processed`.

### 8.3 What happens if you delete a row from `koi_memories`?

The sensor's `processed` set still contains the RID. The sensor will
**not** re-emit. To re-ingest:

1. Identify the RID(s) you want re-emitted.
2. Edit `<name>_sensor_state.json` and remove the matching entries from
   `processed` (and decrement counters if you care).
3. Restart the sensor.

There's no one-button "re-ingest cohort" tool today. This is fine for
small surgical re-emits; for bulk re-ingestion, build a one-shot CLI
flag (the newsletters sensor's `--ingest-mbox` is an example).

### 8.4 RID stability is the hidden axis

If your RID computation changes between releases (different hash inputs,
different namespace), the sensor will re-emit every item it has ever
seen, because `is_processed(new_rid)` is false for every item. This is
both noisy (bridge re-chunks) and confusing (search results suddenly
show duplicates).

**Test RID stability before the first deploy.** Run the sensor twice
against the same source; the second run should emit zero items.

---

## 9. Testing

### 9.1 The dry-run / diagnostic flag pattern

For one-shot operations (mbox import, archive scrape, full-source
backfill), add a `--dry-run` CLI flag that walks the work and logs what
it *would* do without emitting:

```python
parser.add_argument("--dry-run", action="store_true",
                    help="List items that would be emitted without emitting")
```

In the work loop:

```python
if dry_run:
    for c in candidates:
        self.logger.info(f"[dry-run] would emit: {c['url']} ({c['title']})")
    return stats
```

This is invaluable for first-run validation and for resolving
"how-many-items-am-I-about-to-blast-the-bridge-with?" questions.

### 9.2 Smoke testing the daemon path

For an IMAP-based sensor, the standard smoke test is a synthetic
IMAP-APPEND of a known message and a journalctl tail:

```bash
# Terminal 1: tail logs
journalctl -u koi-sensor@<name> -f

# Terminal 2: append a synthetic message
python3 -c "
import imaplib, email.message
msg = email.message.EmailMessage()
msg['From'] = 'test@example.com'
msg['Subject'] = 'KOI smoke test'
msg.set_content('Smoke test body, at least 200 chars to pass the length filter ...')
imap = imaplib.IMAP4_SSL('imap.gmail.com')
imap.login('darrenainews@gmail.com', '<app-password>')
imap.append('KOI/Substack', '\\\\Seen', None, msg.as_bytes())
imap.logout()
"

# Terminal 3: query the DB after ~30s
psql -h localhost -p 5433 -U postgres -d eliza -c \
"SELECT rid, source, is_private, access_source FROM koi_memories
 WHERE rid LIKE 'orn:newsletter.%' ORDER BY created_at DESC LIMIT 1;"
```

For other sources, the analogue is "create a test item that matches one
of your routes, watch it land in `koi_memories`, verify columns".

### 9.3 The privacy verification protocol

Every privacy-touching change must verify both directions before
declaring success:

```bash
# 1. Unauth must NOT find a known-private phrase
curl -s -X POST https://regen.gaiaai.xyz/api/koi/query \
  -H "Content-Type: application/json" \
  -d '{"query": "<phrase only in your private content>", "limit": 5}' | jq '.results | length'
# expect: 0

# 2. Auth MUST find it
curl -s -X POST https://regen.gaiaai.xyz/api/koi/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "<phrase only in your private content>", "limit": 5}' | jq '.results | length'
# expect: > 0

# 3. /rid-lookup must agree
curl -s "https://regen.gaiaai.xyz/api/koi/rid-lookup?rid=<your-private-rid>" \
  | jq '.found'
# expect: false (unauth) / true (auth)
```

This is the pattern from the 2026-05-04 #23 Phase 2 verification — keep
it as your privacy regression test.

### 9.4 Verifying bundle metadata propagates

If your sensor sets a metadata field that needs to land on a
`koi_memories` column or in a downstream consumer, verify the field
survives `document_to_bundle`:

```bash
psql -h localhost -p 5433 -U postgres -d eliza -c \
"SELECT
   rid,
   metadata->>'<your-field>' AS your_field,
   is_private,
   access_source
 FROM koi_memories
 WHERE rid LIKE 'orn:<your-namespace>.%'
 ORDER BY created_at DESC LIMIT 5;"
```

If your field is **not** in the whitelist (Section 11), it will be
absent from `metadata` here. That's the bug signature.

---

## 10. Observability

### 10.1 Heartbeats

Every sensor should send:

- One heartbeat on startup, before entering the poll loop.
- A periodic heartbeat every 30 minutes, even when idle.

Heartbeats are bundles with `metadata.event_type = "HEARTBEAT"`. The
coordinator doesn't treat them specially, but the dashboard
(`regen.gaiaai.xyz/koi`) reads them to compute liveness. A sensor that
hasn't heartbeated in >2x its interval is shown as stale.

### 10.2 Log shape

Standard log line format (set by `_setup_logging`):

```
2026-05-05 08:14:22,123 - koi.sensor.newsletters - INFO - step: poll_once()
2026-05-05 08:14:25,456 - koi.sensor.newsletters - INFO - [KOI/Substack] poll: 3 new UIDs (since 12345, uidvalidity=5)
2026-05-05 08:14:26,789 - koi.sensor.newsletters - INFO - [KOI/Substack] 🔒 nate-jones-substack NEW: AI is going to be everywhere
```

Conventions:

- `step: <name>` for major lifecycle transitions. Helps you find
  where in the loop the sensor died.
- `[<context>]` prefix for per-source logs (folder name, repo name,
  workspace ID). Lets `grep` cleanly partition by source.
- 🔒 / 🌐 emoji for private / public emit log lines. Eyeball-fast cohort
  audit when you're scrolling.

Use `PYTHONUNBUFFERED=1` (set by `run-sensor.sh`) so logs reach journald
in real time, not on flush boundaries.

### 10.3 journalctl

```bash
# Live tail
journalctl -u koi-sensor@<name> -f

# Last 100 lines
journalctl -u koi-sensor@<name> -n 100 --no-pager

# Errors only, since boot
journalctl -u koi-sensor@<name> --since today --no-pager | grep -iE "error|exception|failed"

# Service status (uptime, restart count, last error)
sudo systemctl status koi-sensor@<name>
```

### 10.4 Coordinator queue health

```bash
curl -s http://localhost:8005/health | jq
```

Returns connected sensors, pending events, delivery stats. If your
sensor's events are queueing without being delivered to the bridge, this
shows you. If the bridge is dead, the queue grows; that's an upstream
issue, not a sensor issue.

### 10.5 Verifying ingest end-to-end

```bash
psql -h localhost -p 5433 -U postgres -d eliza -c \
"SELECT
   COUNT(*) FILTER (WHERE rid LIKE 'orn:<your-ns>.%') AS your_rows,
   COUNT(*) FILTER (WHERE rid LIKE 'orn:<your-ns>.%' AND created_at > NOW() - INTERVAL '1 hour') AS last_hour,
   COUNT(*) FILTER (WHERE rid LIKE 'orn:<your-ns>.%' AND is_private) AS private_rows
 FROM koi_memories;"
```

---

## 11. Common pitfalls

### 11.1 The `document_to_bundle` metadata whitelist

**What it is.** `koi_protocol/core/bundle_system.py:document_to_bundle()`
builds `bundle.manifest.metadata` as an explicit allow-list, NOT a
passthrough. As of `c3a8013` (2026-05-05), the whitelist is:

- Always: `source`, `source_type`, `collection_method`, `original_id`
- Conditional (URL): `url`, `source_url`
- Conditional (date): `published_at`, `published_confidence`,
  `last_modified`
- Conditional (code-graph): `file_path`, `repo`, `branch`, `commit_sha`,
  `commit_date`
- Conditional (privacy): `is_private`, `access_source`
- Conditional (cohort): `tags`, `ingest_method`

**The bug shape.** Your sensor sets `metadata.my_new_field = "foo"`. The
bridge reads `bundle.manifest.metadata['my_new_field']` and gets
`KeyError`. The data appears to "go missing" between sensor and DB, but
the sensor logs are clean and the document dict is correct — the field
is silently stripped at conversion time.

**The fix.** A 2-line edit to `document_to_bundle`:

```python
if "my_new_field" in doc_metadata:
    bundle_metadata["my_new_field"] = doc_metadata["my_new_field"]
```

**Why this exists.** Historical: the bundle metadata is wire-shipped
across federation peers, and the whitelist was intended as a
known-shape guarantee. In practice it bites every sensor author who
adds a new field. **Check the whitelist before adding new metadata
fields end-to-end.**

This was the root cause of the 2026-05-04 #23 Phase 1 false-positive:
synthetic POST direct to `/process-koi-event` worked because it skipped
`document_to_bundle`; real sensor flow failed silently. Fixed in
`c3a8013` for `is_private`/`access_source`. The pattern recurs.

### 11.2 KOI_ENVELOPE_SIGN must be `false` for direct invocations

Covered in [Section 7.4](#74-one-shot-script-invocations-the-koi_envelope_sign-gotcha).
Recap: `.env` says `true`; `run-sensor.sh` overrides to `false` for
local sensors; direct `python3 sensor.py` invocations skip the wrapper
and broadcasts fail with `No public key registered`.

**Symptom signature.** Many "skipped" log lines in a one-shot run with
no per-message reason logged. (Real route-mismatch skips DO log a
reason; signing failures do not.)

### 11.3 RID must be stable across runs

Covered in [Section 3.5](#35-rid-shape) and
[Section 8.4](#84-rid-stability-is-the-hidden-axis). If your RID
incorporates `now()`, `uuid4()`, or any per-run-changing input, every
poll re-emits the entire source.

### 11.4 `is_private` stickiness

The bridge ON CONFLICT clause is **sticky-OR**: once a row's column is
`TRUE`, re-emitting the same content with `is_private=False` will NOT
flip it back. This is intentional (you can't accidentally publicise a
private cohort by misconfiguring a route). But it means: if you
incorrectly set `is_private=True` on first emit, you must **either**
explicitly UPDATE the column, or accept the row stays private.

For the inverse, sensors that need to escalate a public row to private
just re-emit; sticky-OR makes that a one-way ratchet, which is what
you want.

### 11.5 Doc-shape bundles, not chunk-shape

The bridge does the chunking. Your sensor emits the **whole document**
content (subject + body, full page text, full file content) as
`document.content`. Don't pre-split into chunks; the bridge has its own
chunking strategy and pre-chunked content makes downstream chunking
non-deterministic.

A "doc-shape" bundle has one RID per logical document. A "chunk-shape"
bundle has multiple RIDs per document with `#chunkN` suffixes. **Sensors
must emit doc-shape.** The `#chunkN` rows in `koi_memories` come from
the v2 bridge, not from the sensor.

### 11.6 Don't ingest code as docs (the github sensor scope-creep)

The github sensor was found 2026-05-05 ingesting `.go`, `.ts`, `.tsx`,
`.py`, `.sh`, `.sql`, `.js` source files into `koi_memories` alongside
markdown. That's wrong: code goes to a separate code-graph pipeline
(`scripts/load_to_staging.py` → tree-sitter → Apache AGE / `regen_graph`).
Doc-shaped chunking + embeddings is for natural-language content only.

The fix: the github sensor's `file_extensions` is now a strict
allow-list (`*.md`, `*.MD`, `*.mdx`, `*.rst`, `*.txt`, `*.adoc`,
`*.asciidoc`, `README*`, `CHANGELOG*`, `CONTRIBUTING*`, `LICENSE*`,
`COPYRIGHT*`, `NOTICE*`, `AUTHORS*`, `CODE_OF_CONDUCT*`, `SECURITY*`).

**Generalised rule.** When walking files or items, **allow-list, don't
deny-list.** It's much easier to add `.adoc` later than to find and
purge 30,000 unintended-cohort rows.

### 11.7 PM2 caches deleted modules

Mostly bites the koi-processor side, but worth knowing if you're
restarting any service. PM2-managed long-running services keep imported
modules cached in memory even after the source files are deleted. The
process keeps working until restart, then crashes with
`Cannot find module`. If you delete or archive a sensor or shared
module, **restart the consuming service in the same change** — don't
let the cached version drift.

### 11.8 rsync-then-commit deploy sequencing

When deploying via the rsync-then-commit pattern (rsync new sensor
files to prod, commit upstream, `git pull` on prod), the prod working
tree may have BOTH untracked files (matching the new commit's added
files) AND modified files (matching the new commit's changes). A
naive scoped `git stash push -u -- <untracked-paths>` misses the
modified files; the pull fails; if you `git stash drop` thinking
success, the untracked files vanish.

Safer recipe:

```bash
# Verify md5 of all changed paths matches between local and prod first
md5sum scripts/run-sensor.sh sensors/<name>/*.py
# Then, if all match local:
git checkout -- scripts/run-sensor.sh        # reset modified
# Untracked files: pull will install them; don't stash
git pull origin main
```

If md5 doesn't match (prod has its own modifications), use unscoped
`git stash -u`, pull, then `git stash pop` — never `git stash drop`
without confirming pull succeeded.

### 11.9 docker container nginx is authoritative

Mostly for upstream services, but if your sensor exposes any HTTP
endpoint (most don't): the live nginx router on prod is the `nginx`
docker container, not systemd. Disk configs at `/etc/nginx/sites-*`
are dead since 2026-04-03. Check container config with:

```bash
docker exec nginx nginx -T 2>/dev/null | grep -nE "172.17.0.1:<port>|host.docker.internal:<port>"
```

before assuming a port is unrouted.

### 11.10 Heavy deps blow up the venv

Don't add `playwright`, `torch`, `tensorflow`, or any large native dep
to `requirements.txt` unless your sensor actively uses them. Each
sensor has its own venv; heavy deps multiply across sensors and have
caused disk-space issues. The newsletter sensor lists Playwright as
optional and only imports it inside the `--scrape-substack-archive`
mode behind a `try/except ImportError` guard.

---

## 12. Reference: existing sensors at a glance

This is a snapshot of the current sensor surface (2026-05-06). For the
authoritative production state, run:

```bash
ssh darren@202.61.196.119 "systemctl list-units --type=service --no-pager 'koi-sensor@*'"
```

| Sensor | Source | Add a source | Privacy posture | Notes |
|---|---|---|---|---|
| `newsletters` | Gmail-IMAP, paid Substack archive scrape | Append entry to `newsletters:` in `config.yaml`, restart | Per-route (default private) | THE current reference sensor. IMAP poller + `--ingest-mbox` + `--scrape-substack-archive` modes. |
| `notion` | Notion API | Add workspace to `workspaces:` in `config.yaml` (each has `enabled`, `workspace_id`, `api_key_env`, `is_private`, `access_source`) | Per-workspace | Most-mature multi-cohort sensor; PII filter; per-workspace privacy threading patched 2026-05-04 (`7b68ddb`). |
| `github` | git clone + file walk | Edit hardcoded repo list in `github_sensor.py:main()`. `config.yaml` is dead config (kept as documentation). | Public (docs only) | **STRICT ALLOW-LIST** of doc extensions only — see Section 11.6. Code goes to a separate pipeline. |
| `github_activity` | GitHub API (issues, PRs, comments) | Hardcoded repo list in source | Public | Activity feed only, not file content. |
| `discourse` | Discourse forum API (REST `/c/<id>.json` + topic pages) | Edit `self.forums` list in `discourse_sensor.py` (canonical entry-point per `scripts/run-sensor.sh:54`) | Public | Three `.py` files coexist; only `discourse_sensor.py` is wired into systemd — `_koi.py` and `_standalone.py` are old variants, leave alone. `forum.regen.network` active; `regencommons.discourse.group` deprecated. |
| `youtube` | YouTube Data API + remote Scribe transcription | Hardcoded channel list (`@RegenNetwork`, `@FirstPrinciplesAI`, `@regenfoundation`) in source | Public | Transcribes full videos via Scribe API. |
| `medium` | RSS + scrape fallback | Edit `medium_sources` list in `MediumMonitorConfig` | Public | Currently disabled (HTTP 403 + code bug); RSS-shape reference for new RSS sensors. |
| `websites` | Playwright | Add URL to `sites/` config files | Public | Heavy dep (chromium); use sparingly. |
| `telegram` | Telegram bot API | Bot must be added to channel; channel list in `.env` | Mixed | Real-time chat. |
| `discord` | Discord bot API | Channel list in config | Mixed | Real-time chat. |
| `twitter` | Playwright (anti-scraping) | `TWITTER_ACCOUNTS` env var | Public | Only `@regen_network` works reliably; others rate-limited. |
| `gitlab` | GitLab API | Currently disabled | — | No active sources. |
| `podcast` | RSS + transcription | Currently disabled | — | No active sources. |
| `claude_sessions` | Local JSONL files | Adds entity-extraction layer (calls personal-koi `/ingest`) — different from team-KOI flow | N/A | Personal-only sensor; reference for the entity-extraction pattern. |
| `ledger` | Cosmos LCD/RPC (regen-ledger) | Currently single-chain; multi-chain not built. RPC/REST endpoint fallbacks editable in `config.yaml`. | Public | On-chain data, not docs. Polls governance / ecocredit / consensus / stats on staggered intervals. |
| `email` | IMAP (Maildir + Proton) | **Personal-only — DO NOT use for team-KOI.** Runs via macOS launchd plist, not systemd. Two implementations: `email_sensor.py` (Maildir watch) + `proton_sensor.py` (Proton IMAP fetcher). | Personal | For team-KOI Gmail-IMAP, use `newsletters/` instead — that's the canonical paid-publication ingestion path. |
| `obsidian` | (none) | **Stub directory only** — `venv/` + `__pycache__/`, no sensor code. Personal-koi vault sync uses a separate path entirely. | N/A | Skip; not implemented. |
| `experimental` | — | Don't ship from here | — | Sandbox. |
| `rss` | Generic RSS fan-in | Append entry to `feeds:` in `config.yaml` | Per-route | Phase-1 implementation; 10 active feeds. |

**Anti-patterns to avoid (observed in older code):**

- The github sensor pre-`2026-05-05` walked code files. Don't do that —
  Section 11.6.
- Some older sensors (medium) embedded `MediumMonitorConfig` defaults
  inside the Python source rather than reading `config.yaml`. Newer
  sensors (newsletters, notion, rss) pull all config from yaml. Prefer
  yaml.
- **Custom RID subclasses** — only roll your own when no shared type
  fits. `shared/rid_types/` already covers five categories
  (`communication`, `dev_tools`, `productivity`, `social_media`,
  `web_content`); if your namespace lives in one, import the existing
  class for wire compatibility with downstream consumers (rid-lib,
  bridge, MCP). Subclass `RID` directly only for genuinely new
  namespaces (the `newsletters` sensor is a justified case — paid
  Substack didn't fit any existing type).
- The notion sensor has top-of-file `print("[STARTUP] ...")` debug
  scaffolding. It works but isn't a model — use `self.logger.info` from
  the start.

---

## 13. Adding to deployment

### 13.1 Branch and repo workflow

- **`koi-sensors`**: production tracks `main` directly. Cut feature
  branches if you want; merge to `main` to deploy.
- **`koi-processor`**: production tracks `regen-prod`, NOT `main`.
  Cherry-picks to `stable`. (You'll only touch this if you're adding
  new bridge-side metadata propagation, e.g., extending the
  `document_to_bundle` whitelist.)

### 13.2 Files to commit

- `sensors/<name>/<name>_sensor.py`
- `sensors/<name>/config.yaml`
- `sensors/<name>/requirements.txt`
- `sensors/<name>/setup.sh`
- `sensors/<name>/start.sh`
- `sensors/<name>/README.md` (1-pager: what the sensor does, who owns
  what, where secrets live)
- One-line addition to `scripts/run-sensor.sh` (case statement)

**Files to NOT commit:**

- `sensors/<name>/venv/` (gitignored)
- `sensors/<name>/<name>_sensor_state.json` (gitignored — runtime state)
- `sensors/<name>/__pycache__/` (gitignored)
- `.env` or any secret file
- `storage_state.json` / OAuth token JSON (treat as secrets)
- Per-sensor log files

`.gitignore` covers most of these. Double-check with `git status`
before committing.

### 13.3 Deploy sequence

```bash
# Local: commit and push
cd /Users/darrenzal/projects/RegenAI/koi-sensors
git status                          # eyeball
git add sensors/<name>/ scripts/run-sensor.sh
git commit -m "feat(<name>): initial sensor for <source>"
git push origin main

# Prod: pull, set up venv, ensure secrets, enable
ssh darren@202.61.196.119
cd /opt/projects/koi-sensors
git pull origin main                # (or follow Section 11.8 if dirty tree)
cd sensors/<name>/
./setup.sh                          # creates venv, installs requirements

# Add secrets to /opt/projects/koi-sensors/.env if needed
sudo vim /opt/projects/koi-sensors/.env
sudo chmod 600 /opt/projects/koi-sensors/.env

# Enable systemd
sudo systemctl daemon-reload         # only needed if template changed
sudo systemctl enable --now koi-sensor@<name>.service
journalctl -u koi-sensor@<name> -f   # watch first poll
```

### 13.4 Verification checklist

- [ ] `systemctl status koi-sensor@<name>` shows `active (running)` (no
      restart loop)
- [ ] `journalctl -u koi-sensor@<name> -n 50` shows startup heartbeat
      sent successfully
- [ ] First poll log line appears within `poll_interval` seconds
- [ ] At least one item appears in `koi_memories` for your namespace
      after a real ingestion event:
      ```bash
      psql ... -c "SELECT COUNT(*) FROM koi_memories WHERE rid LIKE 'orn:<your-ns>.%';"
      ```
- [ ] If private: `is_private=true` and `access_source='<expected>'`
      on every row
- [ ] If private: unauth `/api/koi/query` does NOT return your private
      content; auth does
- [ ] Heartbeats are landing in `koi_memories` (search for
      `metadata.event_type = 'HEARTBEAT'` AND `sensor_id = '<your-name>'`)

If any of these fail, don't `disable` the sensor in haste — read the
journalctl logs first and check Section 11 pitfalls.

---

## 14. When your data shape doesn't fit

Not every source maps cleanly onto the doc-shape pattern. Some escape
hatches:

### 14.1 Streaming / event sources (chat, websockets)

Use the chat-sensor pattern (telegram, discord). Long-lived websocket
connection; emit one bundle per message; aggregate or truncate as needed
to keep `content` under sane size. Polling cadence becomes idle keepalive
+ heartbeats only; the work happens in the websocket callback.

### 14.2 Binary / non-text content

If your source emits images, audio, or video, you have two choices:

- **Transcribe upstream**: convert to text in the sensor (or upstream).
  This is what the youtube sensor does — full video transcription via
  remote Scribe API, then doc-shape bundle.
- **Store metadata only**: emit a doc-shape bundle whose `content` is a
  textual description / metadata dump, and keep the binary externally.
  Suitable for "we want to know it exists, not full-text search it".

The bridge does NOT process binary content — `koi_memories` is a text
RAG corpus. If you need vector search over images/audio, that's a
separate pipeline (out of scope for this guide).

### 14.3 Per-item polling is too slow

If your source has thousands of items and you can't fetch them in one
poll cycle, paginate within the poll and use `state.metadata` for the
pagination cursor. The newsletter sensor does this with IMAP UIDs
(`max_uid` per-folder, per-uidvalidity). The notion sensor uses Notion's
cursor-based API.

### 14.4 The source has no API and no RSS

Two patterns:

- **Email forwarding**: many publishers have email subscriptions even
  without a web API. The newsletter sensor was originally an attempt at
  RSS for paid Substack and pivoted to Gmail-IMAP because Substack
  doesn't expose post-level private RSS.
- **Browser automation**: Playwright with persisted login storage_state.
  The newsletter sensor's `--scrape-substack-archive` mode is the
  reference. Heavy (chromium dep), brittle (CSS selectors break), but
  unblocks otherwise-unreachable sources.

### 14.5 Talk to the platform team

If the answer above isn't satisfying, surface it. The framework is still
small enough that adding a new core primitive (an
"emit-binary-bundle" path, a different bridge target, a richer event
type) is reasonable when motivated. Don't fork-and-paper-over; design
the new primitive deliberately.

---

## 15. Future: SDK direction

A `koi-sensor-sdk` Python package is under consideration. Recurring
boilerplate that would belong in the SDK:

- Sensor base class with `poll_loop`, `heartbeat`, `state` wired in
- Standard config loader (env-var expansion, route-list shape, secret
  reference resolution)
- Bundle helper that gates fields against the
  `document_to_bundle` whitelist with a clear error
- Pre-built CLI flag patterns (`--dry-run`, `--ingest-from`,
  `--cohort-filter`, `--max-items`)
- Test fixtures: synthetic-event emitter, in-memory coordinator stub
- Privacy-verification harness baked in

Goals:
- Sensor authors write only `def fetch_one_batch() -> list[Document]`
  and route config; the SDK handles the rest.
- The whitelist gotcha becomes a typed `BundleMetadata` schema
  with a clear error at definition time.
- Deployment becomes `pip install koi-sensor-sdk` + a manifest file
  rather than five boilerplate files.

This guide will be updated when the SDK ships. Until then, the
patterns above are the canonical interface.

---

## Appendix: file paths reference

Local development:

- Repo root: `/Users/darrenzal/projects/RegenAI/koi-sensors/`
- Sensors directory: `/Users/darrenzal/projects/RegenAI/koi-sensors/sensors/`
- Reference sensor (newsletters): `/Users/darrenzal/projects/RegenAI/koi-sensors/sensors/newsletters/newsletters_sensor.py`
- Wrapper script: `/Users/darrenzal/projects/RegenAI/koi-sensors/scripts/run-sensor.sh`
- Bundle conversion: `/Users/darrenzal/projects/RegenAI/koi-sensors/koi_protocol/core/bundle_system.py`
- KOI node base: `/Users/darrenzal/projects/RegenAI/koi-sensors/koi_protocol/nodes/koi_node.py`
- State management: `/Users/darrenzal/projects/RegenAI/koi-sensors/shared/persistent_state.py`
- RID base: `/Users/darrenzal/projects/RegenAI/koi-sensors/koi_protocol/core/rid_system.py`
- Shared RID types: `/Users/darrenzal/projects/RegenAI/koi-sensors/shared/rid_types/`

Production:

- Repo: `/opt/projects/koi-sensors/` (tracking `main`)
- Systemd template: `/etc/systemd/system/koi-sensor@.service`
- Per-sensor service: `koi-sensor@<name>.service`
- Logs: `journalctl -u koi-sensor@<name>`
- Coordinator: `http://localhost:8005` (health), `:8005/events/broadcast`
- v2 bridge: `http://localhost:8100` (event ingest)
- Team DB: `gaia-postgres-1`, port 5433, database `eliza`
- Search API: `http://localhost:8301` (koi-query-api.ts)
- nginx (live): `docker exec nginx nginx -T`

Bridge/processor side (relevant for understanding the consumer):

- `/opt/projects/koi-processor/src/core/koi_event_bridge_v2.py` —
  current production bridge (chunks, embeds, writes `koi_memories`
  rows, promotes `is_private`/`access_source` to columns, runs Pass-A
  entity extraction via `trigger_kg_extraction` → `PassAExtractor`)
- `/opt/projects/koi-processor/src/core/koi_event_bridge_semantic.py` —
  shawn's bridge. Unfed since the 2026-01-02 routing flip; v2 covers
  extraction now (see Section 2 historical incident).

---

*Last updated: 2026-05-06. Contributions welcome — open a PR against
`main`.*
