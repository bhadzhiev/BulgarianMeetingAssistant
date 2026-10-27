# UX flow reliability and validation

The review in this task was implemented on top of `00193f0` without changing the audio capture/transcription provider contract or publishing to external sources.

## Behavior

- Meeting/source readers publish only the latest requested result. Refresh rechecks the current meeting and dirty state after receiving data. In-flight transcript/note saves temporarily make the editor inert; navigation waits for the save.
- Date fields display and accept `dd.mm.yyyy`. A field-scoped controller retains ISO values for existing API callers. Select, type, presets and Clear emit the same events. Invalid dates show field errors; date-only values never pass through UTC midnight.
- Library search/project/period stay visible; advanced source/series/participant filters collapse. Active filters can be removed individually, and session-local filters/page survive navigation. Queries are not copied into shared URLs.
- Prepare me sends item revisions and resets a failed completion control. Project-level preparation also includes explicitly project-assigned work from external sources, respecting manual assignments and disposition.
- Task generation is an isolated cancellable job. The editor shows source evidence, model/destination, project, editable text and a manual fallback. Only Create task commits. Successful creation and a failed list refresh are separate outcomes; operation IDs prevent duplicate creation after retry. Open task opens a contextual panel. Opt-in draft recovery stores only the draft/selection/project on this Mac for at most 24 hours.
- Project scope is visible before recording. A new meeting from a project inherits that project. Tasks can be opened/edited from the project without leaving it. Sources have their own Gmail/Chat/GitHub sub-navigation, preserving selected objects/reports in routes.
- Post-meeting states distinguish transcript readiness, outdated notes and notes awaiting review. One primary action drives generation/update/review; detailed timings and speaker tools collapse. Reading timestamps are quieter; explicit split/merge tools preserve the recording and require confirmation before merging different speakers.
- Errors appear inside the active modal. GitHub collection distinguishes access, rate limits and connectivity. Copy diagnostics excludes credentials and conversation text.
- Native quit checks the editor dirty bit as well as recording. The authenticated UI sends only a boolean/heartbeat through the existing private backend/native pipe. App menu → Recover interface reloads the window without restarting the backend; unsaved edits require confirmation. A stale heartbeat flags the window title; no automatic reload discards work.
- Repository analysis batches pinned evidence by logical change within the existing input limit, retains validated quotes, saves completed input parts and produces a bounded source-grounded overall summary. Omitted summary sources are disclosed; all per-change findings remain actionable. Context reads are memoized by account/repository/blob. AI cache strategy changes do not rewrite existing source evidence.
- Report polling reads lightweight list/job revisions; unchanged report detail is not downloaded or rendered again. Expanded report details are preserved across actual updates.
- Meeting metadata uses a bounded memory cache (20 MB / 10,000 entries). File mtime, size and inode invalidate entries; callers receive independent values. No persistent copy of transcripts or new FTS index was added.

## Validation

Automated coverage includes reversed meeting responses, edit-started-during-refresh, leap/invalid dates and Sofia date/time display, Prepare revisions, task operation retries with changed text, cancelled draft publication, project-scoped external tasks, batch boundaries, quote validation after restart and metadata replacement/mutation/deletion.

Manual browser QA used an isolated library, synthetic meetings and a fake localhost LLM. Verified: library presets/format/invalid-date errors; source navigation; source → generated draft → edited text → selected project → creation → contextual task panel; Clear → enabled Save → reopened task without the old due date; successful completion from Prepare me. The responsive library was inspected at 1024 px and 768 px. No real external content was sent to an LLM for these checks.

Rust `cargo check` passed after native quit/recovery changes. Full-suite/build/install results are reported separately in the task completion message.

## Performance evidence and limits

Run `python scripts/benchmark_ux.py --output /tmp/atlanta-ux-benchmark.json` in the application's environment. It generates disposable meeting metadata/transcripts and makes no account or LLM requests.

The committed JSON records this Mac's sample. At 5,000 synthetic meetings, warm library median changed from 0.4889 s to 0.4289 s with metadata caching. Cold performance was approximately unchanged (0.4823 s versus 0.4969 s); the optimization targets repeated use. These small synthetic transcripts do not establish latency for very long real recordings or production p95.

For an 80-part / 10-change synthetic snapshot, the plan changes from 80 worker steps to 11 including synthesis. That is a request-plan reduction, not a measured LLM speedup or quality claim. Report metrics expose worker steps, input characters and elapsed processing time for the selected model. Output-splitting retries can issue additional underlying model calls. The benchmark peak RSS belongs to the Python benchmark, not to Whisper, Parakeet or an LLM.

The current 5,000-meeting sample does not justify a new persistent transcript/FTS store. The existing text cache and rebuilt search index remain; a broader index should follow evidence from long real libraries.
