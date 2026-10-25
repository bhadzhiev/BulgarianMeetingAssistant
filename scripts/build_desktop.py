#!/usr/bin/env python3
"""Build the Python sidecar and a macOS .app. Run in a packaging virtual environment.

Requires: pip install -r requirements.txt pyinstaller; npm --prefix desktop ci; Rust; Xcode tools.
Optional: --ffmpeg-dir with self-contained ffmpeg and ffprobe binaries for distribution.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-dir', type=Path)
    parser.add_argument('--debug', action='store_true', help='Build a development app bundle')
    args = parser.parse_args()
    subprocess.run([str(ROOT / 'build_native.sh')], cwd=ROOT, check=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'meeting-backend', '--distpath', str(ROOT / 'build/desktop-backend'),
               '--workpath', str(ROOT / 'build/pyinstaller'), '--specpath', str(ROOT / 'build'),
               '--collect-all', 'pywhispercpp', '--collect-all', 'sounddevice',
               '--add-data', f'{ROOT / "web"}:web', '--add-binary', f'{ROOT / "bin/SystemAudio"}:bin']
    if args.ffmpeg_dir:
        for name in ('ffmpeg', 'ffprobe'):
            path = args.ffmpeg_dir / name
            if not path.is_file():
                parser.error(f'{path} is missing')
            command.extend(['--add-binary', f'{path}:bin'])
    else:
        print('This build requires ffmpeg and ffprobe installed on the target Mac (brew install ffmpeg).', flush=True)
    command.append(str(ROOT / 'desktop_app.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    config = ROOT / 'build/desktop-bundle.json'
    config.write_text(json.dumps({'bundle': {'resources': {str(ROOT / 'build/desktop-backend'): 'backend/'}}}))
    build = ['npm', '--prefix', str(ROOT / 'desktop'), 'run', 'tauri', '--', 'build',
             '--bundles', 'app', '--config', str(config)]
    if args.debug:
        build.append('--debug')
    subprocess.run(build, cwd=ROOT / 'desktop', check=True)


if __name__ == '__main__':
    main()
