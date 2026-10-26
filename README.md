# Bulgarian Meeting Assistant

An everyday meeting workspace for a Mac: record in-person or online meetings,
keep the audio, transcribe Bulgarian speech, and review editable meeting notes.

## Open the app

### Native desktop app (Tauri, macOS Apple Silicon)

The desktop wrapper opens the existing interface in its own window and owns one Python server.
Closing the window or choosing Quit saves an active recording, stops live captions and exits the
server. If the window process crashes, a private pipe closes and asks the server to shut down too.
Reopening the desktop app focuses its existing window. It never replaces a running CLI server.
An unrelated process using port 8765 causes a startup error instead of being stopped.

Desktop data is separate from a source checkout, under
`~/Library/Application Support/io.github.bhadzhiev.meeting-assistant/`: `meetings/`, `models/`
and `backend.log`. Backend startup and runtime diagnostics are written to that log;
the private readiness URL is not logged. Use Archive/Restore to bring saved meetings into the desktop library.
Models download on first use. Local AI notes still use the independently running model server
configured in Settings. The desktop app does not stop that server.

Calendar meeting links currently open in the default browser, which does not share the desktop
window's session cookie. Opening such a link can show "Open the app using its launcher" even when
the desktop app is running. Open the meeting from the desktop library instead. Opening calendar
links directly in the desktop window needs a future deep-link integration.

For development, install Rust and run `scripts/run_desktop.sh`. It uses `.venv/bin/python` by
default; `BMA_PYTHON` selects another interpreter. `BMA_DATA_DIR` selects an isolated data directory.
The native audio helper must be built with `./build_native.sh` before testing online recording.

To build a `.app`, use a packaging virtual environment with the normal requirements and PyInstaller,
then install the Tauri CLI and run:

```sh
npm --prefix desktop ci
python scripts/build_desktop.py
```

The result is under `desktop/src-tauri/target/release/bundle/macos/`. Add `--debug` for a development
bundle. This packages Python, the web interface, Whisper libraries and the native audio helper.
By default, ffmpeg/ffprobe must be installed on the target Mac (`brew install ffmpeg`). To package
self-contained builds of those binaries, pass `--ffmpeg-dir <folder>`; check their redistribution
licenses. Optional pyannote diarization dependencies must be included and validated separately.

The initial build is for local testing. Distribution requires a stable signing identity,
notarization and real microphone/ScreenCaptureKit permission checks on the final signed bundle.
Force Quit and power loss still use the normal raw-audio recovery path. Interrupted AI jobs can
be retried after reopening. The desktop controller allows up to 90 seconds for normal shutdown,
then terminates only its own process group if it cannot finish.

Double-click **Open Meeting Assistant.command** in Finder. It opens the interface in
your normal browser; keep the launcher running while you record or process meetings.
Double-clicking it again stops the older copy and starts the updated app, so code changes take effect.

