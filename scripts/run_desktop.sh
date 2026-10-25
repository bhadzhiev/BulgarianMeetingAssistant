#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export BMA_DEV_ROOT="$task_root"
export BMA_PYTHON="${BMA_PYTHON:-$task_root/.venv/bin/python}"
# A terminal or IDE that started before Rust was installed does not have rustup's folder on its PATH.
if ! command -v cargo >/dev/null 2>&1; then
  if [ -x "$HOME/.cargo/bin/cargo" ]; then
    PATH="$HOME/.cargo/bin:$PATH"
  else
    echo "Rust is not installed. Install it from https://rustup.rs, then run this script again." >&2
    exit 1
  fi
fi
exec cargo run --manifest-path "$task_root/desktop/src-tauri/Cargo.toml"
