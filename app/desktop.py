"""Private parent/child control channel for the desktop window (never an HTTP endpoint)."""
from __future__ import annotations

import json
import os
import sys
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


def control_output():
    """Keep readiness on its own pipe; send Python and native stdout diagnostics to the log."""
    sys.stdout.flush()
    output = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return output


def ready(url, output):
    # stdout is a private pipe to the native parent; do not write the credential to logs.
    print(json.dumps({'event': 'ready', 'url': url}), file=output, flush=True)
