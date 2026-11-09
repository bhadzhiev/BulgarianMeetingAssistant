# Transcription, AI notes and analytics

## Transcription and notes

**Audio preparation before final transcription** in Settings → Recording has three options:
**Off** (default, including older meetings), **Light** and **Strong**. Light removes low-frequency rumble,
reduces steady noise gently, balances levels with gain capped at 2×, and limits output peaks.
Strong replaces the gentle denoiser with RNNoise (FFmpeg `arnndn`, the "leavened-quisling" model for
voice in a noisy room, about 300 KB, downloaded into `models/` on first use at a pinned revision).
It removes more fan, traffic and room noise, but it can also change voices. In a synthetic check
with one Bulgarian sentence, Strong lowered word errors with fan-like noise and raised them with
white noise. Whisper is trained on noisy speech, so compare Original and Prepared audio and the
transcript on your own recordings before you keep Strong. Without its model, Strong stops with a
clear reason; it never changes to another profile silently.
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
  Live captions and Parakeet use the ONNX release of the same Silero version (v5.1.2, about
  2.3 MB, through `onnxruntime`). Live captions send only the detected speech to Whisper instead of
  everything above a loudness threshold, so steady noise no longer starts a caption. With Silero, a
  short answer that only repeats vocabulary terms (for example "Kubernetes.") is kept. Parakeet skips
  chunks without speech and trims each chunk to its speech. In a synthetic check with 20 s of fan noise
  between two sentences, live captions decoded half as much audio and kept both sentences whole;
  Parakeet finished 2.3× faster. If a model or `onnxruntime` is unavailable (for example on macOS 13,
  which the current `onnxruntime` wheel does not support), transcription continues as before and the
  reason is saved in `transcript.metadata.json` or `live-caption.log`. Turn it off in
  **Settings → Recording**.
- **Hallucination filter:** the app removes known Whisper inventions (subtitle credits,
  "subscribe" and "thanks for watching" phrases) and loops where one phrase repeats four or more times.
- **Vocabulary:** enter names and terms in **Settings → Recording → Vocabulary for transcription**.
  Whisper gets them with the known speakers as a prompt. This helps with words such as Terraform
  or OIDC. A prompt makes Whisper timestamps unreliable, so the final pass then runs two times:
  the first pass gives the segments and timestamps, the second gives the words. The app aligns
  the words to the segments. If the two passes differ too much, the first text stays.
  Live captions use the same prompt and drop captions that only repeat it.
- **Names that Atlanta knows:** each transcription, correction and set of notes also gets the names
  and aliases of People, the project names and the repository names. They are added after your
  vocabulary when the vocabulary does not have them yet. A name over 50 characters or 5 words is
  left out (the Scribe limit). The saved vocabulary does not change.
- **Learn from corrections:** when you correct a term in the text of a task or a decision (for
  example "Ex Am Pull" to "example.org"), Atlanta offers to add it: "Add “example.org” (heard as
  “Ex Am Pull”) to the vocabulary?". **Add to vocabulary** saves `example.org | Ex Am Pull`.
  Only short replacements count (up to 3 words); a rewrite or a speaker name offers nothing.
- **Named speakers in the notes:** when you name a speaker (for example SPEAKER_00 as Мария), the
  saved notes get the name too, without AI: "SPEAKER_00 да провери" becomes "Мария да провери",
  also as the task owner. The tasks and decisions of the meeting follow, unless you changed their
  text yourself. Quotes keep the words that were said. Reviews that you confirmed still hold.
- **Cloud transcription:** sends recorded audio chunks to OpenAI; requires an API key and
  incurs API charges. Default model is `gpt-transcribe`, configurable in Settings. Cloud
  timestamps indicate approximate audio chunk boundaries, not word alignment. See the
  [official file-transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text).
- **Configured API notes:** use the OpenAI-compatible API configured in **Settings → Notes & AI →
  Configured API**. Defaults: `http://localhost:1235/v1`, model `qwen3.5-9b`. Click **Load available
  models** and enter a text/chat model ID exposed by your server. This one endpoint/model powers
  summaries, decisions, task extraction, open questions, and meeting titles.
