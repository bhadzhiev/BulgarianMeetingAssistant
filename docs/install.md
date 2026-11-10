# Install and open the app

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

Calendar meeting links open in the default browser, which does not share the desktop window's
session cookie. The browser page hands the meeting to the desktop app through the `atlanta://`
URL scheme, and the desktop window opens the meeting. The browser can ask once for permission to
open Atlanta. Unsaved edits in the window get the usual leave prompt first.

For development, install Rust and run `scripts/run_desktop.sh`. It uses `.venv/bin/python` by
default; `BMA_PYTHON` selects another interpreter. `BMA_DATA_DIR` selects an isolated data directory.
The native audio helper must be built with `./build_native.sh` before testing online recording.

To build a `.app`, use a packaging virtual environment with the normal requirements and PyInstaller,
then install the Tauri CLI and run:

```sh
npm --prefix desktop ci
python scripts/build_desktop.py
```

To build and install (or reinstall) in one step, run `scripts/install_desktop.sh`. The script makes
a packaging environment in `.venv-build`, installs the Tauri CLI, and builds the app. It then quits a
running copy and replaces `/Applications/Atlanta.app`. Only one install runs at a time: a second
run stops with "Another install is running", because two builds in the same folders make an app
that does not start. A lock left by a stopped install (`build/install.lock`) is taken over. A copy with the old name
(`Bulgarian Meeting Assistant.app`) moves to the previous copies. The identifier, the library and
the Keychain item stay the same. `BMA_INSTALL_DIR` selects
another folder. The script accepts the same options as `build_desktop.py`. It also installs
`requirements-diarization.txt` and builds with `--with-diarization` by default. Add
`--without-diarization` for a smaller app without speaker separation.

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
OpenAI and ElevenLabs keys can be supplied separately in Settings or through
`OPENAI_API_KEY` and `ELEVENLABS_API_KEY`. An OpenAI key entered in the interface stays in
process memory. An ElevenLabs key entered in the interface is saved in macOS Keychain. Keys are
never returned by the API or stored in meeting files, and can be forgotten in Settings. A key
supplied in the environment is loaded again on restart and is not saved.
Do not share the launch URL: it grants access to this local app session.

The tab does not ask the app for news every second. It keeps one connection (server-sent events), and the
app tells it when a meeting, the notes or the settings change; only then does the tab load data. During a
recording or a microphone test, the timer and the level arrive on the same connection. A hidden tab closes
the connection and loads the current state when you show it again. The microphone list is scanned only
while the new-meeting form is open.
