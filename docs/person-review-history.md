# Reviews start with a person

Team → select a member’s name, or Reviews → choose a person. The person’s page shows open agreements from every earlier review, including help promised by the manager, followed by the review history. Each timeline card shows up to three recorded completions, checked results or overdue events from its period, plus its saved agreements. Newest first is the default; Oldest first reverses it. A correction and its earlier versions are grouped under one review. A correction draft stays there; Continue preparation opens it. The profile stays in People, accessible from the history. The manager can select their own existing People identity without joining their own team. The all-reviews archive remains available below.

History links use `?view=team&person=<person-id>`. Review links also keep the person. Back from a review opens that person’s history. Renaming or leaving the team does not change the person’s stable identity or remove reviews.

## Preparation and the conversation

Finalize fixes the review preparation. It does not claim that a conversation happened. Record the actual date under Conversation; it can be corrected or cleared independently. Existing finalized reviews have an unknown conversation date until a person records it. Dates entered here use Europe/Sofia.

A review shows the last review’s agreements and any unresolved agreements from earlier conversations. Each agreement keeps its own identity and origin. Save states on the previous review, or open the originating review for details. An agreement does not disappear because an intermediate review recorded none.

Coverage, task counts and GitHub details are collapsed in reading mode. Edit text still opens the complete Markdown. Refresh facts opens a proposed replacement alongside the current text. Nothing is replaced until Replace review text with these facts. The server rejects a proposal if the review or sources changed. Applying replaces the review text, including manually edited text and previous AI/GitHub sections; conversation notes, agreements and private context remain. The old collect API remains for compatibility.

## Agreements and checked results

Each action or goal has an owner (the person, me, both), a due/check date, an expected result, a state and optional evidence of a result check. I checked this result requires the expected result and the evidence. The server records when the manager saved that check and the configured manager name. This is a recorded human check, not an automatic test of whether a linked URL proves completion. Changes retain their append-only agreement history.

Save an agreement before Make a task. Creating its task stores the task ID on the same agreement; Open linked task then replaces Make a task. The expected result is carried into the task editor. If linking fails after task creation, the UI reports that the task already exists. No automatic second task is created.

Only commitments taken on within the analysed interval count as newly taken on. Earlier promises appear as carried context with their original source. Future promises do not count. Old closed work without activity or a result check in the period is omitted. A progress update with a link is not a confirmed result. Result confirmed counts require an explicit agreement check linked to the task, at or after completion and inside the period. Task completion and result acceptance remain separate.

Overlapping finalized periods are visible in history and in the review. Finalizing requires a separate acknowledgment of the overlap. Correcting a review does not overlap with the version it replaces. Historical records are never automatically rewritten. Comparison durations show hours/minutes for partial days, rather than zero days.

## Private context and additional data

Private preparation context holds role/expectations, the person’s view as recorded by the manager, manager support/dependencies, and the development focus. Role and focus carry to the next preparation; the person’s current view and AI permission do not carry automatically.

Choose observations from meetings offers only current, saved Team analysis observations in the period, with a timestamp that resolves in the transcript and an unambiguous confirmed person name. The manager’s own page offers their coaching observations. Select at most 20. These are AI interpretations, not confirmed facts. Selected snapshots retain their wording and source; if the transcript changes or disappears, a warning appears instead of silently rewriting the snapshot.

Context is excluded from AI by default. Include this private context in the next AI preview is an explicit choice, saved with the draft. Prepare with AI then shows the exact records and destination and requires the existing approval. The instructions treat recorded views and earlier AI interpretations as perspectives for neutral questions, not findings. The resulting private preparation and its evidence appear separately in the review. They never replace the normal review text and never enter its Markdown export. Context and private preparation are excluded from meeting notes, search and follow-up emails. Backups preserve both.

No new external source is fetched automatically. GitHub keeps its existing repository-selection step. Operational/support work can be recorded through agreements, linked tasks and context; this change adds no helpdesk connector.

## Storage and compatibility

Existing review files remain valid. Optional `review-context.json` and `private-preparation.md` are created only when used. Conversation date is an optional metadata field. New versions preserve conversation notes, date, agreements and private context. Agreement check fields and histories default to absent on old records. Backup/restore accepts the new optional files. Fixed review text stays fixed; fact corrections to finalized reviews use a new version.
