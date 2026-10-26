# Work assistant: initial contract

Scope: one person, one local library, Google Workspace. Gmail is the first external connector,
followed by Google Chat, GitHub, repository analysis and confirmed external actions.

## Deliveries

This change establishes transactional storage for existing tasks and decisions, item revisions,
stable meeting-note evidence snapshots and a meeting-based My Work view. It preserves existing
meeting extraction and review behavior. It does not implement Gmail, Chat, GitHub, canonical
questions or a standalone AI proposal engine in the first delivery.

Part 2 adds canonical questions and local Source/Evidence/Proposal/Relationship APIs. Content
revision, evidence, proposal and accepted item changes commit in the same SQLite transaction.
The Suggested and Questions sections expose review and answers; external connectors remain disabled.

## Objects

| Object | Contract | Current implementation |
| --- | --- | --- |
| WorkItem | Stable ID; typed state; field authority; revision; personal disposition | Existing tasks/decisions with unchanged IDs; manual/proposed questions |
| SourceLink | Provider + account + external ID; availability distinct from item state | Meeting links stay compatible; generic sources use stable provider/account/external ID |
| Evidence | Quote kind, locator and pinned revision; historical content stays separate from current state | Meeting-note snapshots plus exact quotes tied to immutable generic content revisions |
| Proposal | Suggested change/link; evidence; Accept, Link, Dismiss, Snooze | Standalone local proposals with revision-checked Accept/Link/Dismiss/Snooze |
| Relationship | same_as, derives_from, implements, supersedes, supports | Typed local relation API; existing meeting replacement stays separate |
| Activity | Actor, event, before/after, source, time | Existing history plus proposal/question/relationship activity retained |

Task states remain open/done. Decision states remain proposed/accepted/superseded. Questions use open/answered and require an answer before becoming answered; a decision and the tasks that implement it stay separate.
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

`work-items.sqlite3` is canonical. Schema version 2 stores graph records alongside the task/decision/question documents and monotonic
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

Part 1 delivered WA-001/002/003/005. Part 2 implements the local WA-004/006 foundation before Gmail ingestion.

### Part 2 API and boundaries

Authenticated local POST routes under `/api/work/` implement `ingest`, `review`, `question`,
`relate` and `availability`. They never call an AI endpoint or an external service. `ingest` accepts
one source revision and at most 100 proposals; invalid later evidence rolls back the entire batch.
Source identity is provider/account/external_id; content versions are immutable. Reusing an external
revision token with different content is rejected, as is replaying an older known version as current.
Unknown revision ordering remains the future connector's responsibility. Quotes must occur in the
pinned content. Locators are stored as data; they are not executed or opened automatically.

Proposal identity hashes evidence/kind/text. Exact retries keep review state across restart; this is
not fuzzy semantic deduplication. A newer source revision marks old pending proposals stale. Accept
creates an open task/question or proposed decision. Link requires the current target item revision,
adds evidence only and never updates owner, text or status. Proposal review also requires its own
revision. Availability affects review, not the linked item's business status.

Relationships support same_as/derives_from/implements/supersedes/supports; same_as is symmetric,
and directed relationships reject cycles of their own type. These are explicit metadata links,
not automatic merge, completion or decision-state commands. A full relation editor is a follow-up.
The existing meeting replacement operation remains responsible for decision state.

Questions are added manually or accepted as proposals. Answer/reopen uses item revisions; the
previous answer remains in history. Automatic promotion of meeting open_questions is deliberately
not enabled. General-source questions and proposals are global and independent of the meeting
project filter. Source-linked items cannot be destructively deleted/merged through legacy controls;
Dismiss keeps their history and IDs. New source records default to ai_export_allowed=false; there
was no route in Part 2 to authorize AI export; selected-message approval is added below.

