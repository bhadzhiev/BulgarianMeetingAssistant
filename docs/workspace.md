# Projects, conversations and the workspace

### Project workspace

Open **Projects** to create a project independently of a meeting and see its
meetings, tasks, decisions, questions and linked source evidence together.
**Unassigned** collects meetings and work without an effective project.

Each accepted WorkItem has an **Assign to project** control in My Work and the
project workspace. Choose one or more projects and save. A saved empty selection
means explicitly unassigned. **Use meeting projects** restores automatic grouping
from linked meetings. Manual choices survive source sync and notes refresh;
assigning a project does not accept a proposal or change a task/source status.
External sources appear through their accepted/linked WorkItems and saved quotes.
Moving a meeting updates inherited assignments, while preserving manual choices.
Archive/Restore retains assignments and maps project IDs to restored projects.

Projects now also link transcript excerpts and cached Gmail/Chat conversations directly, without requiring a WorkItem.


### Conversations library

**Conversations** is the full browser; the sidebar keeps five recent matching
meetings and a link to the library. Search saved transcript text or titles and
filter by project, series, participant and inclusive Europe/Sofia dates. Results
are paginated, 50 per page. Meeting speaker names come from the current saved
transcript (draft captions are used only when no final transcript exists).

Select up to 200 meetings and move them to a project together. Scope revisions
prevent overwriting a newer project assignment; active meetings cannot be moved.
The app journals the scope update so an interrupted batch completes on restart.
Explicit WorkItem project assignments are preserved. A series is retained only
when its parent project stays the same, unless a new series is selected.

From a saved transcript choose **Attach excerpt to project** and select speaker
turns or a time range. Ranges include complete overlapping transcript segments,
up to 500 segments per excerpt. The app checks the transcript revision and saves
a pinned quote with its timestamps, speaker labels and original meeting link.
It does not copy audio. Editing or removing the transcript preserves the quote
and marks its original as changed/unavailable. Saved excerpts support multiple
projects through **Save project links**.

Choose **Gmail threads** or **Chat conversations** to attach cached conversations
without accepting or creating a task. This is a bounded snapshot of the existing
cache, not a request for complete remote history; attachments are not fetched.
Snapshots do not update automatically and no AI request or connector write is
made. Refresh normal source sync, then explicitly attach the new cached revision
if needed. Saved snapshots remain readable after disconnecting or clearing the
source cache. Unassigning them retains the local evidence and existing archives.

In **My Work → Gmail** or **Chat**, **Attach to project** on an open thread or
conversation saves the same snapshot directly. It shows the projects that already
have it; choosing again saves the current cached version.

**Timeline → Trace** shows one row for each group of linked work: the conversation
where it started, the decision, the tasks, their GitHub issue or PR, and the merged
code change. Items join a row only through links that a person saves with **Link to
another item** on a task, decision or question (implements, comes from, supports,
same as). The other steps join by identity, never by similar text or dates: the
item's meetings and source quotes, the attached excerpt that contains the quoted
moment, the attached thread or Chat space of a Gmail or Chat source, and the merged
PR with the same repository and number in a repository report of the connected
GitHub account. Each step opens its evidence. **Timeline → Events** lists the same
records by day, including those merged code changes.

Projects have **Conversations** and **Timeline** tabs. The timeline combines
meeting/source dates, recorded WorkItem history and dated GitHub source captures,
with evidence navigation and explicitly stored relationships. It does not infer
causality, completed work, successful CI or deployments. It shows current item
wording/status alongside event dates, up to 300 newest events. Links and pinned
quotes are included in Archive/Restore; project IDs are remapped on restore.
The additive conversation-link collection upgrades the WorkItem SQLite schema
to version 3; older app builds refuse this database rather than discarding links.


### Consistent periods, preparation and confirmed identities

The Library, repository reports, analytics and task dates share the Atlanta date
picker, with keyboard navigation, typed ISO dates and Today/Yesterday/Last 7 days
period shortcuts. A calendar day uses local dates, preserving DST boundaries.
Library batch actions appear only after selecting meetings.

Meeting type is visible before recording. Prepare me asks which upcoming meeting
to prepare when a project contains mixed types; an explicit choice can override a
series default. Preparation retains the whole project's work but takes typed
context from the last matching meeting. Backlog refinement adds readiness,
acceptance criteria and estimation blockers. Sprint review distinguishes shown,
finished and explicitly accepted changes. Saved templates and prior notes remain
unchanged until the user reprocesses or edits them.

