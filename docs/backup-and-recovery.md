# Archive, durability and recovery

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
For the default Qwen3.5 model, **Reasoning effort → Automatic** (including previously saved
`default`) turns reasoning off for notes, transcript correction and titles. The server default can
spend the output budget on thinking before producing JSON, even for a short meeting. Choose
**Server default** to explicitly leave reasoning to the endpoint, or **Off** to disable it for all
local AI features. Explicit Low/Medium/High choices are not overridden. Truncation errors distinguish
an empty answer from a partial answer and report the requested output budget and reasoning setting. Measure transcription quality on your own speech before choosing a smaller model.

After an interrupted recording or job, reopen the app and select **Recover audio** to rebuild
a playable WAV from raw tracks. Then **Transcribe** to retry. Recovery works without a finalized
WAV header. Failed model/API jobs preserve audio and previous final transcripts. Retries resume
compatible completed transcription chunks. Do not remove the raw tracks until you
have checked the recording. **Delete meeting** removes all files of a meeting permanently.

The library is independent of the original CLI's `output/` folders; those can still be reprocessed
with the CLI. Existing CLI folders are not automatically imported.

### Local metadata recovery

Removing a confirmed channel identity uses the full provider/account/sender key.
When the same email is confirmed for another account, that identity and the shared
email stay attached to the person. Removing its final Gmail identity removes that
email only; other emails and Chat identities remain.

`people.json`, `projects.json`, `github-links.json` and `meeting-templates.json`
distinguish an absent file (a new empty library) from an unreadable, malformed or
structurally invalid file. Invalid metadata is read-only, including merge and low-level
save paths. Changes outside the app after loading also block writes. A persistent
warning identifies affected files and opens **Settings → Backup**. Recording remains
available without assigning a project.

Recovery requires an existing verified archive containing every affected metadata
file. Archive metadata is validated before meetings are moved. Damaged stores recover
as complete validated collections; healthy stores continue to merge missing entries.
The original bytes are copied to `<name>.corrupt-<id>.json` before replacement, and
these local recovery copies are not automatically removed. If the original cannot be
read for preservation, recovery fails instead of overwriting it. No new archive is
created while metadata needs recovery, avoiding a misleading verified backup of the
broken data. Existing recording and transcript files are unaffected by metadata repair.

A damaged `settings.json` (not valid JSON, or not an object) does not stop the app. The app
starts with safe defaults: no automatic processing, no calendar and no cloud AI. It copies
the original bytes to `settings.corrupt-<id>.json` and does not write `settings.json` until
you save Settings. The same warning names the copy and opens **Settings**. Saving valid
settings ends the safe mode; the copy stays.

1:1 backups also preserve optional `review-context.json` and `private-preparation.md`. They are local private preparation data; Markdown review exports omit them.
