# Page, property and comment reconciliation

The sensor polls known database pages and explicitly monitored pages. Page bodies,
properties and comments are separate observations; a comment is never appended to
page content or marked as an adopted decision.

## Notion access and coverage

The integration needs **Read content** and **Read comments**, plus access to the
relevant pages. Notion disables comment capabilities by default. The comments API
returns **unresolved comments only**, with pagination; it cannot provide a complete
historical archive or tell this sensor whether an absent comment was resolved,
deleted, moved, or became inaccessible. Enabling the capability is an operator
configuration action, separate from this code change.

The sensor requests comments for the page and for discovered visible blocks,
including nested blocks. Child-page/database references are separate source
boundaries, excluded from the ancestor’s comment targets and counted in
`child_references_excluded`. A child page must be independently monitored/discovered
to ingest its discussion. Configured `skip_pages` and `skip_sections` exclusions
apply before descendant traversal. A heading inside an excluded subtree cannot
reopen that section. Signed comment attachments, avatars and raw user objects are
not emitted. Rich text includes `plain_text` for mentions, subject to the existing
configurable PII filter. Attribution retains user IDs and filtered display names.

Page metadata contains `comment_coverage`: the `unresolved_comments_only` scope,
`resolved_history_available: false`, targets total/checked, and any HTTP or
incomplete-read errors. `complete` means this visit read every discovered visible
comment target successfully within the configured budgets; it does **not** mean
resolved history or unshared content is covered. Partial/budget-limited visits
remain explicitly `partial`. No absence or access error produces a `FORGET` event.

A failed body or paginated property read does not replace the previous complete
page snapshot. A failed comment read can still accompany a current page snapshot
with partial comment coverage. Pending comments from failed, skipped, or empty
comment targets stay queued and are withheld until positively observed again.
Archived/inaccessible pages also withhold pending delivery. This does not retract
records already delivered downstream; retention/access revocation there remains a
separate responsibility.

The API version remains `2022-06-28`; database-to-data-source migration is outside
this patch. Relation values reflect what the integration can see; referenced
pages are not fetched to infer ownership or governance state.

Primary API references:

- [Retrieve comments](https://developers.notion.com/reference/list-comments)
- [Comment object](https://developers.notion.com/reference/comment-object)
- [Page property values and pagination](https://developers.notion.com/reference/page-property-values)
- [Retrieve page property item](https://developers.notion.com/reference/retrieve-a-page-property)
- [Integration capabilities](https://developers.notion.com/reference/capabilities)

## Records and change detection

Existing page RIDs are preserved. The KOI node profile advertises the additional
`orn:notion.comment` event namespace. Each comment gets its own stable RID:

```text
orn:notion.comment:<workspace_id>/<comment_id>
```

Comment metadata includes `record_kind: comment`, comment/discussion IDs, parent
page/block ID, page/source URL, created/edited timestamps, attribution,
`is_private`, and `access_source`. Block links use the parent page URL with a block
fragment; they are source links, not invented direct comment permalinks. Comment
text is explicitly labelled as discussion, separate from page content. The
sensor supplies no ratification, acceptance, or decision status.

Page properties now include status names, people (IDs and available filtered
names), and relation page IDs. People/relation values that may be truncated are
hydrated through the paginated property endpoint. Contact fields remain omitted;
textual property names/values use the existing PII filter. IDs are preserved as
identifiers, not processed as phone numbers.

The change digest covers filtered title, content and metadata. Property-only
changes therefore emit updates even with an identical page body. Comment polling
does not depend on the page's `last_edited_time` or body digest. A comment edit
updates that comment RID; repeated identical observations do not emit again.
Comment coverage changes can update the page metadata independently of its body.

## Bounded polling and delivery

- `max_pages_per_poll` defaults to 25. A persisted fair page-ID queue rotates over
  all known configured sources, including between database discovery intervals.
  Fresh metadata is fetched for selected pages when discovery is not due. Queue
  state survives process restart; database edit filters do not gate comments.
- `max_comment_targets` defaults to 100 (minimum 2). Each page visit reads page
  comments plus a rotating subset of block targets. The block offset persists.
- Each API list is limited to 100 response pages. Block discovery has a budget of
  100 child-list traversals and a maximum depth of 50. Invalid/repeated cursors,
  API incomplete results, and exhausted budgets fail explicitly rather than
  masquerading as an empty or complete list. A page exceeding the block/list
  budgets stays incomplete; its block traversal does not resume across visits.
- List/page requests are paced at 0.35 seconds and the session has a 30-second
  request timeout. Failed sources, including HTTP 429, are retried on later
  reconciliation visits, not in an immediate retry loop. These budgets limit
  individual work units, not total cycle duration; large workspaces take multiple
  cycles. Workspace discovery itself retains the existing startup search path.
- Successful filtered video transcripts are reused for unchanged block versions
  in a workspace cache limited to 256 entries. Source edits refresh the cache;
  failures are retried. Signed file URLs are not stored in the cache.

The existing sensor state file stores a workspace-partitioned outbox and
acknowledged digests. It checkpoints the outbox before coordinator delivery and
saves acknowledgement immediately after a successful return from the existing
KOI node. A non-success/exception retains the payload for a later **fresh source
observation**. If the source reverts to an acknowledged revision, a superseded
failed update is discarded. Pending updates coalesce to the latest observed
revision; this is not an immutable change-history archive or exactly-once queue.
Normal writable state storage is required. The state file remains a single-writer
resource; namespaces do not add concurrent multi-process file locking.

## Verification

Synthetic fixtures exercise the Notion HTTP pagination/permission paths and the
real KOI node's failed HTTP delivery path. They use no workspace tokens, live
coordinator, model download, or production state. A comment event and bundle also round-trip through the local
persistent cache; this does not verify live coordinator retrieval or ACL enforcement:

```bash
.venv/bin/python -m pytest tests/test_notion_polling.py tests/test_koi_protocol_alignment_p0.py tests/test_rid_lib_migration.py -q
```

Install the existing runtime dependencies and `requirements-dev.txt` into an
isolated virtual environment. These tests verify sensor behavior; they do not
establish production comment capability, downstream indexing, or team write-back.
