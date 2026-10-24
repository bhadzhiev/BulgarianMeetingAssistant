#!/bin/zsh
set -eu
cd "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [[ ! -x .venv/bin/python ]]; then
  echo 'First run: creating the Python environment…'
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
if ! command -v ffmpeg >/dev/null; then
  echo 'Install ffmpeg with: brew install ffmpeg'
  read -r '?Press Return to close.'
  exit 1
fi
if [[ ! -x bin/SystemAudio || native/SystemAudio.swift -nt bin/SystemAudio ]]; then
  echo 'Building Mac system audio support…'
  ./build_native.sh
fi
exec .venv/bin/python desktop_app.py
