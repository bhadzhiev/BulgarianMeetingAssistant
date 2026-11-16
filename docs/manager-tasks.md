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

Every new task uses one and the same task editor, whatever the source: transcript selection (**Task from selection**), Gmail, Chat, GitHub, repository findings, an unanswered meeting question (**Make task**), or free text (**New task**). The dialog always offers the same fields and the same actions — **Draft with AI**, **Improve with AI**, **Create or link**. When a source is attached, its evidence and the AI provider preview are shown inside the dialog, generation is optional, and the source, evidence, task fields, routing and retry receipt commit together. A task made from a question keeps a lasting link back to that question. No task is created until confirmation.

**Improve with AI** (new-task dialog and task editor) sends the current card — title,
description, expected result, plus the chosen project's goal when there is one — to the
configured AI provider after an explicit confirmation, and returns a sharper suggestion in
the same fields. An empty suggested field never wipes a filled one, the suggestion only
becomes real when the person saves, and it can never create or change a task by itself.
The fields stay editable while the AI works. If the person changes the card meanwhile, Atlanta
asks before it replaces the changes with the suggestion. Closing the form, or a failed status
check, cancels the job. The new-task dialog has the same **Expected result** field as the
task editor, so a suggested expected result is not lost.
With reasoning on **Automatic**, a cloud API or a thinking local model (qwen3.5) is asked for
**no** thinking on this improvement, so the editor does not wait for a reasoning pass at all.
Kimi K3 always thinks and rejects a no-thinking request, so there Atlanta asks for its lightest
valid effort (**low**). Another local server keeps its own default.

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

Manual task capture and evidence linking work with AI disabled or unconfigured. Only **Draft with AI** requires a valid AI provider; no worker starts without it.


## Meeting question sources and concurrent edits

**Make task** on a meeting question creates or reuses its canonical tracked question and commits the task and `derives_from` relationship together. The meeting question shows buttons for its tasks; the task Sources section links back to the question and focuses its row in the meeting. A question stays open until the person records an answer. The same answer is shown in the meeting and prevents the question from returning as unresolved in **Prepare me**; reopening makes it eligible again.

Tracked meeting questions inherit their meeting's project unless the person assigns their projects explicitly. A task made from a tracked question starts with its original meeting, project and source moment. Restoring a manual task into regenerated notes preserves its moment. Choosing **No project** for a new task is an explicit empty assignment; API callers that omit `project_id` retain meeting inheritance.

Creating a task from a notes line or question sends the notes revision captured when its editor opened. If the notes changed, the server refuses to attach the old row index and the editor keeps the draft. Retry after an uncertain response uses the exact same request and revision, so it returns the existing task without creating a duplicate. Older tracked questions can still resolve to their original note by meeting, exact wording and moment; no fuzzy cross-project answer matching is used.


## Tasks that implement meeting decisions

**Make task** on a decision opens the same task editor as a question. Its wording and reason prefill the title and description; the person still reviews and creates the task. The task keeps the meeting and recording moment and an `implements` relationship to the canonical decision. The decision shows its tasks; the task's Sources section links back to the exact decision row. Creating a task does not accept a proposed decision or change the original wording. This works with AI meeting tasks off; the source remains a meeting note and does not appear as a new AI proposal in My Work. The captured notes revision guards against changed or removed rows, and retrying the same request cannot create a second task.

A saved Gmail draft has one envelope indicator beside the task title in both compact and expanded My Work cards. It remains there whether the task has a last update or not; it is not part of the update or the state flags. Its accessible label and tooltip explain that a draft was saved, not sent.


UI audit corrections: compact task cards show summary facts and offer Quick fields in the menu; Inbox keeps meeting proposals before connected-source proposals and excludes fresh proposals from Stale. Closed tasks no longer request review confirmation. Task-title draft markers use content-sized titles; header actions occupy separate flex slots.


Work cards use active, proposed and closed lifecycle presentation. Questions and decisions keep History/GitHub and project administration under More details. Meeting review places routing after content, evidence and actions, inside the same secondary disclosure. Cancelled tasks offer Restore task rather than Mark done.


Library exposes Source above advanced filters and applies it immediately. Meeting cards show recording/transcript/notes readiness from local file availability, separately from the manual Done mark. Narrow layouts wrap Library/My Work tabs, keep menus beside titles and place project chips below. My Work identity setup is a disclosure instead of a permanent form row.

## Compact cards (2026-11-15)

- Tasks share a title/tools row and an editable facts row in My Work and Projects. Mark done/Reopen, Add update and Edit are direct icon buttons with accessible names and tooltips. Timeline and secondary actions stay in the overflow menu.
- Click Owner, State or Due date to open that field alone; close it with the visible close button. Quick fields in the menu opens the full four-field editor. The chosen field stays open across revision-checked saves.
- Description and Sources share the facts row as labelled icon disclosures and expand in place. The last update takes one line; the full update remains in Timeline. Follow-up dates show when assigned and gain an attention colour when due.
- In meeting notes, checked-against-source is a passive shield indicator, separate from Check/Undo check. Edit and Delete are direct buttons; no menu hides a single Delete action. Card actions, including Create task and Confirm, use icons; names and explanations stay in accessible labels and tooltips. Source timestamps stay direct; meeting-task quotations expand below the unchanged facts row. Existing confirmation and undo behavior is preserved.
- Meeting readiness uses accessible indicators for completed stages; missing stages and processing problems retain visible text. The personal Done action is separate from notes readiness.
- Compact layouts wrap at narrow widths. Status uses shape plus meaning, warnings keep text, and controls stay visible without hovering. Light and dark themes use the same theme variables.

