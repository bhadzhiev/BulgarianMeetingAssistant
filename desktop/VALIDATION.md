# Desktop validation

Validated locally on Apple Silicon, 25 October 2026, with separate temporary meeting libraries.

- Full Python regression suite: 249 tests passed. One subsequent ownership test also passed;
  all four desktop lifecycle tests pass together.
- `cargo check` and optimized Tauri app build passed.
- Frozen backend emits its private readiness event, serves loopback HTTP and exits on stdin
  shutdown or EOF. The frozen live-worker entry point accepts its own arguments.
- Real native window loaded the existing UI and showed Connected to this Mac.
- A second native launch focused the existing instance and did not create another library/server.
- Closing the window / Quit stopped the backend and released port 8765.
- Force-stopping an isolated native parent caused its backend to exit and remove `.running.json`.
- A synthetic active recording was rendered to WAV on desktop shutdown, without starting AI work.
- Desktop mode refused to replace an existing process that owned the library lock.
- The complete optimized app passed `codesign --verify --deep --strict` with a local ad-hoc signature.

Not established by these checks: real microphone or ScreenCaptureKit permission grants in the signed
app, recording alignment, real Whisper inference inside the frozen bundle, optional pyannote/MPS,
or notarization on another Mac. The default build uses the installed ffmpeg/ffprobe. Local AI notes
still require the model server selected in Settings. Models and real meeting data are not bundled.