Requirements: macOS 13+ on Apple Silicon, Python 3.11+, ffmpeg, and Apple's Command Line
Tools (`xcode-select --install`). This version was built and tested on macOS 27.0.1.
The launcher creates a virtual environment on first use and builds the system-audio helper.
For a manual installation:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
brew install ffmpeg
./build_native.sh
.venv/bin/python desktop_app.py
```

The browser talks only to `127.0.0.1`. The server uses a random session credential,
checks request origins, and does not expose a network listener to other computers.
An API key can be supplied in Settings or through `OPENAI_API_KEY`. Keys entered in the
interface stay in process memory, are never returned by the API or stored in meeting files,
and can be forgotten in Settings. A key supplied in the environment is loaded again on restart.
Do not share the launch URL: it grants access to this local app session.

The tab does not ask the app for news every second. It keeps one connection (server-sent events), and the
app tells it when a meeting, the notes or the settings change; only then does the tab load data. During a
recording or a microphone test, the timer and the level arrive on the same connection. A hidden tab closes
the connection and loads the current state when you show it again. The microphone list is scanned only
while the new-meeting form is open.

## Record an in-person meeting

1. Connect your iPhone as a macOS input device, or use the Mac microphone.
2. Enter a name, select **In person**, and choose the microphone.
3. Use **Test mic** for a ten-second level check. It does not save audio.
4. Click **Start recording**. **Pause** discards audio until you resume and removes
   the pause from the saved timeline.
5. To mark a moment, press **1** (Important), **2** (Decision) or **3** (Check later), or click the
   buttons under the timer. Type a short note first if you want. Markers are saved in `markers.json`.
   After the meeting, **Moments you marked** at the top of the transcript plays each moment.
   Notes generation gets the markers as hints; the AI must still find the moment in the transcript.
6. Click **Stop & save**. The meeting appears in the library immediately; processing
   continues in the background when automatic processing is enabled.

For the iPhone: use the same Apple Account on both devices, enable Wi-Fi/Bluetooth and
Continuity Camera, and confirm **iPhone Microphone** appears under macOS Sound → Input.
A cable can help maintain a stable connection. The app does not run on the iPhone itself.

## Import audio from a phone or another app

In **Import audio or a transcript**, choose an audio file (.m4a, .mp3, .wav, .aac, .ogg, .opus,
.flac, .webm, .mp4, .mov, .caf, .aiff, .amr, .3gp; up to 4 GB) and click **Import file**.
The app converts it with ffmpeg into the same 16 kHz mono `recording.wav` that a recording makes,
then processes it with the current settings. The meeting date comes from the recording time in
the file (iPhone Voice Memos write it), else from the file's modification time.
The file name is the meeting name until an AI title replaces it. The meeting appears only after
the conversion succeeds; an interrupted upload leaves nothing behind.

## Record an online meeting

Choose **Online meeting** and your microphone. The app captures **all Mac system audio**
plus the selected microphone as independent tracks. Use headphones to avoid recording
remote voices twice through the microphone. Other Mac app sounds are included, so silence
unwanted notifications and avoid playing old recordings during capture.

System audio uses Apple's ScreenCaptureKit; no virtual audio driver is required. macOS may
request **Screen & System Audio Recording** permission for the launching app/helper.
Microphone capture also requires **Microphone** permission for the launching app/Python.
If capture is denied, grant permission in **System Settings → Privacy & Security**, quit
and reopen the launcher, then retry. The helper registers audio output only; it does not
save screen video. Capture cannot start on a Mac without an available display.

The app does not join meetings as a bot. It records what your Mac plays and what your
chosen microphone hears. ScreenCaptureKit reference:
[Apple capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos).

## Transcription and notes

**Audio preparation before final transcription** in Settings → Recording has two options:
**Off** (default, including older meetings) and **Light**. Light removes low-frequency rumble,
reduces steady noise gently, balances levels with gain capped at 2×, and limits output peaks.
It does not remove pauses, change speed or promise to repair clipped or reverberant speech.
Both local and cloud final transcription can use it; live captions are unchanged.

The original `recording.wav` and raw tracks stay unchanged. After successful transcription,
`transcription.wav` holds the prepared 16 kHz mono audio with exactly the same number of samples.
The playback selector switches between **Original recording** and **Prepared for transcription**;
both are downloadable from Files. Metadata records the profile and source. Switching Off and
successfully transcribing again uses the original and removes the prepared audio. The prepared audio
takes about 115 MB per hour and can be made again from `recording.wav`, so `versions/` keeps only the
metadata of an earlier preparation, and library archives leave `transcription.wav` out. A temporary
prepared file that a crash leaves behind is removed when the app starts.
If preparation or transcription fails, prior published output stays available and the temporary
prepared file is removed. Fix the cause or choose Off before retrying; there is no silent fallback.

For online recordings with both raw tracks, only the microphone gets rumble removal, denoising
and level balancing; system audio is resampled and mixed with it before the final limiter.
Imported or older recordings without both raw tracks use the saved mixed recording instead.
Processing is streamed through ffmpeg, so it does not hold the full recording in memory.

Synthetic tests check sample count, alignment, rumble reduction, silence, separate-track handling
and failure isolation. Recognition improvements on real Bulgarian meetings remain unmeasured;
compare both modes using `benchmarks/README.md` before choosing Light as your usual setting.

**Settings** controls the next recording and manual processing/retries. A recording keeps
the settings it started with for automatic processing.

- **Local transcription:** Whisper through pywhispercpp, Bulgarian language, no translation.
  Default `large-v3-turbo`; `large-v3`, `medium`, and `small` are also available. Models download
  into `models/` on first use. Expect about 1.6 GB for turbo and 3.1 GB for full large-v3.
- **Voice detection (VAD):** on by default. The final local pass uses the Silero model of
  whisper.cpp (under 1 MB, downloads into `models/` on first use) to skip silence. On silence,
  Whisper can invent text such as "Абонирайте се!"; VAD stops this and makes timestamps more exact.
  If the model cannot download, transcription continues without VAD and the reason is saved
  in `transcript.metadata.json`. Turn it off in **Settings → Recording**.
- **Hallucination filter:** the app removes known Whisper inventions (subtitle credits,
  "subscribe" and "thanks for watching" phrases) and loops where one phrase repeats four or more times.
- **Vocabulary:** enter names and terms in **Settings → Recording → Vocabulary for transcription**.
  Whisper gets them with the known speakers as a prompt. This helps with words such as Terraform
  or OIDC. A prompt makes Whisper timestamps unreliable, so the final pass then runs two times:
  the first pass gives the segments and timestamps, the second gives the words. The app aligns
  the words to the segments. If the two passes differ too much, the first text stays.
  Live captions use the same prompt and drop captions that only repeat it.
- **Cloud transcription:** sends recorded audio chunks to OpenAI; requires an API key and
  incurs API charges. Default model is `gpt-transcribe`, configurable in Settings. Cloud
  timestamps indicate approximate audio chunk boundaries, not word alignment. See the
  [official file-transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text).
- **Local notes:** uses the OpenAI-compatible API configured in **Settings → Local AI**.
  Defaults: `http://localhost:1235/v1`, model `qwen3.5-9b`. Click **Load available models**
  and enter a text/chat model ID exposed by your server. This one endpoint/model powers
  summaries, decisions, task extraction, open questions, and local meeting titles.
  Keep your model server running. It must accept unauthenticated requests on this endpoint.
  JSON schema is the default; choose JSON object or Prompt only if your server needs it.
  All modes still validate generated notes and task evidence timestamps before saving.
  Reasoning effort defaults to the server setting; choose **Off** for faster extraction
  when the server supports `reasoning_effort`. The shared maximum output defaults to
  4096 tokens (including reasoning on many servers). Truncated responses are rejected.
  Local requests allow up to 10 minutes for slower inference.
  Requests never fall back to a cloud provider. A remote base URL sends transcript text
  to that server; use localhost to keep text inference on this Mac.
  Live captions and local final transcription continue using Whisper.
- **Cloud notes:** sends transcript text to OpenAI. Default `gpt-4.1-mini`, configurable.
- **No notes:** saves the transcript only. Generate notes separately later.

The recording screen includes a **Live transcript**, enabled by default. Local Whisper
updates provisional text approximately every 2.5 seconds of new audio plus inference time,
then commits phrases after a pause or a 12-second window. The interface refreshes once per
second and follows new text unless you scroll up. Online captions include the Mac audio
track as well as the microphone. Pausing flushes the current phrase; resuming continues
on the same timeline.