- **A cloud configured API**, for example Kimi Platform (`https://api.moonshot.ai/v1`): enter its
  **API key**. The app saves it in macOS Keychain and sends it only to that endpoint; the OpenAI key
  never goes there. An address outside this Mac and its local network shows a warning, and the
  privacy text names the host that receives meeting text. Without a key, processing stops before it
  starts. `LOCAL_AI_API_KEY`, if set before the app starts, is used instead and is not saved.
- **Model context** (advanced; always shown for a cloud API) is the context of the served model. Up to 16,384 tokens, a long
  meeting goes in parts of 10,000 characters. A larger context takes the meeting in larger parts, up
  to 400,000 characters, so a cloud model usually reads the whole meeting at once.
- **Temperature** (advanced; always shown for a cloud API): **0** gives the same answer for the same input. Kimi K3 models accept
  only their own value; choose **Server default** for them. Keep reasoning on **Automatic** for Kimi.
  With thinking on, Kimi K3 models used the full 16,384-token output limit and returned no notes.
  Keep your model server running. It must accept unauthenticated requests on this endpoint.
  JSON schema is the default; choose JSON object or Prompt only if your server needs it.
  All modes still validate generated notes and task evidence timestamps before saving.
  Reasoning effort defaults to **Automatic**: Qwen3.5 notes, transcript correction and titles
  send `reasoning_effort=none` before the first request. The same applies to every model on a
  cloud (non-local) API. Selected-email analysis resolves Automatic
  to Off for Qwen3.5 and shows the effective reasoning/output limit before approval. Other models
  keep the server default. Explicit Off/Low/Medium/High choices are kept. Choose
  **Server default** if your endpoint does not accept `reasoning_effort`. The shared maximum output defaults to
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
Long transcripts are extracted in parts of about 10,000 characters, then consolidated with the same
selected AI provider. A part fits a 16k-token local model context with its answer.
The global summary has at most six points; tasks and decisions have no fixed count limit. If the
model keeps skipping one source, that source stays as its own point instead of failing the merge.
Each statement goes into one section only, in this order: decisions, tasks, updates, the sections
of the meeting type, needs decision, open questions, next steps, observations, summary. The model
writes the sections in this order too, so the summary comes last. The summary does not repeat
tasks, decisions, updates or questions. A guess ("може би ще го дам на Иван") is an open question,
not a task. Observations are at most three work risks; they never judge a person. Known participant
names keep their exact spelling in every statement. Another name of a person in People (for
example a short name) becomes the People name in the statements, task text and owner.
Vocabulary variants (`PacketFence | PacketFancy`) become the preferred
spelling in the generated notes; the transcript keeps the recognized text.
Consolidation selects an existing task or decision instead of rewriting its owner or deadline.
Different owners, dates, negations, numbers and environments veto a proposed merge. Similarity
is only a candidate search, never an automatic deletion rule. Expand **Consolidation evidence**
in Review or Notes to see the original statements and transcript moments; AI grouping still
requires human review and is not a guarantee of semantic equivalence.

A small model can skip, repeat or invent one ID in its answer. Consolidation repairs that before
its strict check: a skipped ID stays its own group, a repeated ID counts once and an unknown ID is
dropped. Nothing new is merged by the repair, and the audit counts the repairs.
Inputs and requests are bounded. If consolidation fails, the notes keep every part as extracted,
so some statements may appear twice, and a warning names the reason. Saved notes remain unchanged:
the unmerged notes wait for review like any new run. **Generate new AI notes** retries and reuses the
completed parts. Cancelling still saves nothing. Editing only the consolidation prompt reuses
completed extraction. The new **Meeting notes consolidation** prompt is editable in Settings
and participates in prompt snapshots and reprocessing previews. Rerunning existing notes
creates a review proposal and preserves manual edits until accepted. Original recordings and
transcripts are unchanged by consolidation.

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

### Listen to a moment

