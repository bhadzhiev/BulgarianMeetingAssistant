# My Work, Gmail and Google Chat

## My Work: one place for meetings, Gmail, Chat and GitHub

Every task, decision and proposal shows a coloured source chip: **Meeting**, **Gmail**, **Chat** or
**GitHub**. Click a chip to open the source. **All sources** filters the task and decision lists.

A task card shows the task, its owner, its due date, its source, **Mark done** and **Add update**.
The more-actions menu opens **Timeline**, **Quick fields** or the full task editor. **Quick fields**
opens the owner, state, due date and next check fields.
The fields stay open after a save. An owner name that matches one person in People shows as that
person. A name without a People entry shows as "· not in People".

In every owner list, the people in your team come first, in alphabetical order. The other people
come next, also in alphabetical order. The typed owner suggestions use the same order.

### Tasks from meetings: you make them

Since 2026-11-12 the AI stops at the meeting notes. The notes still list the tasks that the meeting
named, but each line is text only. Atlanta does not make task proposals from the notes, does not
match them with existing tasks, and does not add updates to tasks. You decide which tasks to keep.

- Click **Create task** on a task line of the notes. The editor opens with the title, description,
  owner and due date of the line. Edit them and click **Create task**.
- The new task links to the meeting and to the line. The line then shows the task card.
- Change the state of a task by hand in My Work. Use the **Updates on work in progress** section
  of the notes as the source.
- Decisions are text in the notes too. Check a decision in the notes to mark it as agreed. My Work has no
  Decisions tab then.
- In Edit of the notes, a task line is text only. Owner, dates and state belong to the task card.
- Task proposals and decisions that the AI made before stay hidden. They are not deleted.
- The meeting has no Review tab for these items, and the review list in My Work does not count them.
- The Inbox holds the Gmail, Google Chat and GitHub suggestions. My Work opens on **All tasks** when
  the saved view is an empty Inbox. A link to the Inbox still opens it.

To get the old behaviour back, turn on **Settings → AI → Let AI propose tasks from meeting notes and
match them with existing tasks**. The hidden proposals then show again, and the sections below apply.
Gmail, Google Chat and GitHub suggestions do not depend on this setting.

### Updates from meetings

This section applies only when AI meeting tasks are on.

After the notes of a meeting, Atlanta compares what each speaker said with the open tasks of that
speaker. When a speaker gives new progress, a blocker or a clarification about their own open task,
Atlanta adds it to that task. The timeline shows it as "Update from the meeting (added by AI)", with
the meeting, the time and the words that were said. The update has the date of the meeting, so an
update from an old meeting never hides a newer one. **Remove this update** removes a wrong update;
the history keeps a record of the removal.

Only the speaker's own open tasks get an update at once, and only when the AI is sure (confidence high)
that the words are about the same work and result. A speaker must be a person in People.
Updates about tasks of other people, closed tasks and proposed changes (owner, due date, state) wait
in the Inbox (Tasks → Inbox). This uses task matching, so it needs the configured API and its permission in
Settings → AI.

### Send tasks by email

Choose **Send by email…** in the **...** menu of a task or in the task editor. To send several tasks
in one email, select them and choose **Send by email…** in the selection bar. The text comes from the
task fields: title, details, expected result, owner, due date and meeting. The end of the text has
the note "Генерирано от Atlanta". A saved draft always has this note.

The owners and the others on the tasks are preselected as recipients. Choose **Save Gmail draft**.
Atlanta saves a Gmail draft and never sends email. Each task then shows an envelope (**Gmail draft**),
and its history has an entry with the recipients and the subject. Saving again for the same tasks
updates the same draft. This needs the `gmail.compose` permission, the same as **Follow-up email**.

**Focus** in My Work keeps up to three tasks selected on this Mac. The picker
suggests overdue tasks and tasks due within seven days. Open any entry to see
the task card or remove it from Focus.

Projects uses the same task cards as My Work. **Overview** previews up to five
items of each kind. **Work** starts with **Open** tasks. **Completed** lists the most
recent completions first, with search across all matching history and **Show more**
for the next groups of tasks. Cancelled tasks have their own view. **Delete** and other rare actions of a task, a decision or a
notes line are in its **...** menu, so the row keeps its main action in view.

