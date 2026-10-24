"""Download complete model files atomically; interrupted live workers leave no valid-looking partial model."""
from pathlib import Path
import hashlib
import os

VAD_MODEL = 'ggml-silero-v5.1.2.bin'
VAD_URL = 'https://huggingface.co/ggml-org/whisper-vad/resolve/main/' + VAD_MODEL
VAD_SHA256 = '29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf'


def ensure_model(name: str, directory: Path, progress=lambda _: None) -> str:
    from pywhispercpp.constants import AVAILABLE_MODELS, MODELS_BASE_URL, MODELS_PREFIX_URL
    direct = Path(name)
    if direct.is_file():
        return str(direct.resolve())
    directory.mkdir(parents=True, exist_ok=True)
    filename = Path(f'{MODELS_PREFIX_URL}-{name}.bin').name
    for candidate in [directory / name, directory / f'{name}.bin', directory / filename]:
        if candidate.is_file():
            return str(candidate.resolve())
    if name not in AVAILABLE_MODELS:
        raise ValueError(f'Unknown local Whisper model: {name}')
    destination = directory / filename
    download(f'{MODELS_BASE_URL}/{MODELS_PREFIX_URL}-{name}.bin', destination, name, progress)
    return str(destination.resolve())


def ensure_vad_model(directory: Path, progress=lambda _: None) -> str:
    """The Silero voice detector that whisper.cpp uses to skip silence (under 1 MB)."""
    destination = directory / VAD_MODEL
    if not destination.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        download(VAD_URL, destination, 'voice detection model', progress, VAD_SHA256)
    return str(destination.resolve())


def download(url: str, destination: Path, name: str, progress, sha256: str | None = None) -> None:
    import requests
    partial = destination.parent / (destination.name + '.download')
    try:
        with requests.get(url, stream=True, timeout=(20, 60)) as response:
            response.raise_for_status()
            expected = int(response.headers.get('content-length', 0))
            received, last_percent = 0, -1
            digest = hashlib.sha256()
            with partial.open('wb') as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / expected) if expected else 0
                    if percent != last_percent:
                        progress(f'Downloading {name} · {percent}%' if expected else f'Downloading {name} · {received // 1048576} MB')
                        last_percent = percent
                output.flush()
                os.fsync(output.fileno())
            if not received or expected and received != expected:
                raise RuntimeError(f'Incomplete {name} download. Retry to download it again.')
            if sha256 and digest.hexdigest() != sha256:
                raise RuntimeError(f'The downloaded {name} is not the expected file.')
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