Every time next to a meeting moment is a start/stop control: **▶** plays from that
moment, **■** stops it. Only one moment plays at a time; starting another stops the
first. The control is in the transcript, speaker review, notes and analytics of a
meeting, and also outside the meeting: task and decision sources in My Work and
Projects, the project trace and events, Prepare me and Search & ask. You listen in
place; the page does not change. A note's source plays only its cited segment, and
a saved excerpt plays only its time range. In the open meeting the control uses
the meeting's player, so its position stays in sync. Opening a meeting from a link
shows the moment in the transcript without starting playback. Meetings without a
recording (for example, imported transcripts) show the control as unavailable.

### Conversation analytics

Saved meetings have an **Analytics** tab for talk time, topic evidence, and questions.
The sidebar's **Conversation analytics** view aggregates those results across meetings,
with date, speaker, and topic filters. It reports descriptive statistics, not employee
scores, and does not perform sentiment analysis.

- **Offline speaker diarization and talk time.** After transcription, optional
  `pyannote/speaker-diarization-community-1` processing creates `speaker-timeline.json`.
  Local Whisper can retain experimental word-sized boundaries and split the final text at
  speaker changes. The exclusive speaker turns align the text; the regular, overlapping timeline
  remains the source for talk-time statistics. Old, cloud or edited transcripts without matching
  word boundaries keep segment-overlap assignment; no word times are fabricated. Talk time is calculated from merged speaker intervals, not transcript lengths;
  silence is excluded. The view includes turns, talk percentage, longest monologue,
  average turn length, and question count. Overlapping intervals for the same speaker are
  merged first. Simultaneous speech by different speakers counts toward each speaker.
- **Speaker review after the meeting.** Open the Transcript tab, find **Speakers · after recording**,
  listen from an example and use **Apply name**. The name applies to that voice throughout this
  meeting, with a transcript revision check to reject stale reviews. A voice suggestion can
  propose a name from earlier meetings (see **Voice suggestions**). Names already confirmed are
  not overwritten by a speaker retry.
  **Identify speakers after recording** retries this stage without rerunning Whisper or correction.
  Re-running Analytics uses saved text and timelines only; it never starts speaker separation.
  Runtime/model errors appear next to the transcript; model dependencies are checked without
  importing torch during recording. An installed runtime does not prove model access.
- **Speaker renaming.** Changing a generic label such as `SPEAKER_00` to a person's name
  updates every matching segment and timeline interval in that meeting, then rebuilds its
  analytics. Generic IDs are not assumed to represent the same person in other meetings.
- **Voice suggestions.** Speaker separation also saves a voice print for each speaker in
  `voiceprints.json`: the mean speaker embedding of up to 60 s of the speaker's longest turns.
  When a speaker has a name, the print learns that name. A new meeting then shows
  "Sounds like …" for an unnamed speaker, with **Use** to apply the name. A suggestion needs a
  similarity of at least 0.75, at least 10 s of audio, and a gap of 0.10 to another voice.
  Only confirmed People aliases join names into one candidate. Similar voices belonging to
  different people remain rivals. A changed speaker timeline invalidates the old print until
  it is learned again. Nothing changes until you apply a suggestion. The observed scores
  (0.82–0.90 for the same person, at most 0.68 for different people) are not identity guarantees.
  **Settings → Voices → Learn voices from saved meetings** makes prints for meetings that were
  separated before this feature. The prints stay on this Mac and are deleted with the meeting.
- **Topic trackers.** Manage shared trackers in **Settings → Topic trackers**. Literal
  phrases match locally and case-insensitively, with timestamped transcript evidence.
  Optional matching by meaning uses the Configured API (on this Mac or a cloud API) and validates every
  returned segment ID. A match must be about the topic in its own words; a reply of one or two words
  never matches. If this matching fails, literal hits remain available and the meeting shows a separate
  analytics warning. A speaker rename reuses the earlier matches.
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
For a desktop bundle, install the extras in the **packaging environment** and build with
`python scripts/build_desktop.py --with-diarization`. Installing them in a separate venv does not
add them to an already frozen application. The build includes pyannote/torch dependencies, not a
Hugging Face credential or gated model weights. A local Hugging Face login (`hf auth login`) can
provide model access; alternatively supply `HF_TOKEN` to the app process. The login needs access
to the gated model and its required submodels. Credentials are never included in library archives.

