# AGENTS.md

Guidance for AI agents (and contributors) working in this repository. Read this first; the
docs in `docs/` carry the details this file points to.

## What this is

Atlanta — a local-first macOS meeting assistant (Bulgarian-first). It records meetings,
transcribes with local Whisper, generates AI notes, and tracks tasks, decisions and questions
across meetings and connected sources (Gmail, Google Chat, GitHub). Everything runs on the
user's Mac: Python backend on `127.0.0.1:8765`, vanilla-JS web UI with **no build step**, and
an optional Tauri desktop wrapper (`desktop/src-tauri/`, Rust) that packages a PyInstaller
backend into `/Applications/Atlanta.app`.

## Verify before claiming done

```sh
.venv/bin/python -m unittest discover -s tests -q   # full suite (~1255 tests; 1 known skip: BMA_RNNOISE_MODEL)
node tests/web_<name>_regressions.cjs               # run one web regression suite
for f in tests/web_*regressions.cjs; do node "$f"; done   # run all 94 directly
node --check web/app.js                             # JS syntax after editing app.js
cargo check --manifest-path desktop/src-tauri/Cargo.toml    # after Rust changes
```

Rules:

- **The venv has no pytest.** Always use unittest.
- The suite does not cover real microphones, permissions, ScreenCaptureKit, diarization
  quality or paid APIs. State what you verified and what you could not.
- After editing anything under `web/`, run the full cjs suite — see below.

## The web regression suites are source assertions

`tests/web_*regressions.cjs` (executed by `tests/test_web_components.py` via node) match the
**text** of `web/app.js` / `web/index.html` / `web/style.css`: exact strings, class names, DOM
structure, and behavioral slices run in a `vm` context. Renaming a user-facing string, a class
or the shape of a component will fail suites far from the code you touched. When you change UI
text, structure or behavior deliberately, update the matching assertions in the same commit —
this is the project's substitute for a browser test suite. New UI behavior gets a new
`tests/web_<feature>_regressions.cjs` following the existing pattern.
`scripts/check_layout.cjs` needs playwright (usually absent); treat it as optional.

## Architecture map

- `app/` — backend package. Entry: `desktop_app.py` (server + browser UI). Key modules:
  `service.py` (HTTP API surface, item_list, task matching orchestration), `items.py`
  (Registry: tasks/decisions/questions, text-similarity candidate matching), `work_graph.py`
  (source-backed proposals: accept/link/dismiss/snooze, meeting matches, supersede),
  `meeting_proposals.py` (meeting-mention proposals), `storage.py` + `WorkItemStore`
  (work-items.sqlite3 with optimistic concurrency — writes carry `revision`, conflicts raise
  `WorkItemConflict`), per-source modules `gmail.py`, `google_chat.py`, `github_source.py`.
- `web/` — the whole frontend. `app.js` (~4400 lines, plain JS, compact one-line style),
  `task-model.js` (`AtlantaTasks`: pure view/filter logic, unit-tested from JS),
  `ux.js`/`forms.js`/`status.js` helpers. Components are helper functions (`btn`, `actionBtn`,
  `el`, `statusBadge`, `originChip`, `segmentedChoice`), not classes. State flows:
  `loadTasks()` → `/api/items` → `itemsData` → `renderTasks()` re-renders on every change.
- `desktop/` — Tauri shell; `native/SystemAudio.swift` compiled by `build_native.sh`.
- `models/` — ggml Whisper binaries (multi-GB, downloaded on first use, not in git).
- `meetings/` — live data dir of the checkout (items.json, settings.json, *.sqlite3 caches).
  Do not treat its contents as fixtures and do not commit changes to it.

## Product invariants (tests enforce these — never break silently)

- **Privacy boundaries:** email/chat text is sent to an AI endpoint only after explicit
  per-message approval; proposed and hidden (dismissed) tasks are never sent to task matching
  (AI sees accepted, visible, open tasks only); API keys never appear in meeting files or API
  responses. Changes touching AI sending must keep these boundaries (see
  `tests/test_ai_budget_and_errors.py`, `docs/work-assistant-contract.md`).
- **AI meeting tasks are off by default** (setting `meeting_task_ai`, since 2026-11-12): the AI stops at the
  notes; tasks and decisions are text there, and the person makes tasks with **Create task** on a notes line. Test modules that cover AI proposals
  or matching import `setUpModule`/`tearDownModule` from `tests/ai_meeting_tasks.py`.
- **Nothing changes until the person decides:** AI proposals stay proposals until accepted or
  linked; meetings, owners, states the person edited are never overwritten by AI
  (`keep_confirmed` reviews in `meeting_review.py`).
- **Local-only networking:** the server binds localhost, checks origins, uses a random session
  credential. Do not add network listeners or telemetry.
- Items keep stable IDs across edits; histories and evidence quotes are append-only.

## Code conventions

- Python: standard library first; small focused modules; `threading.RLock` around shared
  state; type hints on new functions. New runtime dependencies go in `requirements.txt` and
  `requirements.lock` (builds install with `-c requirements.lock`) — say so if you add one.
- JS: match the file's compact style and the existing helpers; create elements via `el()`,
  buttons via `btn()`/`actionBtn()`; strings are user-facing English copy.
- Comments in this repo explain **why** (product decisions, invariants), not what. A comment
  citing a dated decision is intentional — keep it current when the code changes.
- CSS: single `style.css`, section comments, themed via `var(--…)` (dark/light). No frameworks.
- Every task/decision/question has exactly one card pattern shared between My Work, projects
  and meeting views — reuse it instead of inventing a variant.

## Workflow

- The remote rejects direct pushes to `main`; all changes go through a PR.
- Ruleset 25815098 requires 1 approval + CODEOWNER review, and the author cannot approve their
  own PR. Maintainer merges with `gh pr merge <N> --squash --delete-branch --admin`.
- One logical change per PR; squash merge. Full suite green on the branch before merging.
- macOS 13+, Apple Silicon; ffmpeg from Homebrew; Rust via rustup for desktop work.
- Desktop (re)install: `scripts/install_desktop.sh` (builds with diarization + parakeet by
  default; `--without-diarization` for a smaller app). Dev run: `scripts/run_desktop.sh`, or
  `.venv/bin/python desktop_app.py` for the browser UI.
- If you change something an `AGENTS.md` section or a `docs/` page describes, update that
  text in the same commit.
