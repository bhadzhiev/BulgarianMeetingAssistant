#!/usr/bin/env python3
"""Build the Python sidecar and a macOS .app. Run in a packaging virtual environment.

Requires: pip install -r requirements.txt pyinstaller; npm --prefix desktop ci; Rust; Xcode tools.
Optional: --ffmpeg-dir with self-contained ffmpeg and ffprobe binaries for distribution.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]



def keep_backend_links(app: Path, backend: Path, entitlements: Path) -> None:
    """Copy the backend into the app again with its symbolic links, then sign the app again.

    PyInstaller links shared libraries in _internal to their packages. Tauri copies resources through
    the links, so the app holds those libraries twice (about 440 MB), and mlx/core loads a copy of
    libmlx.dylib that has no mlx.metallib next to it: MLX then stops the process when it opens Metal.
    """
    target = app / 'Contents' / 'Resources' / 'backend' / backend.name
    if not target.is_dir():
        raise SystemExit(f'The app has no backend at {target}')
    shutil.rmtree(target)
    subprocess.run(['ditto', str(backend), str(target)], check=True)
    # The same ad-hoc signature that Tauri makes: hardened runtime with the app's entitlements.
    subprocess.run(['codesign', '--force', '--sign', '-', '--options', 'runtime', '--entitlements', str(entitlements), str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-dir', type=Path)
    parser.add_argument('--with-diarization', action='store_true', help='Bundle installed pyannote/torch speaker dependencies')
    parser.add_argument('--with-parakeet', action='store_true', help='Bundle installed Apple Silicon Parakeet MLX dependencies')
    parser.add_argument('--debug', action='store_true', help='Build a development app bundle')
    args = parser.parse_args()
    if args.with_diarization:
        sys.path.insert(0, str(ROOT))
        from app.diarization import availability
        if not availability()['available']:
            parser.error('Install requirements-diarization.txt in the packaging environment first')
    if args.with_parakeet:
        sys.path.insert(0, str(ROOT))
        from app.parakeet import availability
        if not availability()['available']:
            parser.error('Parakeet requires Apple Silicon and requirements-parakeet.txt in the packaging environment')
    subprocess.run([str(ROOT / 'build_native.sh')], cwd=ROOT, check=True)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'meeting-backend', '--distpath', str(ROOT / 'build/desktop-backend'),
               '--workpath', str(ROOT / 'build/pyinstaller'), '--specpath', str(ROOT / 'build'),
               '--collect-all', 'pywhispercpp', '--collect-all', 'sounddevice',
               '--add-data', f'{ROOT / "web"}:web', '--add-binary', f'{ROOT / "bin/SystemAudio"}:bin']
    if args.with_diarization:
        for package in ('torch', 'torchaudio', 'torchcodec', 'pyannote.audio', 'pyannote.core', 'pyannote.pipeline'):
            command.extend(['--collect-all', package])
    if args.with_parakeet:
        for package in ('parakeet_mlx', 'mlx', 'librosa'):
            command.extend(['--collect-all', package])
    else:
        command.extend(['--exclude-module', 'parakeet_mlx', '--exclude-module', 'mlx'])
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
    product = json.loads((ROOT / 'desktop/src-tauri/tauri.conf.json').read_text())['productName']
    app = ROOT / 'desktop/src-tauri/target' / ('debug' if args.debug else 'release') / 'bundle/macos' / (product + '.app')
    keep_backend_links(app, ROOT / 'build/desktop-backend/meeting-backend', ROOT / 'desktop/src-tauri/Entitlements.plist')


if __name__ == '__main__':
    main()