`transcript.before-speakers.json` keeps the pre-separation text, and `transcript.alignment.json`
keeps native estimated word units. Both are included in library archives and downloadable Files.
Retranscribing archives the old artifacts. Original segment starts remain available so existing
notes keep their timestamp references. The worker reuses a private, rebuildable matplotlib cache
outside meeting archives instead of rescanning macOS fonts on every speaker job. AI correction keeps a separate `transcript.raw.json`
with the same turn layout for per-row restoration. Numbers, negations and known participant names
are protected from AI rewrites; this is a guard, not proof of semantic equivalence.

Real meeting diarization accuracy and MPS inference have not been measured by the automated
suite; verify a short recording before relying on speaker statistics.

### AI correction of the transcript

After you stop a recording, processing runs in this order: Whisper transcription,
optional diarization, AI correction, notes, analytics, then any calendar automation. Set the provider in **Settings → Recording → AI correction after
transcription**: **Configured API** (default), **Cloud · OpenAI**, or **Off**.

- The model fixes spelling, punctuation, capital letters, and words that were heard wrong.
  It uses the known speakers for the spelling of names. A misspelled name may become the name
  ("Мариа Петрова" → "Мария Петрова"). A name may not go away, may not appear from other words,
  and may not become another person. A short name (under 6 letters) keeps its form.
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
unresolved questions, agreed next steps), **Notes** (summary, questions for
your decision, private observations), and **Analytics**. Generated notes contain these sections:

- **Summary** and **Decisions**.
- **Next steps:** agreed process steps, for example a follow-up meeting.
- **Questions for your decision:** items that wait for a decision and were not decided.
- **Tasks:** task, owner, deadline as said, due date, status (open or done), and source timestamp.
  The model receives the meeting date. It converts a deadline such as "до петък" into a due
  date when the date is clear. Otherwise the due date stays empty. A task without a deadline in the
  words of the meeting gets no due date from AI. You can set it yourself.
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

### Follow-up email

After you review a meeting, open **More → Follow-up email…**. The draft uses only reviewed content:
accepted decisions, accepted tasks with their owners and due dates, and checked summary, open-question
and next-step statements. Open questions get their own section only when there are checked ones. Private observations and AI proposals stay out.

- The editor opens with a plain draft. **Write with AI** rewrites it with the Notes & AI provider.
  Edit the instructions in **Settings → AI instructions → Follow-up email**.
- Recipients come from **People**. Participants and task owners with an email address are preselected.
  You can add other addresses.
- **Save Gmail draft** saves the email as a draft in Gmail. It needs the separate `gmail.compose`
  permission: choose **Connect Gmail drafts** once. Atlanta never sends email. You check the draft and
  send it from Gmail. Saving again updates the same draft until you send or delete it.

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

The [work assistant contract and implementation tasks](work-assistant-contract.md) describe
the next stages. This foundation supports meeting tasks, decisions and questions.
The Gmail, Google Chat and GitHub source integrations are described below.

**Suggested** stores source-backed proposals separately. **Accept** creates an item; **Link** attaches
the quote to an existing item of the same kind without changing its text, owner or status. Dismiss,
Snooze and Restore keep proposals reachable. A changed or unavailable source blocks acceptance of
its older proposal. **All** includes reviewed and stale proposals. Reprocessing an identical revision
does not create another proposal or reset a dismissal. Automatic extraction from Gmail or Chat is
not enabled yet.

**Questions** first shows **From meeting notes**: the open questions and the questions for your decision
in the notes of every meeting, newest first. A question asked again shows once. **Answer** or **Track**
moves it to **Tracked questions** with its meeting and moment; new notes of the meeting do not remove it.
Tracked questions also hold personal questions and questions accepted from proposals. Add a question,
save an answer, or reopen it; the earlier answer stays in its history. Suggested and Questions cover all sources,
independent of the meeting project filter. **Edit** and **Delete** work on every question, task and
decision, also on items with saved sources. Delete removes the links to other items; the saved source
quotes stay. Proposal Link adds sources without merging away IDs or history.

