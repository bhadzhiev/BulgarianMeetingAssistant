# Manager task workflow

Meetings remain the source of notes. A proposed action is not yet an accepted commitment.

- Open **My Work → Tasks → Inbox** to review proposed meeting actions and source suggestions together: two queues, *From meetings* and *From connected sources*. Edit and accept, accept, link to an existing task, or skip.
- Use **New task** for work received outside an imported source. Manual tasks are accepted locally; no AI or external message is sent.
- Open a task title anywhere to edit the same task card: title, description, expected result, owner, state, project, dates and progress updates. Since 2026-11-12 the card does not show Received from, Assigned by, Followed by or the evidence of an update; their saved values stay unchanged.
- Set **This is me** to an existing People profile. **My tasks** uses a confirmed owner identity or a manually assigned matching name/alias. The **Assigned by me** view and the **Received from** / **Followed by** filters were removed on 2026-11-12, because nobody sets these roles. These roles do not mean the recipient has accepted externally.
- **Follow-up** shows active tasks with a due follow-up, an overdue deadline or Waiting state. Add a dated progress update to retain what changed.
- Local states: To do, In progress, Waiting, Done, Cancelled. Only accepted, non-cancelled tasks count as active commitments. Existing tasks retain their IDs, links and history and default to accepted locally without fabricated review receipts.
- **Create GitHub issue** opens the existing editable preview and explicit publication flow. Linking or publishing preserves the Atlanta task. GitHub state remains separate; closing an issue does not silently finish the local task.

All task edits use one revision-checked save. Conflicts retain the winning stored version; failed writes restore the in-memory snapshot. Project links are preserved unless explicitly changed. Local updates appear in history at their actual event time. Meeting confirmation becomes stale when either the task content or the source changes.

The task card shows saved sources and local history. It does not claim to import every remote GitHub comment or automatically notify owners.

## Stages 1 and 2

Task model version 1 adds an optional **Followed by** person independently of owner and assigner. Legacy open/done tasks migrate without moving into Inbox. Existing AI tasks without review receipts get an explicit legacy badge and can be reviewed gradually. Archive/Restore includes standalone user tasks and preserves manager fields, IDs and history.

Select transcript segments and choose **Task from selection**. The same source editor handles Gmail, Chat, GitHub and repository findings, and **New task → Draft with AI** handles free text. Generation is optional and uses the explicit source/provider preview. It suggests title, context and expected result; owner, requester and due date are entered by a person. Cancel returns to the original quick-capture form. No task is created until confirmation.

**Create or link** can add the saved evidence to an existing accepted task while preserving its wording, owner, projects and state. Meeting proposals can use **Link to existing task**; the old proposal remains as dismissed history and only the target counts as active work. Source, evidence, task fields, routing and the retry receipt commit together. Repeating the same capture returns the same ID; changing an uncertain request is refused.

The first notes produced for the meeting being viewed open **Tasks & decisions**, provided the user has no unsaved edits and is still on Transcript. Explicitly selected other tabs are preserved.

## Stage 3: managing the list

Accepted task rows show requester, assigner, latest explicit progress update, and direct owner/state/due/follow-up controls. A field change confirms the human's choice and uses the existing revision check. **Add update** opens the same card focused on the update field.

Project, owner, requester, follower, source, workflow and status filters are retained on this Mac. Choosing **New task in this project** prefills the actual project workspace, independently of the My Work filter.

Select up to 100 accepted visible tasks. Bulk actions allow owner, state and dates, with the count, selected titles and action shown before confirmation. Filtering removes hidden rows from the selection. The server validates the whole selection and saves once: a stale or invalid member rejects all changes. An uncertain response can retry exactly the same approved operation. No external message or GitHub write occurs.

## Stages 4 and 5: development and GitHub

The task card merges local history, evidence, GitHub link observations and publication states into **Task timeline**. Action timestamps stay separate from the source meeting date; older evidence without an attachment timestamp is undated. Progress notes can refer to a quote already linked to the task. **Link another source** starts a visible evidence-linking context and reuses the existing source editor without creating another active task.

Prepare me adds local updates, waiting tasks, due follow-ups and cached GitHub activity since the previous meeting, with an owner filter. A written progress update counts as activity even if no field changed. External snapshots never mark local work done or reopen it automatically.

**Check GitHub activity** explicitly reads the linked issue/PR and up to two pages of its [GitHub timeline](https://docs.github.com/en/rest/issues/timeline). **Load next activity pages** continues a partial read. Up to 300 event excerpts per link are retained (1500 characters per excerpt); incomplete coverage and omitted older events are marked. These are snapshots, not a complete audit log. Account switches, offline failures and link removal cannot replace unrelated snapshots or resurrect a deleted link. Cache clearing affects only remote activity excerpts.

Repository readiness verifies read access, repository identity and whether Issues are enabled. It does not claim to prove token Issues write permission from repository push access; that is checked by GitHub only after explicit publication approval. Existing preview, editable drafts, Copy Markdown and durable operation markers remain in use. Unknown publication outcomes can be found and checked from the task card after restart; there is no automatic POST retry. An issue closing or reopening offers a local review action, never an automatic status rewrite.

Manual task capture and evidence linking work with AI disabled or unconfigured. Only **Generate draft** requires a valid AI provider; no worker starts without it.
