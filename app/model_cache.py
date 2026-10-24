"""Download complete model files atomically; interrupted live workers leave no valid-looking partial model."""
from pathlib import Path
import os


def ensure_model(name: str, directory: Path, progress=lambda _: None) -> str:
    from pywhispercpp.constants import AVAILABLE_MODELS, MODELS_BASE_URL, MODELS_PREFIX_URL
    import requests
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
    partial = directory / (destination.name + '.download')
    url = f'{MODELS_BASE_URL}/{MODELS_PREFIX_URL}-{name}.bin'
    try:
        with requests.get(url, stream=True, timeout=(20, 60)) as response:
            response.raise_for_status()
            expected = int(response.headers.get('content-length', 0))
            received, last_percent = 0, -1
            with partial.open('wb') as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / expected) if expected else 0
                    if percent != last_percent:
                        progress(f'Downloading {name} · {percent}%' if expected else f'Downloading {name} · {received // 1048576} MB')
                        last_percent = percent
                output.flush()
                os.fsync(output.fileno())
            if not received or expected and received != expected:
                raise RuntimeError('Incomplete Whisper model download. Retry to download it again.')
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return str(destination.resolve())