GitHub draft options regenerate untouched fields while keeping manual edits.
Issue and comment edits are retained separately in memory during the page session.
Review regenerated text compares both versions before explicit replacement.
Drafts are not published, stored in browser storage or sent to AI by this feature.

Confirm a message sender with Link sender to person. Gmail matches a manually
confirmed exact email; Chat requires a confirmed stable users/ ID scoped to its
Google account. Display names and voice are never used to guess channel links.
Renaming a person retains the previous name as an alias. Numbered speakers stay
scoped to their meeting. Profiles join saved statements/commitments, existing
GitHub assignments and matching local email/Chat cache messages. Profile channel
coverage is bounded to 1000 cached threads/messages and 50 matching messages per
channel. Clearing a source cache removes its profile message preview, while
confirmed identities remain in people.json and library archives.

GitHub resource links distinguish Found in local cache, Checked in GitHub and
Not checked/offline. They show the cache timestamp and/or last live check when
known. Check in GitHub performs an explicit read-only refresh; a failed refresh
preserves the previous title/state and labels it unavailable. Legacy links whose
verification origin is unknown ask for a new check. These labels never mark a
local task completed or claim CI/deployment success.


**Suggest a task** now drafts one task with the selected Notes & AI model from the selected
Gmail message, Chat message, GitHub issue/PR or saved repository finding and its evidence.
Review the model/provider before generating, then edit the multiline draft and choose
**Create task**. Only that confirmation creates an open local task in My Work, with pinned
source evidence. Cancel discards the draft. Generation does not create a proposal or task,
assign an owner/deadline, or publish anything to GitHub. A changed source requires a new draft.

### Reliable editing and a consistent workspace

Dates are shown/entered as **dd.mm.yyyy** (date/time: **dd.mm.yyyy · HH:MM**, Europe/Sofia), while API and archive date-only fields retain ISO values. The compact Library keeps Search, Project and Period visible, with additional filters under More filters. Filters stay in session state when returning to the Library.

**My Work → Sources** groups Gmail, Chat and GitHub. **Suggest a task** opens a source-aware editor; generate with the shown AI provider or write manually, choose a project, then **Create task**. Generation can be cancelled. Draft retention is optional and limited to 24 hours on this Mac. A successful task creation remains successful even if refreshing its list fails; **Open task** returns directly to it.

Project and meeting type are visible before recording. Project-level **Prepare me** includes externally sourced tasks explicitly assigned to that project. Transcript/note edits are protected from late refreshes and navigation races, and calendar Clear updates the saved due date.

The desktop app warns before quitting with unsaved editor changes. **App menu → Recover interface** reloads the interface while recording and the local backend continue; unsaved edits require confirmation. Copy diagnostics omits credentials and source text.

Repository reports analyze bounded groups of changes and then synthesize the supported source passages. Per-change findings and exact evidence remain available. See [UX validation and benchmark limits](ux-flow-validation.md) for the implemented contracts and reproducible measurements.


### Editable AI instructions

**Settings → AI instructions** configures nine operations: meeting notes/tasks/decisions,
transcript correction, meeting titles, Gmail commitments, task drafts, GitHub change analysis,
GitHub report synthesis, search answers and semantic topic matching. Edit the task layer
(language, style, focus and extraction priorities); source adapters, JSON schemas and
runtime evidence checks remain in code. Transcription vocabulary remains under Recording.

Instructions inherit in order: defaults → global → meeting type → individual meeting.
Meeting-specific scopes apply to notes, correction, titles and topic matching. Operations
spanning sources use global instructions. **AI instructions** next to a meeting's type
opens its override. Save blank / Reset to inherited removes only that layer. The last
20 versions per layer can be loaded into the editor and saved as a new version.
Concurrent edits require reloading instead of overwriting another save.

Recording start freezes the instructions. Processing retries keep the saved snapshot;
explicit reprocessing uses the current configuration. Saving instructions never reruns
old meetings or changes tasks automatically. Select a meeting in the notes editor and
choose **Generate new notes for this meeting** to explicitly request a new proposal;
saved notes remain until the existing review flow accepts changes. `prompt-history/`
inside the meeting retains used snapshots, with the latest step snapshot in
`prompt-<step>.json`. Archives include `ai-prompts.json`; restore adds missing prompt
layers without replacing existing overrides.