The Gmail, Chat and GitHub tabs use the same layout. The bar on top shows the connection and the sync
state. A list of threads, conversations or issues comes next; arrow keys move through it. The open
item fills a fixed-height reader below, with its actions under it. Rare actions (reconnect, stop,
reload) are in the **⋯** menu. Explanations and cache clearing are under **About**.

- **Gmail** shows the selected thread message by message, with **Suggest a task** and **Analyze with
  AI** on each message.
- **Chat** shows the conversation as a chat: sender names, times and day separators, newest at the
  bottom. Select a message to suggest a task from it. A click selects the whole burst: the messages
  of one sender less than 5 minutes apart. Shift-click adds messages up to the clicked one, also from
  other people (up to 30). The list refreshes itself when it is older
  than 10 minutes, and the first open of a conversation syncs it. Direct messages are named after the other person.
- **GitHub** lists every open issue and pull request without a repository choice. See below.

A thread, Chat message or GitHub item that already has a task shows a small green check mark next to
its title. A number shows when there is more than one task. Click the mark to open the task. Click the
rest of the row to open the source. The mark is grey when all its tasks are done. Hidden tasks do not
show a mark.

## AgentMail: a dedicated test inbox

Open **My Work → Sources → AgentMail** and connect a single `@agentmail.to` inbox with an
inbox-scoped API key granting `inbox_read` and `message_read`. Atlanta saves the credential in
macOS Keychain. **Refresh inbox** lists up to 50 recent incoming messages. Open a message to read
its text. Forwarded messages retain their text and replies prefer the provider's extracted reply.
Atlanta reads selected messages through the AgentMail API.

**Create task…** opens the task editor with the subject and selected body. **Add update to task…**
lets you choose an existing task and edit the progress text. Saving either action pins the message
as evidence. Saving an update leaves the owner, state and dates in place. Disconnect clears the local
credential and message previews. Task evidence already saved in Atlanta remains available.

To send a task, open **Send by email**, review the recipients and email text, and choose
**Send from Atlanta**. Confirm the sender and recipients. The key needs the additional
`message_send` permission for the connected inbox. AgentMail treats a retry with the same
task selection, recipients and text as the same send during its idempotency window.
After AgentMail confirms a send, each included task shows a sent envelope and a history entry.

## Gmail: local read-only pilot

Gmail sync is read-only. The only Gmail writes are email drafts: the follow-up email and tasks by
email. They use their own `gmail.compose` permission (see **Follow-up email**).

Open **My Work → Gmail → Connect Gmail read-only**. Use the shared Google connection and approve
`gmail.readonly`. Calendar permission is requested only if already used or separately connected.
This desktop OAuth flow requests the complete selected scope set again; it does not use incremental
authorization. Tokens stay in macOS Keychain. Enable the Gmail API for the app's OAuth project;
Workspace admin policy, OAuth testing users or restricted-scope verification can block access.
See [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) and
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

The Gmail tab syncs by itself. When the tab opens, a sync starts if the last one is older than
5 minutes or did not finish. While the tab is open, it checks again each minute. **Sync** starts a
sync at once.

One sync continues page by page (20 threads per page) until the cache is current. Each page is saved,
so a stop keeps the work done. The first sync covers up to 200 threads with Inbox/Sent activity in the
preceding 30 days. A limit message means the initial window is incomplete. Later syncs use Gmail
history. Atlanta reads the history first and then fetches the changed threads newest first, so today's
mail comes first. An expired history cursor asks you to start a bounded rebuild. Recording/processing
pauses further work, and Cancel stops before the next cache commit. A network request already in
flight can take up to its 30-second timeout; it does not hold recording controls.