Live captions always run locally, including when cloud final transcription is selected.
Choose their Whisper model in Settings and use **Show live transcript while recording**
to enable/disable them for the next meeting. On first use, model downloading/loading delays
the first captions. `large-v3-turbo` is the default; slower hardware may need `medium` or
`small`. Actual delay has not been benchmarked on real meeting audio. The UI shows a
catch-up indicator if processing falls behind.

Caption inference runs in a separate process and reads bounded snapshots of already-saved
audio. A caption failure does not stop recording. Live drafts are saved separately as
`live-transcript.json` and `live-transcript.md`; `live.json` holds current display state.
Final transcription still uses the full saved recording and does not overwrite the draft.
If recording stops while captions are far behind, final processing covers the remaining audio.
The worker has up to 15 seconds to finish before the app ends it to release model memory. Live and final processing share one model slot so model jobs do not compete for memory.
Capture uses a separate disk-writing thread and does not wait for transcription.
Long audio is processed in bounded chunks, preferring a quiet boundary near each split.
Long transcripts are summarized in parts; notes retain their part order rather than inventing
an overall synthesis. Local and cloud jobs preserve the prior final transcript until success.

The meeting header shows one button for the next step (for example **Transcribe** or
**Generate notes**). The other actions are in **More ▾**, and the saved files are in **Files ▾**.
The tabs stay at the top of the window when you scroll.

From a saved meeting you can:

- Play the recording or click a transcript timestamp to seek.
- Read the notes as lists. Click a timestamp in the notes to see that moment in the transcript.
- Tick a task as done directly in **My Work**.
- Correct transcript text and manually label speakers, then **Save corrections**.
- Choose speakers from the shared list of known speakers. Known speakers show a coloured badge.
- Delete the meeting with **More ▾ → Delete meeting**. You can also delete its Google Calendar event.
- Click **Edit** to change summaries, decisions, tasks, owners, deadlines, and source timestamps, then **Save notes**.
- Search meeting names and saved transcripts, rename a meeting, and export audio/Markdown/JSON/SRT.
- Transcribe again with the current settings or generate notes independently.

### Conversation analytics

Saved meetings have an **Analytics** tab for talk time, topic evidence, and questions.
The sidebar's **Conversation analytics** view aggregates those results across meetings,
with date, speaker, and topic filters. It reports descriptive statistics, not employee
scores, and does not perform sentiment analysis.

- **Offline speaker diarization and talk time.** After transcription, optional
  `pyannote/speaker-diarization-community-1` processing creates `speaker-timeline.json`.
  Whisper segments receive the speaker with the greatest timeline overlap, with midpoint
  fallback. Talk time is calculated from merged speaker intervals, not transcript lengths;
  silence is excluded. The view includes turns, talk percentage, longest monologue,
  average turn length, and question count. Overlapping intervals for the same speaker are
  merged first. Simultaneous speech by different speakers counts toward each speaker.
- **Speaker renaming.** Changing a generic label such as `SPEAKER_00` to a person's name
  updates every matching segment and timeline interval in that meeting, then rebuilds its
  analytics. Generic IDs are not assumed to represent the same person in other meetings.
- **Topic trackers.** Manage shared trackers in **Settings → Topic trackers**. Literal
  phrases match locally and case-insensitively, with timestamped transcript evidence.
  Optional semantic matching uses only the configured Local AI endpoint and validates every
  returned segment ID. There is no cloud fallback. If semantic matching fails, literal hits
  remain available and the meeting shows a separate analytics warning.
- **Question detection.** Deterministic Bulgarian and English cues and question punctuation
  identify questions, including Bulgarian questions without `?`. Answers are never inferred;
  mark questions answered manually. Reanalysis preserves answered state where the stable
  question identity or its evidence still matches.
- **Cross-meeting analytics.** Aggregates talk seconds, turns, questions, unanswered
  questions, topic hits, and longest monologues. JSON results are cached by file modification
  time. Meetings without analytics are omitted until you open them and choose **Reanalyze**.

Diarization is optional and is not required for recording, transcription, or notes. To enable
its model, install the extra dependencies in the app's virtual environment and provide a
Hugging Face token through the environment (never in meeting settings or files):

```sh
.venv/bin/python -m pip install -r requirements-diarization.txt
export HF_TOKEN=your_hugging_face_token
```

Accept the model's access conditions on Hugging Face if requested. The first model load may
download model files. Processing uses Apple MPS when available and otherwise CPU. Diarization
or analytics failures do not mark an otherwise successful transcript/notes job as failed.
Imported transcripts receive topic and question analytics but no invented talk-time data.
Real meeting diarization accuracy and MPS inference have not been measured by the automated
suite; verify a short recording before relying on speaker statistics.

### AI correction of the transcript

After you stop a recording, processing runs in this order: Whisper transcription,
optional diarization, AI correction, notes, analytics, then any calendar automation. Set the provider in **Settings → Recording → AI correction after
transcription**: **Local · Configured API** (default), **Cloud · OpenAI**, or **Off**.

- The model fixes spelling, punctuation, capital letters, and words that were heard wrong.
  It uses the known speakers for the spelling of names.
- Timestamps and speaker labels never change. The model gets numbered segments and must return
  the same segments. If it does not, the correction stops and the Whisper text stays.
- A segment that changes too much keeps the Whisper text. The limit is a similarity below 60 %
  or a length change of more than −40 % / +50 %. The transcript tab shows how many changes
  the app refused.
- The app keeps the Whisper text in `transcript.raw.json`. Corrected segments have a green mark
  and an **AI ↺** button. Hover over the button to see the original. Click it to restore the
  segment, then click **Save corrections**.
- If the correction fails, processing continues with the Whisper text, and the meeting shows
  the reason. Click **AI-correct transcript** to try again. A manual run corrects the current
  text, including your own corrections.