**Test with an excerpt** previews an explicitly pasted snippet (up to 4000 characters),
assembled test messages, schema, destination and model before approval. Tests always
use the saved **Notes & AI** destination, even for stages whose production provider is
configured separately. The source is synthetic; normal whole-meeting chunking and
source collection are not simulated. An isolated cancellable worker runs the request,
validates the result and holds it in memory without writing meeting outputs or creating
tasks. Recording/processing takes priority. The test never loads a meeting transcript
automatically. No cloud/model quality claims follow from a successful test.

**Meeting types → Customize a copy** copies a built-in's section definitions and
preparation style into the editable template form. Save gives it a separate identity;
existing meetings retain their saved template. Prepare me is deterministic from saved
data and uses that preparation style, without an LLM request or a separate AI prompt.

### Compact everyday navigation

**New meeting** keeps name, type and project together. Audio and recording controls
live in a separate disclosure; Start recording remains visible at the bottom. **Import**
opens its own view. **Library** starts with Search and closed Filters, with chips for
active filters and an explicit Apply action. Empty Library and My Work views show the
next useful action instead of unused controls.

Projects use **Overview, Work, Meetings, Timeline**. Sources and Conversations are in
**More**; Work includes its kind filter. The sidebar project selector is explicitly
**Filter recent meetings**, separate from the project workspace, and full search lives
in Library. Below 1000 px navigation becomes an icon rail; phones use a compact top bar.

Meeting detail has one next primary action. Transcript editing is in its header; Save
appears during editing, and cancel protects unsaved corrections. Select transcript text
to attach an excerpt; the confirmation uses complete source segments to retain exact
quotes and timestamps. Files, AI instructions and next-meeting preparation are in More.
Settings groups the original panels under **Recording, AI, People & sources, Workspace,
Advanced**. Diagnostics are in **Advanced → Help**. Existing project-section links remain
valid. See `docs/ux-flow-validation.md` for measured layout and test boundaries.

### Manual tasks

Use **New task** in My Work for a standalone action, or **Add task** in a meeting for a meeting-linked action. Set the text, owner, due date and project before saving. Meeting task rows have **Edit task**; My Work uses the existing task editor. These are normal local WorkItems with history, status, project routing and GitHub preview/approval. Creating one does not call AI or publish externally.

User-added meeting tasks survive regenerated notes and remain available before notes exist. No transcript timestamp is invented. Deleting the meeting keeps the user task in My Work without a dangling meeting link. A repeated creation request uses the same request ID to avoid duplicates after a lost response.

### Project repository links

In **Projects → select a project → Overview → Repositories**, click **Link repository**, search the accessible repository list and use **Link selected repository**, or enter `owner/name` manually. **Save links** applies the staged changes; the editor shows unsaved changes and warns when unlinking a repository used as a task destination. A repository can belong to several projects. Unlinking keeps existing issues and historical GitHub links. Manual entries do not prove access.

A task can publish only to a repository linked to one of its effective projects. Removing its chosen destination requires explicit reselection; Atlanta does not silently substitute another repository. Multiple linked repositories require a choice unless the task already has a valid destination. Changing the project repository links invalidates earlier publication previews, including removing and subsequently restoring the same link. Failed project saves restore the previous in-memory configuration.

### One People directory for meeting participants

People is the shared directory for meeting participants, task owners and confirmed channel
identities. Naming a new participant creates a People profile; choosing an existing person
changes the participant in this meeting, without adding a global alias. Edit global aliases
explicitly in the person's profile. Person renames retain the old name as an alias, preserving
older meetings, task ownership and voice matching.

Legacy `speakers.json` names import once into `people.json`. Exact unique names/aliases reuse
existing profiles and IDs. Original legacy bytes remain in `speakers.migrated-*.json`; the old
list is no longer a live registry. Ambiguous matches require review in People. Corrupt source
files are retained and reported. Unidentified `SPEAKER_00` labels stay meeting-local.

Optional voice matching uses profiles already present in People and only proposes a name.
The person's detail shows current local voice samples. Deleting a person stops future voice
suggestions for that profile; original meetings, audio and saved task text remain available.
