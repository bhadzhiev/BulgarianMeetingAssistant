# Work assistant: initial contract

Scope: one person, one local library, Google Workspace. Gmail is the first external connector,
followed by Google Chat, GitHub, repository analysis and confirmed external actions.

## First delivery

This change establishes transactional storage for existing tasks and decisions, item revisions,
stable meeting-note evidence snapshots and a meeting-based My Work view. It preserves existing
meeting extraction and review behavior. It does not implement Gmail, Chat, GitHub, canonical
questions or a standalone AI proposal engine. Those are separate deliveries below.

## Objects

| Object | Contract | Initial implementation |
| --- | --- | --- |
| WorkItem | Stable ID; typed state; field authority; revision; personal disposition | Existing tasks and decisions, with unchanged IDs |
| SourceLink | Provider + account + external ID; availability distinct from item state | Local meeting links; existing meeting_id remains compatible |
| Evidence | Quote kind, locator and pinned revision; historical content stays separate from current state | Immutable meeting-note mention snapshots; explicitly not verbatim transcript quotes |
| Proposal | Suggested change/link; evidence; Accept, Link, Dismiss, Snooze | Existing meeting link review stays; standalone proposal storage is next |
| Relationship | same_as, derives_from, implements, supersedes, supports | Existing merge/replacement behavior; typed general relations are next |
| Activity | Actor, event, before/after, source, time | Existing history retained |

Task states remain open/done. Decision states remain proposed/accepted/superseded. Questions need
their own lifecycle in the next schema; a decision and the tasks that implement it stay separate.
Deleting a replacement restores the previous decision's actual prior state, never an assumed acceptance.

## Field authority

- Local status changes belong to the person. AI can suggest, and must not complete tasks.
- Explicit human edits protect text, owner and dates from later AI updates.
- Current meeting behavior may fill unedited task fields when the person chooses Same task.
- Gmail and Chat commitments will enter through proposals, not direct canonical mutations.
- GitHub controls remote issue/PR state. Internal priority/disposition stays local. A primary binding
  and completion policy must be explicit before mapping remote state to a WorkItem's state.
- Identities use provider/account identifiers. Similar names are not proof of the same person.

## Storage and migration

`work-items.sqlite3` is canonical. Schema version 1 stores the task/decision documents and monotonic
item revisions in transactions. `items.json` is a generated, portable compatibility export, not another
editable source of truth. The original import is retained as `items.before-sqlite.json`.

Migration validates every imported item, keeps IDs/history/manual fields, and commits the whole
registry or none of it. Malformed legacy input is never replaced by an empty registry. A stale export
after a crash is rebuilt from SQLite. Edits to a current export are rejected rather than silently lost.
Older binaries and out-of-band edits to items.json are unsupported after migration.

Item writes through HTTP require the revision the person saw. Both revisions are required for a merge.
Deletion leaves a revision counter so restoring an item cannot reuse an older revision token.
The existing meeting JSON/Markdown files remain supported. This is not yet a transaction spanning
every meeting file and the database; connector ingestion must wait for the source/proposal transaction
API described in WA-004. The current registry adapter still reads/writes a registry batch.

## Evidence and personal disposition

Initial evidence is a snapshot of a meeting note, with a content-derived revision and meeting timestamp.
It must be labelled meeting_note / mention_snapshot. It does not pin or verify the full transcript.
Transcript segments, email messages, Chat messages and code references need their own version rules
before those source types are enabled. Code references must include repository, commit, path and range.

Dismiss and Snooze affect only My Work visibility and counts. They do not change task/decision state,
delete source data, complete an external issue or send a message. All/Snoozed/Dismissed filters make
the items reachable. The project filter follows the meetings that link to an item.

## Backup and concurrency

The service pins file versions under short service/registry/project/library locks, then releases them
before compression and verification. Active recordings, processing jobs and live-caption writers are
excluded and listed. App metadata writes use atomic replacement; completed audio is immutable.
Snapshot pinning requires hard-link support on the library filesystem. External in-place filesystem
edits are outside this guarantee. Restore extraction/checksums happen outside the lock; publishing
restored meetings and merging their metadata use the same lock order.

Portable archives use items.json, including revisions, evidence, history and personal disposition;
they do not copy a live SQLite/WAL file. Restoring adds only missing meetings and their eligible items,
and keeps existing items authoritative. Future database entities must have a versioned portable export
and restore contract before being used.

## Connector boundaries

New integrations start read-only, with selected accounts/sources and bounded initial sync. Calendar's
existing explicit event-writing feature remains separate. Tokens stay in Keychain. A shared Google
connection must track capabilities for Calendar, Gmail and Chat independently.

Source content is untrusted data. Read permission does not authorize exporting it to AI. New source
types default to no cloud/API export until explicit per-source consent; a configured API endpoint can
itself be remote. Recording has highest priority; sync/index/extraction jobs must be bounded,
cancellable and resumable. Search indexes and derived caches must be rebuildable.

## Delivery tasks and acceptance

- WA-001: Preserve prior decision state; reject stale item updates/deletes/merges; test unchanged-text conflicts.
- WA-002: Pin backup versions; test concurrent metadata changes, concurrent archive names and restore round trips.
- WA-003: Migrate registry to SQLite; retain IDs/manual fields/history; test interrupted exports, bad input, stale writers and restored revisions.
- WA-004: Add Source/Evidence/Proposal/Relationship transaction APIs and canonical questions. Require immutable source revisions, idempotent ingestion and no partial canonical updates.
- WA-005: Add My Work project filters and reversible personal Snooze/Dismiss; keep sources and canonical status intact.
- WA-006: Add standalone proposal Accept/Link/Dismiss/Snooze and content-version conflict checks; test dedup across reprocessing and restart.
- WA-007: Gmail Workspace capability spike, then bounded Inbox/Sent sync and Needs reply/Waiting for/Suggested. No writes; verify capability and AI-export boundaries first.
- WA-008: Chat, GitHub, repository index, then previewed and confirmed external actions, each as a separate connector delivery.

The current PR targets WA-001/002/003/005. WA-004/006 complete the general model before Gmail ingestion.
Physical iPhone recovery and speech throughput measurements remain manual validation work; passing
synthetic tests does not complete those checks. No blocking product-scope questions remain for this slice.