Example: "Test the SAP permissions" is created on 19 Oct; on 23 Oct a meeting says "до петък", the due
date changes, and the task stays open. The history shows both meetings.

**New AI notes and existing items.** When new notes mention something that looks like an open task or a
decision in force, nothing is linked automatically. **To review** cards (in this view and in the meeting)
ask you to choose:

- Tasks: **Same task · update** (new owner, deadline and due date fill the fields that you did not edit),
  **Duplicate** (link only), or **new task**.
- Decisions: **Same decision**, **Replaces it** (the older decision becomes *Replaced*), or **new decision**.

**Processing a meeting again** (a new transcript or new notes) replaces its notes, tasks and decisions.
A task or decision with the same text keeps its identity, status and history. The new notes replace the
other items of the earlier notes, so you review each task once. A task that you added to the meeting stays.
An item that another meeting also discusses stays, without the link to this meeting.

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
- In the meeting notes, each statement has **Edit** and **Delete**. Examples: the summary, decisions,
  unresolved questions and next steps. You do not need the full notes editor. An edited statement
  counts as checked.

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
With "Configured API" notes, the question and passages go to that API; they stay on this Mac only
when the API runs here.

### People and meeting participants

Manage everyone in **Settings → People & sources → People**. The same profile supplies
participant names, task owners, aliases and confirmed channel identities. New names you save
in a transcript are added to People; anonymous diarization labels remain meeting-local.
Choosing another person in a meeting changes that meeting, without adding a global alias.
Edit aliases explicitly in People. Notes receive preferred names as spelling context, never
as evidence that someone attended or accepted a task.

### Delete a meeting

Click **More ▾ → Delete meeting** on a saved meeting and confirm. The app removes the meeting folder
with the recording, transcripts, notes, and versions. You cannot undo this. Make a copy
of the folder first if you are not sure.

If the meeting has a Google Calendar event, the same question has three answers: **Delete meeting
and event**, **Delete meeting, keep event**, or **Cancel**. The app deletes only the event that it created
for this meeting. If Google cannot delete the event, the meeting stays on this Mac.
After the delete, the Library opens. A saved link to a deleted meeting also opens the Library and says
that the meeting is no longer on this Mac.
You cannot delete a meeting while it records or processes.
The app validates notes' structure and source timestamps, but factual correctness still requires
review against the recording. See [benchmarks/README.md](../benchmarks/README.md) for a repeatable
local-versus-cloud quality evaluation; no provider quality ranking has been established yet.

## Local Parakeet v3 transcription (Apple Silicon)

In **Settings → Recording → Transcription**, select **Local · Parakeet TDT 0.6B v3**
for the final transcription. Whisper remains available; live captions always use the selected
Whisper model. Existing settings do not change automatically.

Parakeet v3 supports Bulgarian and English, with automatic language detection. The Whisper
vocabulary does not apply; voice detection does (see Voice detection above). Compare the results on representative recordings before
assuming better accuracy for Bulgarian with English technical terms. AI correction, notes and
post-recording speaker separation remain separate steps.