Portable export version 3 contains every graph collection. Restore validates graph content before
publishing meetings and commits its registry/graph merge together, preserving local records on ID
conflict. Like the previous delivery it is not a crash-atomic transaction across meeting files and
SQLite. Content and historical revisions are retained locally and inside archives; automatic
retention/purge controls and large-account ingestion performance remain later connector work.
Physical iPhone recovery and speech throughput measurements remain manual validation work; passing
synthetic tests does not complete those checks. No blocking product-scope questions remain for this slice.


## Gmail pilot (WA-007 first delivery)

A shared PKCE/Keychain account tracks Calendar and Gmail grants independently. Gmail uses only
`gmail.readonly`; existing Calendar grants are explicitly included in the next consent request.
The desktop flow does not support incremental authorization, per
[Google's native app guide](https://developers.google.com/identity/protocols/oauth2/native-app).
No actual account is connected during automated development checks.

Manual sync uses a separate indexed SQLite cache and durable per-account queues. Initial sync reads
at most 200 matching threads in a fixed 30-day window, in pages of 20. History refresh preserves the
old cursor until every referenced thread is handled; HTTP 404 resets to a bounded rebuild, following
[Google's sync contract](https://developers.google.com/workspace/gmail/api/guides/sync). There is one
worker, no automatic sync and recording/processing takes priority. Full selected thread text is read
within local body/response/count limits; attachments are excluded. The cache is rebuildable, excluded
from archives and can be cleared independently. Promoted source snapshots remain in graph archives.

Needs reply/Waiting for are last-message direction heuristics. Message-to-task proposals are manual,
with pinned quotes and existing Accept/Link review. The first pilot did not include AI extraction;
selected-message extraction is described below. Draft, send, label and mailbox modification remain unsupported. Existing promoted sources are
refreshed before a cache page is committed, so interruption retries are safe across the two stores.
Unknown provider ordering, live mailbox validation, retention policy, Workspace deployment consent
and automatic extraction remain explicit follow-ups. The Gmail permission itself is restricted; see
[Google's scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes).


## Selected-message Gmail AI extraction

`/api/gmail/ai/preview` computes a token from the account, pinned thread revision, selected message,
extractor version and complete configured endpoint/model/format/token/reasoning settings. It makes
no AI request and writes no consent. `/start` requires explicit boolean approval and the matching
preview token. `/cancel` cancels the owned client worker. General read-only Gmail access and meeting
AI settings never grant blanket permission to analyze email.

Consent is scoped to one runtime job, message, source revision and target settings. Same-revision
source ingestion preserves an active consent, while changed/unavailable source ingestion revokes it.
Account, endpoint/settings and recording/processing changes invalidate the job. Restart/restore
revokes persisted grants, and no interrupted AI export resumes. The source flag alone cannot start
a job. Cache lookup binds the expected account before returning message content.

The isolated worker uses the existing private pipe/guardian lifecycle. It has no tools, passes email
as untrusted JSON data and sends only the selected body and sender/subject/ID, limited to 20,000
characters. Parsing and source validation reject invented quotes and unquoted owner/date fields.
Relative dates stay literal; canonical due_date requires an exact ISO date in the evidence. Up to 20
task proposals are published; no item status or external system can change without review.

Proposals include optional quoted fields. Accept copies them into a new open task; Link preserves
existing fields/status. Proposals, completed-extraction activity and consumed consent share one
SQLite commit. Exact same-input/settings/version retries reuse the completed proposal IDs and their
review states; this is not semantic deduplication or a guarantee about unchanged server model weights.
Any result with invalid evidence fails as a batch. Truncation produces a settings/input-limit error,
not partial proposals or automatic recursive requests. Repeated analyses with changed wording still
need human Link review. The source snapshot/replay metadata remains in portable export version 3.

No real email or external model was used in development validation. Remaining manual checks include
Workspace consent, real Gmail sync and extraction precision on consented reference messages. No
bulk/background AI, cloud fallback, email writes or guessed normalized relative dates are enabled.