Meeting task rows keep state, due date, description disclosure, source moment and GitHub on a shared wrapping facts line. Within an owner group the repeated owner is hidden; standalone rows retain it. Description opens on demand; completed state appears once.

The two-row hierarchy also applies to decisions, tracked questions, meeting-question candidates, Library conversations and meeting review. Projects, source access and secondary context share the facts row. Related question tasks and conversation previews expand in place. Meeting-review evidence and blocking notices remain readable below the two primary rows; Confirm/Edit/Skip retain their handlers and disabled states beside the title.

All direct card actions are icon-only, including Add another task, Make task, Confirm, acceptance/skip controls and the GitHub trigger. Expanded menus retain named choices. Status values, dates, people and context counts remain readable.

Dark appearance (Atlanta Dark, 2026-11-16): neutral near-black surfaces with restrained green. Green marks only the primary action, focus, the selected tab and success. Inputs are darker than their container. Page and dialog titles use the primary text colour. Links and source moments use the info blue. View and filter switches show the chosen view by a selected surface, not by a green frame. Task states have one colour on every screen: To do grey, In progress blue, Waiting amber, Done green, Cancelled muted; Overdue stays red on the due date. Project colours mark only the project: the card's vertical line and the dot in its chip. New projects pick from a muted nine-colour set; a saved project colour never changes. Metadata keeps the monospace stack.

Card action buttons and context triggers use one 32px-high box; icon-only controls are 32px wide, and symbols are 16px. Their frame stays muted green, including destructive hover. The symbols carry action meaning: green complete/accept, blue edit/copy, cyan create/update, red delete, amber check/restore, purple source/link/GitHub, and muted neutral tools. Shapes, names and tooltips remain available alongside colour.

Meeting task context now expands in a separate row while its source timestamp and icon controls stay on the facts line. Source quotation and description have distinct symbols, and opening one closes the other to avoid duplicated context. The expansion uses an explicitly hidden panel rather than relocating native details. Action frames and symbol colours are subdued; card controls have no hover/focus glow, and retain a thin visible keyboard focus outline.

Type and form scale (2026-11-16): page titles are 24px, dialog titles 21px, section titles 16px, field labels 13px and helper text 12–13px. Titles use weight 600, labels 500 and text 400, always in the primary text colour. In dialogs and the New meeting form, fields and buttons are 40px high with 8px corners and 12px side padding; inline helpers such as Improve with AI are 32px; text areas start at 96px, except the task Title. Lists and toolbars keep 32px controls and task rows keep the 28px compact scale, so lists stay dense.

Edit task layout (2026-11-16): the Title is one line and grows only when the text needs more; Description, Expected result and Add an update grow with their content up to a limit (Title, Description and Expected result also in New task). A new update is written in its own frame under **Progress & activity**, and **Activity history** follows right below it, before the people, sources and GitHub sections. The footer stays visible while the dialog scrolls: Cancel task and Send by email are on the left, Close and Save changes on the right. Every field and action stays available.

Confirmations and Undo (2026-11-16): risky actions ask first, and the confirm button is red for actions that remove or end something. Cancelling a task (in Edit task, in the State field of a card or for selected tasks), merging two items, deleting and discarding ask before anything changes; a merge cannot be undone. Other changes are saved at once and show the result with **Undo** for a few seconds: Save changes in Edit task, editing a title in place, Mark done and Reopen, and the Owner, State, Due date and Next follow-up fields of a card. Undo after Save changes restores only the fields that changed; a progress update stays in the task history.

### Email several meeting tasks

In a meeting's Tasks section, **Email tasks…** opens a checklist of accepted, visible tasks linked to that meeting. Select individual tasks or up to 100 together, then choose **Compose email**. My Work also supports multiple tasks through **Select tasks → Send by email…**. The composer lists the included tasks and lets you edit recipients, subject and text with a live formatting preview.

The default Bulgarian letter presents numbered tasks, details, expected results, owners, deadlines and states. A shared meeting appears once in the introduction and subject. Quotes and change history are omitted from the default letter. Saving creates one multipart Gmail draft with a plain-text fallback and escaped HTML formatting derived from the edited text; every selected task receives the draft marker. Atlanta never sends the email.

### Main tasks and subtasks

Tasks support one main task and one level of subtasks. In My Work select existing tasks and choose **Add to main task…** to select an existing main task or create one atomically. The task menu provides the same action. In Edit task, **Subtasks → Add existing subtasks…** offers search and select/clear matching tasks. A subtask can move to another main task or detach; its owner, dates, state, history and source evidence stay intact. Main tasks cannot themselves become subtasks while they have children. Grouping uses revision checks and an idempotent request ID; a failed or uncertain request can be retried unchanged.

My Work nests matching subtasks beneath their main task with a collapsible list. Filters still apply to each task: a matching subtask remains visible on its own if its parent does not match. Main cards show completed/total subtasks. Completing a main task with unfinished subtasks requires explicit confirmation and never completes the children. Deleting a main task detaches and keeps its children; merging duplicates requires detaching hierarchy links first.

The email composer explicitly lists the selected main tasks and available subtasks. Only checked tasks are included. **Apply selection and rebuild letter** updates the letter and preserves recipients; replacing edited text asks first, and saving is disabled while an unapplied selection is pending. Selected children follow their selected parent as 1.1, 1.2, etc., retaining individual owners and deadlines. A child sent alone names its main task for context. Suggested related tasks are never automatically added to the email.
