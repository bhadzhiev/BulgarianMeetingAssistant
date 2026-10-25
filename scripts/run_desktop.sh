#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export BMA_DEV_ROOT="$task_root"
export BMA_PYTHON="${BMA_PYTHON:-$task_root/.venv/bin/python}"
exec cargo run --manifest-path "$task_root/desktop/src-tauri/Cargo.toml"