**Needs reply** means the latest non-draft message is incoming; **Waiting for** means it is sent.
These are direction-based candidates, not AI judgments that someone owes a reply. Open a thread to
read its cached text and fetch time. An HTML-only message becomes Markdown: headings, lists, emphasis,
links and quotes stay. Gmail, Chat and GitHub text show in one Markdown view, and https links open in
the default browser. Remote images, scripts and attachments are not fetched or rendered. Threads
cached before 2026-11-21 keep their old plain text until they change or the cache is cleared. A thread includes at most its latest 100 non-draft messages and local
size limits apply. A thread larger than the Google response limit (8 MB) is read message by message.
A message that is still too large, or a body over the local limit, keeps its sender, subject and date;
the reader says "too large to load" and the sync goes on. When the thread text is too long, the
oldest bodies are left out first. Matching threads can contain older messages. This version does not send, modify,
label or draft email. Email content reaches an AI endpoint only through the selected-message approval below.

**Suggest a task** opens the same task editor used everywhere, with this message pinned as the
source and the AI provider preview shown. The editor never opens empty: the title and the
description come from the source itself, with no AI. A GitHub item gives its title, an email its
subject without "Re:" or "Fwd:", and a Chat message or meeting passage its first line with at
least three words. A code finding gives its conclusion. The description holds the source text.
**Draft with AI** is optional. It asks before it replaces text only after you edit the fields. **Create task** confirms
the edited text and saves an open task with the pinned source quote. Cancel discards the draft;
owners and dates are not assigned automatically. Syncing a
changed previously-linked thread marks its old pending proposals stale. A removed/out-of-window
thread becomes unavailable without completing its WorkItems. Review uses the last synced revision;
it is not a live Gmail check at the instant you click Accept.

The rebuildable `gmail-cache.sqlite3` holds email text locally. Accounts have separate caches; only
the connected account is shown. **Clear local email cache** can remove a selected cached account even
after sign-out. This keeps promoted WorkItem source snapshots and archives. The email cache and
cursor are excluded from library archives; promoted sources/proposals remain in the portable graph.
Incremental sync can grow the cache beyond the initial cap; lists show at most 200 threads. There is
no automatic email retention purge or automatic background sync in this pilot.

### Analyze one email message with AI

Open a cached message and choose **Analyze this message with AI**. Preview shows the account,
subject, character count, configured API endpoint and model from **Settings → Notes & AI**. The
endpoint can be remote, even when the provider is called local. **Cancel** sends nothing. **Approve
and analyze** permits one request for that message revision and those settings; there is no cloud
fallback and the OpenAI API key is not used for this feature.

The worker receives only the selected body, sender, subject and message ID. It does not send the
other messages in the thread or any meeting transcripts. Inputs are limited to 20,000 characters
including metadata; larger messages need a manual proposal. Up to 20 candidate tasks can be returned.
Quotes must occur verbatim in the selected body. Owners and deadlines must occur in that quote;
`due_date` accepts only an explicit `YYYY-MM-DD` date in the quote. Relative dates remain literal
text rather than guessed calendar dates. These checks do not prove that the AI understood the email;
review the task and fields before **Accept** or **Link**.

A successful run creates proposals only. Accept applies proposed owner/date fields to a new open
task. Link adds evidence to the existing item and preserves its human text, owner, dates and status.
Proposals, the replay checkpoint and consumed consent commit together. **Show saved analysis**
reuses the exact message/settings result, including earlier Dismiss/Accept/Link states, without
another AI request. A changed message or settings requires a new preview.

**Cancel email AI analysis**, recording/processing, account/settings changes and source revocation
stop the owned client worker; no new proposals are published from that cancelled run. Data already
sent cannot be recalled, and an endpoint may continue computing after its client disconnects.
Consent expires when the run ends and is revoked on restart/restore. Interrupted jobs never resume
automatically. The private input pipe carries email text; it is not written to job argument files.
Analyzed source snapshots remain local in the WorkItem graph and archives, even if the model finds
no tasks. Clearing the email cache does not purge those snapshots.

The connector and extraction flow are tested with synthetic Gmail responses and a local mock AI
endpoint. Live consent, Workspace policy, a real mailbox sync and real-model extraction quality still
need validation with the app owner's account. Broad background email analysis is not enabled.

## Google Chat: selected conversations, read-only

