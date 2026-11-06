"""Progress messages and Job phase classification must stay in sync."""
import ast
from pathlib import Path
import unittest

from app.jobs import PHASE_PREFIXES

PROJECT = Path(__file__).resolve().parents[1]
SOURCES = ['app/processing.py', 'app/correction.py', 'app/diarization.py', 'app/analytics.py',
           'app/audio_preparation.py', 'app/model_cache.py', 'app/parakeet.py',
           'app/parakeet_sherpa.py', 'app/voices.py', 'app/service.py']


def leading_text(node):
    """The literal start of a progress() argument: plain, f-string, concatenation or conditional."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return leading_text(node.values[0])
    if isinstance(node, ast.BinOp):
        return leading_text(node.left)
    if isinstance(node, ast.IfExp):
        return leading_text(node.body) or leading_text(node.orelse)
    return ''


def progress_messages():
    messages = []
    for name in SOURCES:
        tree = ast.parse((PROJECT / name).read_text(), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'progress' and node.args:
                text = leading_text(node.args[0])
                if text:
                    messages.append((name, node.lineno, text))
    return messages


class ProgressPhaseTests(unittest.TestCase):
    def test_every_progress_message_has_a_phase(self):
        unmatched = [(name, line, text) for name, line, text in progress_messages()
                     if not any(text.startswith(prefix) for prefix, _ in PHASE_PREFIXES)]
        self.assertEqual(unmatched, [])

    def test_every_phase_prefix_is_used(self):
        messages = [text for _, _, text in progress_messages()]
        unused = [prefix for prefix, _ in PHASE_PREFIXES if not any(text.startswith(prefix) for text in messages)]
        self.assertEqual(unused, [])


if __name__ == '__main__':
    unittest.main()
