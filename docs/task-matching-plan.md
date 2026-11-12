# Task matching: technical plan

**Status: off by default since 2026-11-12.** The AI stops at the meeting notes; the person makes tasks by hand. Settings → AI → *Let AI propose tasks from meeting notes* turns this plan's features on again.

**Earlier status: draft.** This plan answers §11 of the brief "Контекстно разпознаване на задачи — задание за реализация, v2" (8 November 2026). It records the decisions so far and the limits.

## Decisions so far

| Decision | Source |
| --- | --- |
| "Same task" links the meeting as evidence only. A field changes only when a person checks it. | PR 1 (#154) |
| Meeting proposals go into the existing proposals (`app/work_graph.py`) and the one Inbox queue (My Work → Tasks → Inbox). | Brief §1 |
| The AI receives only **accepted, visible, open** tasks, plus accepted tasks closed in the last 14 days. Proposed (not accepted) and hidden (dismissed) tasks never go to the AI. | Decision of 8 November 2026 |
| The local sieve still compares with proposed tasks, so a repeated pending task does not become a second proposal. This costs no tokens. | Same decision |
| Automatic notes and a remote API: the extra task context waits for approval, or a standing permission in Settings. | Open: product decision (brief remark 4) |

## What exists today

| Part | Where | Reuse |
| --- | --- | --- |
| Notes extraction, stage `meeting_minutes` (and `meeting_consolidation` for long meetings) | `meeting_assistant.py` `minutes_schema` (line 323), `app/prompts.py` | Extend the schema (PR 2) |
| Text similarity, threshold 0.55, top 3 | `app/items.py` `similarity`, `Registry.candidates` | The local sieve (PR 3) |
| Old link review of meetings | `app/service.py` `pending_links`, `resolve_link`; `web/app.js` `linkCard` | Replaced by proposals (PR 4) |
| Proposals of Gmail, Chat and GitHub: one revision + all proposals commit together; review with revision checks; `link` adds evidence only | `app/work_graph.py` `ingest`, `review`, `ai_consent` | Meetings become one more source (PR 4) |
| Progress updates: `update_note` → `progress_update` history event | `app/service.py` `update_item` | Accepted updates (PR 4) |
| Job states | `app/job_registry.py`, `/api/jobs` (D04) | Add the matching step (PR 3) |

## Limits (first version)

| Limit | Value |
| --- | --- |
| Candidates per mention | 8 |
| Unique candidates per meeting (a candidate for several mentions goes once) | 30 |
| Candidate title | 200 characters |
| Description or expected result | 300 characters |
| Updates per candidate | 2, each 200 characters, with date and origin |
| Total extra input per meeting | about 6 000 tokens |
| Recently closed | accepted tasks closed in the last 14 days, before the meeting cutoff |
| No candidate above the threshold | no matching request |

A limit never cuts a quote of the meeting. When the total is over the limit, the lowest scored candidates go first.

Estimate: one candidate is about 120–150 tokens. The meeting cap gives about 4 500 tokens. A one-hour transcript is about 15 000–25 000 tokens, so matching adds about 20–30 % to a notes run.

## Order of work

1. **PR 1 (#154):** no silent overwrite, field choice, revision check, honest wording.
2. **PR 2, extraction:**
   - Add a `quote` to each task, decision and question in `minutes_schema`.
   - Add a list `updates` with `text`, `quote` and `evidence_timestamp`.
   - Validate each quote against the transcript.
   - Keep the edited prompt layers of `meeting_minutes` working.
   - Keep old notes readable without the new fields.
3. **PR 3, sieve and AI matching:**
   - Candidate selection: score, project, owner, accepted and visible only, the time cutoff.
   - The limits above.
   - A new prompt stage `task_matching` with a strict JSON schema.
   - A check of every returned ID against the candidates that were sent.
   - The consent snapshot (target, transcript revision, candidate set).
   - A step in the D04 job.
4. **PR 4, proposals and review:**
   - Meeting mentions become proposals in `work_graph`.
   - The old link review goes; its pending links become proposals.
   - The proposal types are `new_task`, `existing_mention`, `existing_update`, `proposed_change` and `uncertain`.
   - One checked, idempotent operation applies the evidence, the update and the chosen fields.
   - A labelled synthetic test set.

## Time rules

- **Cutoff:** the end of the meeting (start + duration) when known, else the end of the meeting day in Europe/Sofia.
- **Candidates:** `created <= cutoff`. A task that was entered later is not a candidate. This is a known limit.
- **State at the cutoff:** replay the history up to the cutoff. History keeps the time of the record, not of the event. The prompt says "state as recorded" and marks a value that it cannot rebuild as "current".
- **Notes:** candidate text never becomes a fact of the meeting.

## Quality check

The synthetic set has these cases:
- the same task in other words;
- a new update;
- different tasks with close titles;
- other projects or periods;
- a changed owner;
- a closed task;
- a task that was entered late;
- a target that was edited after the proposal.

Measure apart:
1. Is the right task in the top 8 (the sieve)?
2. Is the match right (the AI)?
3. Is the proposal type right?

## Status after PR 4

Done:
- PR 1 (#154), PR 2 (#156) and PR 3 (#157) are merged.
- In PR 4, meeting tasks and updates become proposals in the Inbox.

Known limits of the first version:
- **Decisions** keep the old link review. Task matching covers tasks and updates only.
- **Regenerated notes** (`minutes.proposed.json`) get AI proposals at the next processing run after they are applied. Until then, the local text similarity still makes proposals.
- **Automatic updates of the speaker's own tasks** (decision of 9 November 2026). The open tasks of the speaker of a
  mention are always candidates. An `existing_update` about an open, accepted task that the speaker owns or works on is
  added to that task at once when the AI gives `confidence: high`, as an update by AI with the meeting, the time and the quote. The task timeline has
  **Remove this update**. Every other answer still waits for a person in the Inbox. An unknown speaker adds nothing.