- Cloud correction sends the transcript text to OpenAI and uses the cloud notes model.

A test with `qwen3.5-9b` on a short Bulgarian sample took 8 seconds. It fixed spelling,
punctuation, and names, but it missed one misheard word. Long meetings take longer.
Correction quality on real meeting audio has not been measured.

### Meeting notes and task tracking

A saved meeting has four tabs: **Transcript**, **Tasks & decisions** (decisions, tasks,
unresolved questions, agreed next steps), **Summary & notes** (summary, questions for
your decision, private observations), and **Analytics**. Generated notes contain these sections:

- **Summary** and **Decisions**.
- **Next steps:** agreed process steps, for example a follow-up meeting.
- **Questions for your decision:** items that wait for a decision and were not decided.
- **Tasks:** task, owner, deadline as said, due date, status (open or done), and source timestamp.
  The model receives the meeting date. It converts a deadline such as "до петък" into a due
  date when the date is clear. Otherwise the due date stays empty. You can set it yourself.
- **Open questions.**
- **Private observations:** risks, promises that look unrealistic, and signs of disagreement.
  This is an AI interpretation. Check it against the recording. It is not in `minutes.md`,
  but it is in `minutes.json`.

Every statement in the notes (summary, decisions, next steps, questions, observations) and every
task has a **source moment** and a **review state**:

- The source shows the exact transcript segment and its speaker. Click **▶ 00:12:03** to play only
  that segment, or click the quote to see it in the transcript. Without audio, the click opens the transcript.
- **AI suggestion** means nobody has checked the statement. Click it after you check the source; it
  becomes **✓ Checked**. Statements that you add yourself start as checked.
- The AI must cite the moment where a decision was taken, not where it was proposed.

**Generate new AI notes** never replaces saved notes. The new result waits as a proposal, and
**Review changes** lists each new, changed, or missing statement or task. New and changed items are
preselected; removals and changes to checked statements are not. **Apply selected** keeps task status
and saves the previous notes in `versions/`. A changed statement needs a new check.

Notes made before this version still open. A source written in the text, such as "(00:12:03)",
becomes the source moment. Other old statements show "No source moment" until you generate new notes.
Notes made before the task tracker still open. Their new sections are empty, and their tasks are open.
Generate notes again to fill the new sections.

Click **✓ My Work** in the sidebar. Each task and decision appears **once**, however many
meetings discussed it. Filter by project, owner and status. Snooze or dismiss an item without changing
its task or decision status; use **Snoozed** or **Dismissed** to bring it back. **In force** shows only
accepted decisions. **Sources** keeps earlier meeting-note wording, separate from the current item text.
These are note snapshots, not independently verified transcript quotations.

The app keeps the registry in `meetings/work-items.sqlite3`, with:

- a permanent ID and the current state (text, owner, deadline, due date, status);
- links to every meeting that discussed it, with the source moment;
- a history: created, discussed again, changed (old → new), merged, replaced — by you or by the AI.

On first launch, the app migrates `items.json` and keeps `items.before-sqlite.json`. IDs, history and
manual edits survive. `items.json` remains a generated portable export; do not edit it by hand.
A stale edit from another window is rejected; cancel the editor to load the newer version.
Migration copies and archives retain earlier data until you remove those copies.

The [work assistant contract and implementation tasks](docs/work-assistant-contract.md) describe
the next stages. This foundation supports meeting tasks, decisions and questions.
The Gmail, Google Chat and GitHub read-only pilots are described below.

**Suggested** stores source-backed proposals separately. **Accept** creates an item; **Link** attaches
the quote to an existing item of the same kind without changing its text, owner or status. Dismiss,
Snooze and Restore keep proposals reachable. A changed or unavailable source blocks acceptance of
its older proposal. **All** includes reviewed and stale proposals. Reprocessing an identical revision
does not create another proposal or reset a dismissal. Automatic extraction from Gmail or Chat is
not enabled yet.

**Questions** holds personal open questions and questions accepted from proposals. Add a question,
save an answer, or reopen it; the earlier answer stays in its history. Existing meeting-note open
questions are not automatically imported into this list. Suggested and Questions cover all sources,
independent of the meeting project filter. For source-linked items use Dismiss instead of Delete;
proposal Link adds sources without merging away IDs or history.

Example: "Test the SAP permissions" is created on 19 Oct; on 23 Oct a meeting says "до петък", the due
date changes, and the task stays open. The history shows both meetings.

**New AI notes and existing items.** When new notes mention something that looks like an open task or a
decision in force, nothing is linked automatically. **To review** cards (in this view and in the meeting)
ask you to choose:

- Tasks: **Same task · update** (new owner, deadline and due date fill the fields that you did not edit),
  **Duplicate** (link only), or **new task**.
- Decisions: **Same decision**, **Replaces it** (the older decision becomes *Replaced*), or **new decision**.

**Transcribe again** replaces the notes of a meeting, but not its tasks and decisions. They keep their
identity, status, manual edits and history, and wait for the new notes of the meeting: the same text links
again by itself, and similar text shows a review card, also for a task that is done.

The state of a task or decision is one value: a change in any meeting's notes, in this view or in Prepare me
reaches the notes of every meeting that mentions it. A decision whose text the AI changes is proposed again
until you check it.

The match is a text comparison of word stems and wording, not AI; a missed match can be fixed with
**Merge…**, which keeps both histories. The AI never changes a status or a field that you edited.

Decisions are **Proposed** until you accept them (checking a decision against its source also accepts it),
**Accepted**, or **Replaced** by a newer decision. **Restore** brings a replaced decision back.

- Filter tasks by **Open**, **Overdue**, **Done**, or **All**, and by owner; filter decisions by state.
- Mark a task as done or change its due date. The status also changes in the notes of every linked meeting.
- **Delete** removes the item from the notes of every meeting that mentions it.

