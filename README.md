# Bulgarian Meeting Assistant

An everyday meeting workspace for a Mac: record in-person or online meetings,
keep the audio, transcribe Bulgarian speech, and review editable meeting notes.

## Open the app

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

## Record an in-person meeting

1. Connect your iPhone as a macOS input device, or use the Mac microphone.
2. Enter a name, select **In person**, and choose the microphone.
3. Use **Test mic** for a ten-second level check. It does not save audio.
4. Click **Start recording**. **Pause** discards audio until you resume and removes
   the pause from the saved timeline.
5. Click **Stop & save**. The meeting appears in the library immediately; processing
   continues in the background when automatic processing is enabled.

For the iPhone: use the same Apple Account on both devices, enable Wi-Fi/Bluetooth and
Continuity Camera, and confirm **iPhone Microphone** appears under macOS Sound → Input.
A cable can help maintain a stable connection. The app does not run on the iPhone itself.

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

From a saved meeting you can:

- Play the recording or click a transcript timestamp to seek.
- Correct transcript text and manually label speakers, then **Save corrections**.
- Choose speakers from the shared list of known speakers. Known speakers show a coloured badge.
- Delete the meeting with **Delete meeting**. You can also delete its Google Calendar event.
- Edit summaries, decisions, tasks, owners, deadlines, and source timestamps, then **Save notes**.
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

Notes made before this version still open. Their new sections are empty, and their tasks are open.
Generate notes again to fill the new sections.

Click **✓ Tasks** in the sidebar to see the tasks from all meetings in one list. The badge shows
the number of open tasks, or the number of late tasks in red.

- Filter by **Open**, **Overdue**, **Done**, or **All**, and by owner.
- Mark a task as done, or change its due date. The change is saved in the notes of that meeting.
- Late tasks have a red mark. Tasks due today have an amber mark.
- Click the meeting name to open its notes.

The app shows reminders only to you, in the app. It sends nothing to task owners.

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

Click **Delete meeting** on a saved meeting and confirm. The app removes the meeting folder
with the recording, transcripts, notes, and versions. You cannot undo this. Make a copy
of the folder first if you are not sure.

If the meeting has a Google Calendar event, the app asks a second question. Choose OK to
delete the event too, or Cancel to keep it. The app deletes only the event that it created
for this meeting. If Google cannot delete the event, the meeting stays on this Mac.
You cannot delete a meeting while it records or processes.
The app validates notes' structure and source timestamps, but factual correctness still requires
review against the recording. See [benchmarks/README.md](benchmarks/README.md) for a repeatable
local-versus-cloud quality evaluation; no provider quality ranking has been established yet.

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
A bounded writer queue stops recording explicitly if disk IO cannot keep up. Microphone gaps,
disconnects, native helper exit, and PortAudio overflow become visible errors.

After an interrupted recording or job, reopen the app and select **Recover audio** to rebuild
a playable WAV from raw tracks. Then **Transcribe** to retry. Recovery works without a finalized
WAV header. Failed model/API jobs preserve audio and previous final transcripts. Retries currently
restart transcription rather than resuming partial chunks. Do not remove the raw tracks until you
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
