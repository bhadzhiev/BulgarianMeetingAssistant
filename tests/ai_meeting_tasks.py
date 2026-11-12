"""Module fixtures for tests of the AI meeting tasks: proposals, matching and links from meeting notes.

These features are off by default since 2026-11-12 (the person makes tasks from the notes by hand). A test module
that covers them imports setUpModule and tearDownModule from here, so each service in it starts with them on.
"""
from app import service

_saved = []


def setUpModule():
    _saved.append(service.DEFAULTS['meeting_task_ai'])
    service.DEFAULTS['meeting_task_ai'] = True


def tearDownModule():
    service.DEFAULTS['meeting_task_ai'] = _saved.pop()