The app shows reminders only to you, in the app. It sends nothing to task owners.

### Projects, series and Prepare me

Group meetings into **projects** (for example "DevOps" or "Client X") and recurring meetings into a
**series** inside a project (for example "Weekly sync"). On a saved meeting, click **＋ Add to a project**
under the title; choose an existing project and series or type a new name. A new recording can start in
a project and series from the **A new meeting** form. The sidebar filter shows the meetings of one project.
Manage names in **Settings → Projects**; deleting a project or series never deletes meetings.

**☰ Prepare me** (or **Prepare the next meeting ›** on a meeting) shows, for a series or a whole project:

- **Proposed agenda:** overdue tasks, questions that need a decision, open questions, tasks due in the
  next 7 days, tasks without an owner or date, proposed decisions to confirm, and moments marked
  "check later" in the last meeting. **Copy as text** copies it for an invitation or a chat.
- **Open tasks** with owner, due date and the meeting where they were last discussed.
- **Questions without a decision** from the last three meetings. A question asked again shows once,
  with its newest source. A question that a later accepted decision may answer is marked, not hidden.
- **Decisions in force:** accepted decisions, newest first, plus proposed decisions not confirmed yet.

Every line links to its meeting and moment. Prepare me uses saved notes, tasks, decisions and markers;
it does not run the AI again. Projects and series are stored in `meetings/projects.json`.

### Search and ask

**⌕ Search & ask** (or press **Enter** in the sidebar search box) finds the **passage**, not only the meeting:
transcript segments with speaker and time, statements in the notes, markers, meeting names, and tasks and
decisions with their current status. Matches are highlighted, and each result opens its meeting at that moment.

- Words also find their other forms: words of six letters or more match by their first five letters, so
  "резервния" finds "резервен". Put "exact words" in quotes to find a phrase.
- Filter by **Decisions**, **Tasks**, **Notes** or **Transcript**, and by project.
- The index is `meetings/search.db` (SQLite FTS5). It updates itself on the next search after a meeting
  changes. It is derived data: archives leave it out, and the app builds it again when it is missing.

**Answer from sources** answers a question such as "Какво решихме за резервния интернет?":

1. At once, without AI, it shows whether a **confirmed** (accepted) decision matches, and lists proposed
   decisions that are not confirmed. If there is none, it says **No confirmed decision found**.
2. Then the notes provider (**Settings → Notes & AI**) writes a short answer from the 12 best passages only.
   It must cite them; an answer without valid citations is not shown. For a decision without a confirmed
   source, the model starts with „Не намирам потвърдено решение.“

A local model can take several minutes; the answer shows the time and a **Stop waiting** button. A local
model server may still finish a request after you stop waiting, before it starts the next one.
With "Local · Configured API" notes, the question and passages stay on this Mac.

### Known speakers

The app keeps one list of known speakers for all meetings in `meetings/speakers.json`.

- Manage the list in **Settings → Known speakers**. Add or remove names there.
- When you save transcript corrections, new speaker labels are added to the list.
- Speaker and task-owner fields suggest the known names.
- A known speaker gets a coloured badge with initials. The colour is the same in all meetings.
  A label that is not yet known shows **NEW**. The transcript header shows each speaker and
  the number of segments.
- Notes generation receives the list. The model uses these exact spellings for task owners
  when the transcript names the person. The list alone does not make a person a participant.

### Delete a meeting

Click **More ▾ → Delete meeting** on a saved meeting and confirm. The app removes the meeting folder
with the recording, transcripts, notes, and versions. You cannot undo this. Make a copy
of the folder first if you are not sure.

If the meeting has a Google Calendar event, the app asks a second question. Choose OK to
delete the event too, or Cancel to keep it. The app deletes only the event that it created
for this meeting. If Google cannot delete the event, the meeting stays on this Mac.
You cannot delete a meeting while it records or processes.
The app validates notes' structure and source timestamps, but factual correctness still requires
review against the recording. See [benchmarks/README.md](benchmarks/README.md) for a repeatable
local-versus-cloud quality evaluation; no provider quality ranking has been established yet.

## Gmail: local read-only pilot

Open **My Work → Gmail → Connect Gmail read-only**. Use the shared Google connection and approve
`gmail.readonly`. Calendar permission is requested only if already used or separately connected.
This desktop OAuth flow requests the complete selected scope set again; it does not use incremental
authorization. Tokens stay in macOS Keychain. Enable the Gmail API for the app's OAuth project;
Workspace admin policy, OAuth testing users or restricted-scope verification can block access.
See [desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) and
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

Choose **Refresh connection**, then **Sync / Continue**. Each run handles one page of up to 20 threads.
The first sync covers up to 200 threads with Inbox/Sent activity in the preceding 30 days. Continue
until the status says synced. A limit message means the initial window is incomplete. Subsequent runs
use Gmail history; an expired history cursor asks you to start a bounded rebuild. Recording/processing
pauses further work, and Cancel stops before the next cache commit. A network request already in
flight can take up to its 30-second timeout; it does not hold recording controls.

**Needs reply** means the latest non-draft message is incoming; **Waiting for** means it is sent.
These are direction-based candidates, not AI judgments that someone owes a reply. Open a thread to
read its cached text and fetch time. HTML becomes plain text; remote images, scripts and attachments
are not fetched or rendered. A thread includes at most its latest 100 non-draft messages and local
size limits apply. Matching threads can contain older messages. This version does not send, modify,
label or draft email. Email content reaches an AI endpoint only through the selected-message approval below.

**Suggest a task from this message** saves a manual proposal with a pinned source quote. Review it
in Suggested, then Accept or Link. It does not extract commitments or dates automatically. Syncing a
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

