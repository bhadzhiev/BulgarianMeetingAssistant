# Atlanta terminology

**Status: draft.** This list waits for a domain review and a privacy review. After approval it is the reference for all UI text and for QA checks (decision D05).

The UI is in English. Each term has a definition, the context where it shows, the words not to use for it, and an example.

## Work items: task, goal, decision, question

These four are different things. Do not use one word for another.

| Term | Definition | Context | Do not use | Example |
| --- | --- | --- | --- | --- |
| **Task** | A piece of work that one person owns and that has a state. Others can also work on it. | My Work, Projects, task editor | action item, to-do, ticket, issue | "Task saved" |
| **Action** (1:1) | An agreed step in a 1:1 review. It is not a task until you create one from it with "Make a task…". | 1:1 review, actions and goals | task (before you create the task) | "＋ Action" |
| **Goal** (1:1) | A change that a person wants to reach. It has the states Open, Done and Dropped. It has no owner workflow. | 1:1 review, actions and goals | task, objective, OKR | "＋ Goal" |
| **Decision** | Something that the meeting agreed. It has a status (proposed, accepted, superseded). It has no owner and no due date. | My Work → Decisions, meeting notes | task, agreement, resolution | "Accepted decision" |
| **Question** | An open question from a meeting that someone tracks until it has an answer. | My Work → Questions | task, issue | "New question" |

## People: person, participant, speaker

| Term | Definition | Context | Do not use | Example |
| --- | --- | --- | --- | --- |
| **Person** | A confirmed profile in Settings → People. It has a name, and can have emails, aliases and a GitHub login. | People, Team, task owner | contact, user, member (outside Team) | "Delete person" |
| **Participant** | A person who took part in one meeting. | Library filters, meeting header | attendee, speaker | "Participant: Ana" |
| **Speaker** | A voice in one transcript, for example "SPEAKER_01", before or after you connect it to a person. | Transcript, analytics | person (before you connect it), participant | "This is Ana" (connects a speaker to a person) |
| **This is me** | Your own person, to filter My tasks and Assigned by me. It is not a login and gives no access. | My Work | user, account, login | "This is me" |
| **Team member** | A person in your team, with membership periods. | Team | employee, report | "Leave the team…" |

## Task roles

| Term | Definition | Do not use |
| --- | --- | --- |
| **Owner** | The person who is accountable for the task. One owner per task. | assignee (alone), responsible |
| **Also working on it** | The other people who share the task and its state. The owner stays accountable. | co-owner, owner |
| **Received from** | The person who asked for the task. | requester (in the UI), reporter |
| **Assigned by** | The person who gave the task to the owner. | creator |
| **Followed by** | The person who checks that the task moves. | watcher, follower (in the UI) |

## States

| Term | Values | Context | Note |
| --- | --- | --- | --- |
| **Task state** | To do, In progress, Waiting, Done, Cancelled | Every task surface | One list for all task surfaces. |
| **Goal state** | Open, Done, Dropped | 1:1 actions and goals | "Dropped" means you stopped the goal on purpose. It is not a failure. |
| **Review status** | Draft, Finalized, Superseded | Team reviews | Superseded means a newer version replaces it. |
| **Job state** | Queued, Running, Completed, Failed, Cancelled | Background jobs | Queued means the request is accepted, not done. |
| **GitHub state** | Verified, Cached, Offline | GitHub | How fresh the check is. It does not mean saved or published. |

## Meetings and the library

| Term | Definition | Do not use | Example |
| --- | --- | --- | --- |
| **Meeting** | One recording or one imported transcript, with its notes. | call, session | "Delete meeting" |
| **Conversation** | Any item in the Library list: a meeting, an email thread or a chat. | meeting (for email or chat) | "No conversations match." |
| **Library** | The area of all conversations on this Mac. | archive, history | "Library" |
| **Transcript** | The saved final text of a meeting. | captions | "Edit transcript" |
| **Live captions** | The temporary text while a recording runs. It is not saved as the transcript. | transcript | "Live captions" |
| **Meeting name** | The name of a meeting that you can change with Rename. | title (in the UI) | "Rename" |
| **AI title** | A meeting name that AI suggests. | generated name | "Generating AI title" |

## Actions and their results

| Term | Meaning | Do not use for it |
| --- | --- | --- |
| **Save …** | Save the named object, for example Save notes, Save draft, Save changes. Other unsaved edits on the page stay. | Apply (for a save) |
| **Cancel** / **Close** | Cancel discards edits; Close closes an editor without edits. | Dismiss |
| **Keep editing** / **Discard** | The two answers when you leave unsaved edits. | OK / No |
| **Delete** | Removes the object from this Mac. It cannot be undone. Name the object and the result. | Remove, Clear |
| **Remove** | Takes a row out of a list that you then save. | Delete |
| **Leave the team** | Ends a membership period. The history stays. | Delete person |
| **Reset filters** | Resets the filters and the task view. The search stays. | Clear all |
| **Clear all** | Resets the search, the filters and the views. "This is me" stays. | Reset |
| **Archive library** / **Restore from archive** | Make a checked archive; add the missing records from it. Existing records stay. | Backup / Import |

## Privacy terms

| Term | Definition | Do not use |
| --- | --- | --- |
| **Saved on this Mac** | The data stays in the local library. Nothing is sent. | local cloud, synced |
| **Configured API** | The AI address in Settings → AI. It can be on this Mac, in your network or on the internet. | local AI (unless the address is on this Mac) |
| **API model** | The model that the configured API uses. | local model |
| **Local Whisper** / **Local Parakeet** | Speech recognition that runs on this Mac. | local AI |
| **Sent to <host>** | Name the host that receives the text, for example "Transcript text is sent to api.example.com for notes". | "processed" (without the destination) |
| **Published** | Sent to GitHub, Gmail or another service after your approval. | saved |
| **Draft (Gmail)** | Saved in Gmail as a draft. Atlanta never sends the email. | sent |

## Open points for the review

1. **Domain review:** confirm "Received from" and "Followed by" with the people who use the task roles.
2. **Domain review:** confirm "Conversation" for email and chat items in the Library.
3. **Privacy review:** confirm the words for a configured API on the local network (on this Mac, in your network, on the internet).
4. **Privacy review:** confirm the text of the Maximum privacy profile.