The Apple Silicon installer includes the runtime by default; `--without-parakeet` omits it.
For a manual build, install `requirements-parakeet.txt` and add `--with-parakeet` to
`build_desktop.py`. Intel Macs can continue using Whisper. The first transcription downloads
model files from `mlx-community/parakeet-tdt-0.6b-v3` at a pinned revision into the app's models
folder. Audio stays local. Long recordings use bounded, restartable chunks; original audio and
previous transcript versions are retained. Parakeet's token boundaries provide word anchors for
speaker alignment, rather than estimating word times from text length.
The original [NVIDIA model](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) uses CC BY 4.0;
the [Parakeet MLX runtime](https://github.com/senstella/parakeet-mlx) uses Apache 2.0.

### Experimental Parakeet + vocabulary

Select **Settings → Recording → Transcription → Local · Parakeet + vocabulary · experimental**.
This separate Sherpa-ONNX CPU backend uses **Vocabulary & names** and saved participant names
while decoding speech, with automatic language detection. Terms are comma/newline/semicolon-separated;
spaces inside phrases are retained. `/` and `:` are reserved by the decoder and rejected.
Unsupported characters fail visibly; terms are never silently dropped. Boosting is a preference,
not a guarantee: an excessive or unrelated dictionary can introduce false words.

The installer includes the runtime by default; `--without-parakeet-sherpa` omits it.
Manual builds require `requirements-parakeet-sherpa.txt` and `--with-parakeet-sherpa`.
The pinned runtime includes the [NeMo TDT speech-dropping fix](https://github.com/k2-fsa/sherpa-onnx/pull/4084).
First use downloads a separate approximately 670 MB ONNX model from
[csukuangfj](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8)
at a pinned revision into `models/parakeet-sherpa`. MLX weights cannot be reused for ONNX.
Audio stays on this Mac; no new server or LM Studio instance is needed.

Existing provider choices stay unchanged. Live captions still use Whisper. AI correction and
speaker separation remain independent. Real token boundaries support playback and speaker alignment;
metadata records the runtime/model revision, vocabulary and decoding settings. Interrupted jobs
resume only with matching audio, vocabulary and decoder settings. Original audio is preserved.
Compare the same representative Bulgarian recording with MLX and Sherpa, with/without a short
dictionary, before changing your default: Bulgarian accuracy, speed and memory have not been
benchmarked on your meetings.

### ElevenLabs Scribe v2

In **Settings → Recording → Transcription**, choose **Cloud · ElevenLabs Scribe v2**.
Create a key at https://elevenlabs.io/app/api/api-keys with Speech to Text access,
paste it into **ElevenLabs API key**, then save settings. The app saves the key in the shared
Atlanta Keychain item, so it is available after a restart. **Forget ElevenLabs key** removes it.
If Keychain refuses the key, Settings shows this, and the key stays only until the app closes.
Alternatively, set `ELEVENLABS_API_KEY` before launching; the app uses it and does not save it.
The app shows whether a key is present; this does not validate credits or API access.

The app uploads the whole recording to ElevenLabs in one request for final transcription.
The model is `scribe_v2`; language detection is automatic for Bulgarian and English.
The original recording is kept. A failed request is retried with the whole recording.
Words retain the API timestamps for playback.

Scribe does not separate the speakers. In online meetings, the voices of other participants
arrive in one system audio stream, and Scribe merges them into one speaker. The local
speaker model separates the speakers, and the Scribe word timestamps assign each word to
a speaker. Live captions continue using local Whisper. Scribe Realtime and importing a transcript from an
ElevenLabs editor URL are not part of this integration.

**Vocabulary & names** is the single dictionary shared by speech recognition, transcript
correction and meeting notes. Existing comma-, semicolon- or newline-separated lists still work.
Optionally enter a preferred spelling with phonetic variants, one entry per line:

```text
Kubernetes | кубернетис, кубернетес
GitHub | гитхъб
Terraform, Keycloak, Иван Петров
```

ASR receives only the preferred spellings, never the alias syntax. AI correction and notes
also receive the explicit variants as spelling context, not proof that a word was said.
Only literal whole-phrase aliases relax the correction similarity check; numbers, negations,
confirmations and known participant names stay protected. "Да" counts as a confirmation only
as an answer (at the start of a sentence or before punctuation); the particle in "трябва да" can be fixed. Ambiguous aliases are rejected
when saving settings. No extra AI pass or separate dictionary is added; original ASR text
and source timestamps remain available. Changing the vocabulary uses the existing explicit
reprocessing flow for old meetings.

For Scribe, preferred spellings are sent as keyterms. Each term must
have at most 50 characters and 5 words; brackets, braces, angle brackets and backslash
are unsupported. ElevenLabs charges extra for keyterms. Review current prices and
account limits at https://elevenlabs.io/pricing/api before processing long recordings.
AI transcript correction does not run automatically after Scribe. To run it on a Scribe
transcript, choose **AI text correction** explicitly. Notes and title generation keep their
separately chosen providers.
