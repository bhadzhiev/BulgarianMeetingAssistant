# Development, CLI and verification

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

### Compare Whisper accuracy locally

Use `scripts/evaluate_whisper.py --audio /path/clip-source.wav --reference /path/human.txt
--output /private/tmp/new-whisper-comparison --models-dir /path/models` on a representative clip.
The default compares `large-v3-turbo` and `large-v3` on the first 120 seconds; `--start` and
`--seconds` select the exact clip that the human reference describes. This runs local Whisper
only, preserves the input and refuses an existing output directory. It may download missing
Whisper models. The private output contains transcripts and `metrics.json` with word error rate
(case-insensitive, punctuation ignored) and wall time including model loading/download. Use warm,
already cached models when comparing speed. A lower error rate on one clip does not establish
quality on every meeting. No AI correction or speaker processing changes the comparison.

Source sync and AI feedback: GitHub refresh keeps earlier cached items visible until the new
refresh completes, and an interrupted page resumes from its saved queue. Cached results may be
older while a refresh is incomplete. Recording/processing pauses further sync requests; choose
Continue sync afterwards. Email AI shows progress and its result next to the selected message,
including a successful analysis with zero task suggestions. Quote validation failures, endpoint
failures and output-limit errors remain explicit and never auto-accept tasks.
