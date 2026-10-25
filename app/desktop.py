"""Private parent/child control channel for the desktop window (never an HTTP endpoint)."""
from __future__ import annotations

import json
import threading


def watch_parent(stream, shutdown):
    """Quit on an explicit command or EOF, including when the window process crashes."""
    def read():
        for line in stream:
            if line.strip() == 'shutdown':
                break
        shutdown()
    thread = threading.Thread(target=read, name='desktop-parent', daemon=True)
    thread.start()
    return thread


def ready(url):
    # stdout is a private pipe to the native parent; do not write the credential to logs.
    print(json.dumps({'event': 'ready', 'url': url}), flush=True)
