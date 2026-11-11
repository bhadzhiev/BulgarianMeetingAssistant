#!/bin/sh
# Build the desktop app and install it, or replace an installed copy.
# Usage: scripts/install_desktop.sh [--debug] [--ffmpeg-dir DIR] [--without-diarization] [--without-parakeet] [--without-parakeet-sherpa]
# The build includes speaker diarization by default. --without-diarization leaves it out.
# BMA_INSTALL_DIR selects the install folder (default /Applications).
# BMA_BUILD_VENV selects the packaging virtual environment (default .venv-build).
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
app_name="Atlanta.app"
# The app had this name before. The same app (same identifier) replaces it.
legacy_name="Bulgarian Meeting Assistant.app"
app_id="io.github.bhadzhiev.meeting-assistant"
install_dir="${BMA_INSTALL_DIR:-/Applications}"
build_venv="${BMA_BUILD_VENV:-$task_root/.venv-build}"

# One install at a time. Two builds share build/ and desktop/src-tauri/target/, and a bundle made of
# both does not start (missing base_library.zip, or "PYZ archive entry not found in the TOC").
lock="$task_root/build/install.lock"
locked=false
release_lock() {
  if [ "$locked" = true ]; then rm -rf "$lock"; locked=false; fi
}
mkdir -p "$task_root/build"
if ! mkdir "$lock" 2>/dev/null; then
  holder=$(cat "$lock/pid" 2>/dev/null || true)
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    echo "Another install is running (process $holder). Wait until it ends, then run this script again." >&2
    exit 1
  fi
  # The last install stopped without removing its lock.
  rm -rf "$lock"
  if ! mkdir "$lock" 2>/dev/null; then
    echo "Another install started just now. Wait until it ends, then run this script again." >&2
    exit 1
  fi
fi
locked=true
echo $$ > "$lock/pid"
trap release_lock 0
trap 'exit 1' HUP INT TERM

profile=release
diarization=yes
parakeet=no
parakeet_sherpa=yes
[ "$(uname -sm)" != "Darwin arm64" ] || parakeet=yes
for arg in "$@"; do
  shift
  case "$arg" in
    --debug) profile=debug ;;
    --without-diarization) diarization=no; continue ;;
    --with-diarization) continue ;;
    --without-parakeet-sherpa) parakeet_sherpa=no; continue ;;
    --with-parakeet-sherpa) parakeet_sherpa=yes; continue ;;
    --without-parakeet) parakeet=no; continue ;;
    --with-parakeet) parakeet=yes; continue ;;
  esac
  set -- "$@" "$arg"
done
[ "$diarization" = yes ] && set -- "$@" --with-diarization
[ "$parakeet" = yes ] && set -- "$@" --with-parakeet
[ "$parakeet_sherpa" = yes ] && set -- "$@" --with-parakeet-sherpa

# A terminal or IDE that started before Rust was installed does not have rustup's folder on its PATH.
if ! command -v cargo >/dev/null 2>&1; then
  if [ -x "$HOME/.cargo/bin/cargo" ]; then
    PATH="$HOME/.cargo/bin:$PATH"
  else
    echo "Rust is not installed. Install it from https://rustup.rs, then run this script again." >&2
    exit 1
  fi
fi
for tool in npm xcrun python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is not installed." >&2
    exit 1
  fi
done
command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg is not installed. The app needs it (brew install ffmpeg)." >&2

echo "==> Prepare the packaging environment in $build_venv"
[ -x "$build_venv/bin/python" ] || python3 -m venv "$build_venv"
"$build_venv/bin/python" -m pip install --quiet --upgrade pip
if [ "$diarization" = yes ]; then
  echo "==> Include speaker diarization (pyannote and torch)"
  "$build_venv/bin/python" -m pip install --quiet -r "$task_root/requirements.txt" \
    -r "$task_root/requirements-diarization.txt" -c "$task_root/requirements.lock" pyinstaller
else
  "$build_venv/bin/python" -m pip install --quiet -r "$task_root/requirements.txt" \
    -c "$task_root/requirements.lock" pyinstaller
fi

if [ "$parakeet" = yes ]; then
  echo "==> Include local Parakeet v3 (Apple Silicon)"
  "$build_venv/bin/python" -m pip install --quiet -r "$task_root/requirements-parakeet.txt" -c "$task_root/requirements.lock"
fi

if [ "$parakeet_sherpa" = yes ]; then
  echo "==> Include experimental Parakeet vocabulary backend"
  "$build_venv/bin/python" -m pip install --quiet -r "$task_root/requirements-parakeet-sherpa.txt" -c "$task_root/requirements.lock"
fi

marker="$task_root/desktop/node_modules/.package-lock.json"
if [ ! -f "$marker" ] || [ "$task_root/desktop/package-lock.json" -nt "$marker" ]; then
  echo "==> Install the Tauri CLI"
  npm --prefix "$task_root/desktop" ci
fi

echo "==> Build the app ($profile)"
"$build_venv/bin/python" "$task_root/scripts/build_desktop.py" "$@"
built_app="$task_root/desktop/src-tauri/target/$profile/bundle/macos/$app_name"
if [ ! -d "$built_app" ]; then
  echo "The build did not make $built_app." >&2
  exit 1
fi

# Copy and verify before touching the installed app. Keep the previous bundle.
target="$install_dir/$app_name"
mkdir -p "$install_dir"
staging=$(mktemp -d "$install_dir/.bma-install.XXXXXX")
previous=""
installed=false
cleanup_install() {
  if [ "$installed" = false ] && [ -n "$previous" ] && [ -e "$previous/$app_name" ] && [ ! -e "$target" ]; then
    mv "$previous/$app_name" "$target"
  fi
  if [ -n "$staging" ] && [ -d "$staging" ]; then rm -rf "$staging"; fi
  if [ -n "$previous" ]; then rmdir "$previous" 2>/dev/null || true; fi
  release_lock
}
trap cleanup_install 0
trap 'exit 1' HUP INT TERM
ditto "$built_app" "$staging/$app_name"
codesign --verify --deep --strict "$staging/$app_name"

# The app saves an active recording when it quits, so ask it to quit and wait.
if [ "$(osascript -e "application id \"$app_id\" is running")" = "true" ]; then
  echo "==> Quit the running app"
  osascript -e "tell application id \"$app_id\" to quit"
  waited=0
  while [ "$(osascript -e "application id \"$app_id\" is running")" = "true" ]; do
    if [ "$waited" -ge 120 ]; then
      echo "The app did not quit in 120 seconds. Quit it, then run this script again." >&2
      exit 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
fi

echo "==> Install to $target"
if [ -e "$target" ]; then
  previous=$(mktemp -d "$install_dir/.bma-previous.XXXXXX")
  mv "$target" "$previous/$app_name"
fi
mv "$staging/$app_name" "$target"
installed=true
[ -z "$previous" ] || echo "Previous app kept at: $previous/$app_name"
if [ -e "$install_dir/$legacy_name" ]; then
  previous=${previous:-$(mktemp -d "$install_dir/.bma-previous.XXXXXX")}
  mv "$install_dir/$legacy_name" "$previous/$legacy_name"
  echo "The app is now named Atlanta. The old copy is kept at: $previous/$legacy_name"
fi
printf 'Installed. Open it with: open "%s"\n' "$target"