Open **My Work → Google Chat → Connect Chat read-only**. The shared Google connection requests
`chat.spaces.readonly`, `chat.messages.readonly` and OpenID/email identity. Gmail and Calendar are
not required for Chat-only sign-in; previously selected Google permissions are retained in explicit
re-consent. Enable the Chat API in the OAuth project. Workspace policy or OAuth verification can
still block access. This is user authentication, with no bot, service account, administrator search,
send or edit permission. See [Chat authorization](https://developers.google.com/workspace/chat/authenticate-authorize).

**Refresh conversation list** (in the **⋯** menu) reads the whole conversation list in one run, up to
500 conversations. The list also refreshes itself when you open Chat and the last refresh is older
than 10 minutes, so a new group chat appears without a manual refresh. A conversation that was active
in the last 30 days and has no local copy gets its newest messages in the same run (up to 40
conversations). Its people and message count then show in the list. Other conversations download
their messages when you open them. The list is sorted by the latest activity in Google Chat.
Direct messages without activity in the last 30 days are hidden. A note says how many, and a search
still finds them. Group chats and spaces always show. Named spaces use their names; a group chat
without a name shows its people after its messages are synced. System membership messages are
excluded by the provider. This view covers conversations the signed-in user can access, not the whole organization.

Each message refresh cycle fixes a 30-day creation-time window and reads at most 200 messages,
20 per page, newest first. Continue keeps that window/page token after interruption. Once complete,
Sync starts a new recent-window refresh. **Restart recent window** discards only the unfinished
cursor, keeping cached messages and source history. Cancel and recording/processing stop further
work; an in-flight request can take up to 30 seconds. There is no automatic background polling,
Workspace Events subscription or complete historical mirror.

Open a cached message to see its sender, message/thread resource names, text and fetch time.
**Refresh this message from Chat** checks that individual resource for edits or deletion, including
older cached messages. Observed edits invalidate older pending proposals; deletion/403/404 makes
its source unavailable without completing or reopening the WorkItem. Losing space access also
removes cached text for that space. Prior pinned source snapshots and archives remain local.
Absence from a capped refresh does not prove deletion; messages outside its range need an individual
refresh. Old cache records can remain until cleared, and message lists show at most 200 entries.

**Suggest a task** opens an editable draft from the selected messages. Several messages are one
source, in reading order; with more than one sender, each line starts with the sender's name. The
source is named after the first message, so the task mark shows on that message. **Draft with AI**
asks for its own approval. **Create task** saves the confirmed task with the exact quoted messages and
space/thread/message/sender references. Cancel creates nothing. This never sends or edits a Chat message. Cards, attachments and remote resources are not
fetched or executed. Chat content reaches the shown AI provider only after its own task-draft approval; Gmail AI approval does not
cover Chat. Quotes and known versions reflect the last observed API response, not a live check at
the moment of acceptance.

`chat-cache.sqlite3` is a rebuildable local cache excluded from library archives. Partitioning uses
the verified Google user ID, so an email rename keeps the same cache. **Clear local Chat cache**
can remove a cached identity after sign-out and keeps promoted WorkItem snapshots in the graph and
archives. There is no automatic retention purge. All development tests use synthetic Chat responses;
live Workspace consent, API access and real conversation sync still need account-owner validation.

### Task list controls (2026-11-14)

Both Compact and Cards start bulk selection with **Select tasks**. The selection count and
checkboxes appear only in selection mode. Cards keep Mark done and Add update on the surface;
Timeline and Quick fields are in the menu, and Sources is collapsed. Opening the title still
opens the complete editor, including Improve with AI, expected result, history and evidence.
The envelope says **Gmail draft**: Atlanta does not know whether that draft was sent in Gmail.

**Select overdue · N** (2026-11-23) shows next to **Select tasks** when the list has overdue tasks.
It selects the open overdue tasks on the list (up to 100) and opens **Set due date**. The quick
dates **Tomorrow**, **Next Monday**, **In a week** and **In two weeks** fill the date. Apply still
asks for confirmation and saves only on this Mac.

### Person-centred 1:1 review history

Select a name in Team to see that person’s review history, open agreements and the next conversation. Reviews also has a person picker; the all-reviews list is a secondary archive. See [Person review history](person-review-history.md) for conversation dates, checked results, selected private context and safe fact refresh.