**Load spaces** fetches conversation metadata only. It reads at most 50 spaces per page and 200 per
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

**Suggest a task from this message** creates a manual proposal with an exact quoted message and
space/thread/message/sender references. Review it in Suggested, then Accept or Link to an existing
item. This never sends or edits a Chat message. Cards, attachments and remote resources are not
fetched or executed. Chat content is not sent to AI in this delivery; Gmail AI approval does not
cover Chat. Quotes and known versions reflect the last observed API response, not a live check at
the moment of acceptance.

`chat-cache.sqlite3` is a rebuildable local cache excluded from library archives. Partitioning uses
the verified Google user ID, so an email rename keeps the same cache. **Clear local Chat cache**
can remove a cached identity after sign-out and keeps promoted WorkItem snapshots in the graph and
archives. There is no automatic retention purge. All development tests use synthetic Chat responses;
live Workspace consent, API access and real conversation sync still need account-owner validation.

## GitHub: selected repositories, read-only

Open **My Work → GitHub**. Create a **fine-grained personal access token** for the selected repositories
with **Issues: Read-only**, **Pull requests: Read-only** and the required metadata access, then Connect.
The app verifies the account with GitHub and stores the token in a separate macOS Keychain entry.
It does not reuse `gh` credentials or environment tokens. The token input clears after submission;
status, settings, archives and command arguments never include it. Token creation, organization
approval and SSO remain GitHub/account-owner setup. See
[GitHub token permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
The app cannot introspect all token permissions; its own adapter only makes GET requests.

Enter **owner/repository**, select **All**, **Assigned to me**, **Created by me** or **Mentioned**, then
**Sync / Continue**. Each action handles at most 20 search matches and at most 200 per repository/filter
refresh. Each filter has its own cached result set and restartable queue; choose Issues/PRs to narrow
the display. Search qualifiers handle mentions, including indexed comments, instead of guessing from
cached body text. Search indexing can lag or report incomplete results. This is not a full mirror,
a transactionally frozen GitHub search or a webhook subscription; absence from the capped results
never proves deletion. **Restart filter refresh** starts a new result generation, preserving sources.

Open an item to read its cached Markdown as plain text and fetch time. PR states distinguish open,
closed without merge and merged; the PR detail is checked separately from the issue representation.
The cache uses the issue database ID returned by the Issues API for both issues and PRs, with the PR
ID retained separately. These IDs differ, as noted in
[GitHub's issue API](https://docs.github.com/en/rest/issues/issues). Stable source IDs survive repository
renames, although redirects are deliberately not followed with credentials: enter the current
repository path and restart its refresh. Login changes during a page sequence also need a restart.

**Suggest a task from this issue / PR** stores a quote and repository/number/kind references in
Suggested. Accept creates a new open local task; Link attaches evidence and preserves existing human
fields/status. GitHub remains authoritative for the remote issue/PR state. A close or merge never
silently completes or reopens the local task. Observed source changes invalidate older pending
proposals; individual **Refresh this issue / PR** rechecks the object. Access loss blocks new
acceptance and clears cached text; historical quotes remain. Rate limits halt without inferring
that the repository was deleted. There are no GitHub writes, AI exports, comments, diffs, code reads
or automatic task executions in this pilot.

The indexed `github-cache.sqlite3` is per verified GitHub user ID and excluded from library archives;
promoted sources remain in the portable WorkItem graph. Lists show at most 200 matches for the current
filter generation. Cache records can accumulate across filters/refreshes until cleared. Clear cache
can remove an old identity after disconnect and keeps source snapshots/archives. **Disconnect locally**
removes the local Keychain credential; revoke the token separately on GitHub if needed. Cancelling,
recording/processing and account changes stop further work, with an in-flight request taking up to
30 seconds. No automatic background sync, OAuth app registration or GitHub Enterprise host is supported.

Tests use synthetic GitHub data and an in-memory token store. Real token permissions/organization
approval, live repository behavior and actual Keychain prompts still need account-owner validation.

## Archive and restore the library

**Settings → Backup → Archive library now** writes `meetings-<date>-<time>-<unique suffix>.tar.gz` into
`~/Documents/Meeting Assistant Backups` (change it with `desktop_app.py --backups <folder>`).
The archive holds every meeting folder (audio, transcripts, notes, markers, `versions/`), known speakers,
topic trackers, projects, the task and decision registry and settings, plus a manifest with the size and SHA-256 of each file. A recording in
progress, a meeting being processed, or a meeting with a live-caption writer is left out. The archive
records these exclusions. A short lock pins a snapshot of the selected files; compression runs after
that lock is released. This requires a library filesystem that supports hard links, such as APFS.
The snapshot protects app writes that replace files atomically; external tools that modify files in
place are outside this guarantee. The portable registry is `items.json`, including questions, pinned source revisions, quotations,
proposals, relationships and activity. Restore keeps existing local records authoritative. Source
quotes and earlier message revisions remain local until their library or archive copies are removed.
Live SQLite and WAL files
are not copied into the archive.

After writing, the app runs a **restore test**: it extracts the archive into a temporary folder,
compares every file with the manifest, and opens the folder as a library with every meeting.
Only an archive that passes is kept; the list shows the result.

**Restore** checks the archive the same way, then adds the meetings that the library does not have.
It never changes existing meetings or your settings; it adds missing known speakers and topic trackers.
A meeting that was busy when it was archived comes back as interrupted.
Keep a copy of the archives on another disk: an archive on the same Mac does not protect against disk loss.

## Durability and recovery

Every meeting has a private directory under `meetings/`:

```text
meetings/<meeting-id>/
  meeting.json                  # title, settings, status, errors
  capture.json                  # sample rates, timeline checkpoint
  microphone.pcm                # continuous native-rate 16-bit mono audio
  system.pcm                    # online meetings, 48 kHz 16-bit mono
  recording.wav                 # mixed, filtered/resampled 16 kHz mono
  live-transcript.json / .md     # preserved near-real-time draft
  live.json                     # caption state / provisional text
  transcript.json / .md / .srt
  transcript.metadata.json      # provider/model and timestamp precision
  transcript.partial.json       # completed chunks from the latest attempt
  minutes.json / .md            # when enabled
  speaker-timeline.json         # optional offline diarization intervals
  analytics.json                # talk time, topics, questions
  versions/                     # previous transcripts/notes/analytics when re-transcribing
```

Shared topic trackers are stored in `meetings/trackers.json`.

Raw tracks are written continuously and synced approximately every second. A crash may lose
the in-flight callback/queue; abrupt power failure can lose the latest unsynced data. The app
never promises zero loss. No entire-meeting audio array is retained in memory during capture.
A bounded writer queue stops recording explicitly if disk IO cannot keep up. A temporary microphone
input overflow keeps recording and shows a warning: some audio was lost and gaps may be present.
The overflow count is saved in `capture.json`. A disconnected or inactive microphone, or no callbacks
for five seconds, starts microphone recovery. Recording keeps its clock and saved audio; the missing
microphone interval is silence and appears as a playable gap in the meeting. The app retries the
selected device by name, including after device renumbering. It never guesses between duplicate names.
Choose **Backup microphone** before starting if the app may use another input; no backup is selected
automatically. The backup must accept the original recording sample rate. Online system audio keeps
recording during microphone recovery. If no microphone reconnects, the app can keep recording silence:
check the visible warning and input level. The desktop title and Dock attention signal also warn of
missing input. Disk writer errors, native system-audio helper exit and other capture errors still stop
recording and preserve audio.

While recording, macOS idle sleep is inhibited with a recording-scoped `caffeinate` process. This does
not override lid closure, explicit sleep, power loss or iPhone Continuity rules. USB and a locked iPhone
are useful checks when troubleshooting wireless capture. Unlocking or answering a call can pause the
iPhone microphone: [Apple Continuity Camera](https://support.apple.com/102546).

Notes use smaller transcript parts. If the local endpoint starts a JSON answer but truncates it,
notes and transcript correction can split the failed part, with at most two splits per attempt.
A model that exhausts its budget without starting an answer needs a different reasoning/output
setting; the app does not repeat it through split requests. Completed, validated notes parts are
saved in `.notes-progress.json` until the run succeeds. Retrying notes reuses them only when the
transcript, model settings, speakers, date and markers match. Saved notes stay unchanged on failure.
Transcript correction does not yet resume completed parts.

### Processing controls and recovery

The launcher runs heavy steps in separate Python workers. **Cancel processing** removes a queued job
or terminates its worker and owned conversion processes without stopping a recording. API keys cross
a private pipe and are not written to job files or command arguments. A parent-death guardian prevents
orphan workers even while native inference holds Python's interpreter lock. Already completed outputs
can remain after cancellation. A remote or separately running model server may continue a request
after its client disconnects; the app does not terminate that server.

The meeting shows elapsed time, queue wait and stage timings, including model loading, audio
preparation and speech inference where available. The transcription estimate applies only to the
remaining audio in the current pass, not later correction or notes. An AI HTTP request's timing includes
any queueing inside that server; the app cannot observe its internal model-load time.

When processing is requested while another meeting has live captions, captions stop and save their
draft to release the single model slot. Durable audio capture continues. Captions do not automatically
restart in that recording. This prioritizes completion of saved meetings without loading more models
at the same time.

Finished transcription chunks are saved in `.transcription-progress.json`. Retry checks the audio
content hash, provider, model file metadata, vocabulary, voice-detection state and preparation profile,
then resumes from the exact saved sample boundary. Legacy partial files without that fingerprint are
not reused. Changed inputs or malformed checkpoints start a fresh pass. Original audio and previous
final output remain available while the retry runs. Checkpoints are removed after successful publication.

**Use faster local settings** selects `large-v3-turbo`, disables live captions, transcript correction and
speaker diarization, and turns reasoning off for Qwen 3.5. It leaves the notes provider unchanged.
Review the fields and save to apply; an update does not silently replace existing preferences.

The native close button, app-menu Quit and Cmd+Q ask **Stop & quit / Keep recording** while recording.
The dialog is attached to the window. System termination, Force Quit and Dock Quit may bypass that
dialog; the backend's parent-EOF path still attempts to save audio. A backend crash shows
**The local server stopped. Restart the app.** instead of launcher advice. Backend logs rotate at
startup above 10 MB; each processing log rotates between steps above 5 MB. A long individual run can
still exceed those sizes.

For faster processing, start with `large-v3-turbo`, disable live captions if you do not need them,
and turn off transcript correction and speaker diarization unless you need those extra stages.
For the default Qwen model, try **Reasoning effort → Off** in **Settings → Notes & AI**;
the server default can spend the output budget on reasoning before producing JSON. Other endpoints
may require **Server default** for compatibility. These are explicit settings; updates do not replace
your saved choices. Measure transcription quality on your own speech before choosing a smaller model.

After an interrupted recording or job, reopen the app and select **Recover audio** to rebuild
a playable WAV from raw tracks. Then **Transcribe** to retry. Recovery works without a finalized
WAV header. Failed model/API jobs preserve audio and previous final transcripts. Retries resume
compatible completed transcription chunks. Do not remove the raw tracks until you
have checked the recording. **Delete meeting** removes all files of a meeting permanently.

The library is independent of the original CLI's `output/` folders; those can still be reprocessed
with the CLI. Existing CLI folders are not automatically imported.

## Legacy CLI

```sh
.venv/bin/python meeting_assistant.py devices
.venv/bin/python meeting_assistant.py record --device 2
.venv/bin/python meeting_assistant.py record --no-final --summarizer local
.venv/bin/python meeting_assistant.py finalize output/my-meeting/recording.wav --summarizer local
```

The CLI provides near-real-time draft captions and a final accuracy pass. It now uses the
same independent durable microphone writer. If inference cannot keep up, draft captions may
skip audio while the raw recording continues. The final pass uses the complete saved audio.
CLI live resampling/energy gating remain the original lightweight implementation; the desktop
app's saved/transcription audio uses ffmpeg filtering and resampling. `--no-final` still permits
notes from the live draft. Online capture is available through the desktop interface.

## Verification

```sh
.venv/bin/python -m unittest -v
```

Tests cover live provisional revisions, phrase commitment, pause/stop flushing, online audio inclusion, model failure isolation, filtered live resampling, synthetic capture/mixing, pause handling, bounded queues, interruption recovery,
library search, full mocked recording/transcription/edit lifecycle, chunking, output validation,
cloud failures, HTTP authentication/origin checks, and playback byte ranges. Analytics tests
cover overlap/silence calculations, Bulgarian questions, topic evidence, invalid semantic IDs,
speaker renaming, idempotent reanalysis, failure isolation, and cross-meeting filters. The native
Swift helper is compiled separately with `./build_native.sh`.

The automated suite does **not** establish real iPhone stability, granted macOS permissions,
ScreenCaptureKit track alignment on real calls, real pyannote diarization quality/MPS execution,
Bulgarian recognition quality, or paid cloud
API access. Run a short test in each mode, then a longer meeting before relying on the app.
Ask participants before recording and protect the saved audio and transcripts.

## Automatic AI titles and Google Calendar

Leave the meeting name blank to let AI name it from the final transcript (or the saved
live draft when final processing is disabled/unavailable). Names you type are preserved.
In **Settings → Automatic meeting titles**, choose **Local · Configured API** or **Cloud · OpenAI**.
Local titles use the shared Local AI model; cloud titles have their own model setting. Title generation is independent of meeting notes; it works when notes are off.
Cloud titles send bounded transcript excerpts to OpenAI. If the model is unavailable or
there is no recognized speech, the original name remains and the meeting shows the reason.
Use **Generate AI title** on a saved meeting to retry or explicitly replace a manual name.
You can always use **Rename** afterward. Manual edits made while AI is running take priority.

To connect a calendar:

1. Open **Settings → Google Calendar** and click **Sign in with Google**.
2. Sign in and allow Calendar access in your browser. Then return to the app.
3. The app selects your primary calendar. Choose a different **Destination calendar** if
   necessary. Only calendars with writer/owner access appear.
4. Enable **Add every new meeting to this calendar** and click **Save settings**.

Use **Switch Google account** or **Sign out** to change the account. The app keeps tokens
in **macOS Keychain**, not in meeting or settings files.

**One-time app owner setup.** Google requires an OAuth client for each app, also for
"Sign in with Google". Do this one time for your copy of the app:

1. In a Google Cloud project, enable **Google Calendar API**.
2. Configure the OAuth consent screen. Add your accounts as test users, or publish the app.
3. Create an **OAuth client ID** of type **Desktop app** and download its JSON.
4. Save the JSON as `google_oauth_client.json` in the project folder, next to `desktop_app.py`.
   As an alternative, set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
5. Restart the app.

After this setup, people only click **Sign in with Google**. The file is in `.gitignore`.
For a Desktop app client, Google does not treat the client secret as confidential.
**Settings → Google Calendar → Advanced** still accepts a client JSON file. A client
imported there has priority over `google_oauth_client.json`.

The app requests calendar-list read access and calendar-event write access. It uses desktop
OAuth with a loopback callback, PKCE S256, expiring single-use state, and background refresh.
Google test-mode credentials or Workspace policy may require reconnecting later. Details:
[Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) and
[Google Calendar event creation](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).

After a recording is saved, the app creates a historical calendar event using the actual
start/end wall-clock times, including pauses. Google receives the **title, time, and local
meeting link**; this integration does not upload the audio, transcript, notes, or API keys.
If an AI title is still pending, the event initially uses the current name, then updates.
No attendees are added, no invitations or reminders are requested, and the event is marked
as not blocking availability. Visibility follows the destination calendar's settings.

Links look like `http://127.0.0.1:8765/?meeting=<id>`. They open the saved meeting **on this
Mac only**, while the app runs at that address. They contain no app session credential.
Open the launcher first if the app is closed or this browser is not yet connected; then
open the calendar link again. Links are not public sharing links and will not open the
recording from your phone or another computer. Keep the normal app port (8765) for stable links.

Calendar events use a stable ID and app ownership marker. Retries, AI title updates, and
renaming update the same event. Each meeting keeps its original calendar/account binding;
changing the default calendar affects future meetings. If another Google account is
connected, the app refuses to update an event bound to the old account. Existing events
are never moved or deleted automatically. They are deleted only when you delete the meeting
and confirm the event deletion.

To add older recordings after configuring the destination, click **Sync saved meetings**
in Settings, or **Sync to Google Calendar** in a saved meeting. Repeating either action
updates existing events instead of creating duplicates. Normal recording/processing
status is separate from calendar/title status. Failed calendar writes are retained with
an error and retried up to three times (after 1, 5, and 15 minutes), including after an app
restart. The meeting's sync button provides an explicit retry. **Sign out** removes local
user tokens and attempts Google token revocation; the client configuration remains.

Google OAuth, token refresh, event writes, conflict handling, account changes, AI naming,
and browser deep links are tested with isolated fakes. The production connection and
macOS Keychain prompts require your actual client JSON, Google sign-in, and chosen calendar;
no live event creation has been verified as part of this setup.
