# My Work, Gmail and Google Chat

## My Work: one place for meetings, Gmail, Chat and GitHub

Every task, decision and proposal shows a coloured source chip: **Meeting**, **Gmail**, **Chat** or
**GitHub**. Click a chip to open the source. **All sources** filters the task and decision lists.

A task card shows the task, its owner, its due date, its source and **Mark done**. **Change owner or
dates** opens the owner, state, due date and next check fields, with **Add update** and **Timeline**.
The fields stay open after a save. An owner name that matches one person in People shows as that
person. A name without a People entry shows as "· not in People".

In every owner list, the people in your team come first, in alphabetical order. The other people
come next, also in alphabetical order. The typed owner suggestions use the same order.

### Updates from meetings

After the notes of a meeting, Atlanta compares what each speaker said with the open tasks of that
speaker. When a speaker gives new progress, a blocker or a clarification about their own open task,
Atlanta adds it to that task. The timeline shows it as "Update from the meeting (added by AI)", with
the meeting, the time and the words that were said. The update has the date of the meeting, so an
update from an old meeting never hides a newer one. **Remove this update** removes a wrong update;
the history keeps a record of the removal.

Only the speaker's own open tasks get an update at once, and only when the AI is sure (confidence high)
that the words are about the same work and result. A speaker must be a person in People.
Updates about tasks of other people, closed tasks and proposed changes (owner, due date, state) wait
in For review. This uses task matching, so it needs the configured API and its permission in
Settings → AI.

### Send tasks by email

Choose **Send by email…** in the **...** menu of a task or in the task editor. To send several tasks
in one email, select them and choose **Send by email…** in the selection bar. The text comes from the
task fields: title, details, expected result, owner, due date and meeting. The end of the text has
the note "Генерирано от Atlanta". A saved draft always has this note.

The owners and the others on the tasks are preselected as recipients. Choose **Save Gmail draft**.
Atlanta saves a Gmail draft and never sends email. Each task then shows an envelope (**Emailed**),
and its history has an entry with the recipients and the subject. Saving again for the same tasks
updates the same draft. This needs the `gmail.compose` permission, the same as **Follow-up email**.

Projects shows tasks and decisions with the same rows as My Work. The overview shows five of each kind;
**All tasks in Work →** opens the full list. **Delete** and other rare actions of a task, a decision or a
notes line are in its **...** menu, so the row keeps its main action in view.

The Gmail, Chat and GitHub tabs use the same layout. The bar on top shows the connection and the sync
state. A list of threads, conversations or issues comes next; arrow keys move through it. The open
item fills a fixed-height reader below, with its actions under it. Rare actions (reconnect, stop,
reload) are in the **⋯** menu. Explanations and cache clearing are under **About**.

- **Gmail** shows the selected thread message by message, with **Suggest a task** and **Analyze with
  AI** on each message.
- **Chat** shows the conversation as a chat: sender names, times and day separators, newest at the
  bottom. Select a message to suggest a task from it. The first visit loads the conversation list,
  and the first open of a conversation syncs it. Direct messages are named after the other person.
- **GitHub** lists every open issue and pull request without a repository choice. See below.

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
read its cached text and fetch time. HTML becomes plain text; remote images, scripts and attachments
are not fetched or rendered. A thread includes at most its latest 100 non-draft messages and local
size limits apply. Matching threads can contain older messages. This version does not send, modify,
label or draft email. Email content reaches an AI endpoint only through the selected-message approval below.

**Suggest a task** previews the AI provider and generates an editable task draft from this message.
**Create task** confirms the edited text and saves an open task with a pinned source quote.
Cancel discards the draft; owners and dates are not assigned automatically. Syncing a
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

**Refresh conversation list** (in the **⋯** menu) fetches conversation metadata only. It reads at most 50 spaces per page and 200 per
discovery cycle; use Load more until complete. Choose a conversation explicitly before **Sync /
Continue** downloads message text. Named spaces use their names; DMs/group chats without a display
name show their resource ID. Empty DMs/group chats and system membership messages are excluded by
the provider. This view covers conversations the signed-in user can access, not the whole organization.

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

**Suggest a task** asks for AI approval for this Chat message, then opens an editable draft.
**Create task** saves the confirmed task with the exact quoted message and
space/thread/message/sender references. Cancel creates nothing. This never sends or edits a Chat message. Cards, attachments and remote resources are not
fetched or executed. Chat content reaches the shown AI provider only after its own task-draft approval; Gmail AI approval does not
cover Chat. Quotes and known versions reflect the last observed API response, not a live check at
the moment of acceptance.

`chat-cache.sqlite3` is a rebuildable local cache excluded from library archives. Partitioning uses
the verified Google user ID, so an email rename keeps the same cache. **Clear local Chat cache**
can remove a cached identity after sign-out and keeps promoted WorkItem snapshots in the graph and
archives. There is no automatic retention purge. All development tests use synthetic Chat responses;
live Workspace consent, API access and real conversation sync still need account-owner validation.
