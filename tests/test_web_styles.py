"""Guard the shared select design while retaining intentional compact controls."""
from pathlib import Path
import re
import unittest

CSS = re.sub(r'/\*.*?\*/', '', (Path(__file__).resolve().parents[1] / 'web' / 'style.css').read_text(), flags=re.S)


class SelectStyleTests(unittest.TestCase):
    def test_every_select_uses_the_shared_custom_control(self):
        # WebKit's native control ignores padding and differs from Chromium.
        rules = re.findall(r'(?:^|\})\s*select\{([^}]*)\}', CSS)
        custom = [rule for rule in rules if '-webkit-appearance:none' in rule]
        self.assertEqual(len(custom), 1)
        base = custom[0]
        self.assertIn('-webkit-appearance:none', base)
        self.assertIn('appearance:none', base)
        self.assertIn('height:40px', base)
        self.assertIn('background:var(--card)', base)
        self.assertIn('data:image/svg+xml', base)
        # Compact task/scope controls and the date navigator deliberately use
        # smaller sizes. Ordinary page filters inherit the shared control.
        variants = {
            '.segment .speaker,.tracked-owner-input,.tracked-meta input[type=date],.task-editor input,.task-editor select,.task-bottom select,.work-proposal select,.tracked-edit-bar select',
            '.task-editor select,.task-bottom select,.work-proposal select,.tracked-edit-bar select',
            '.scope-entry select', '.date-popup-head select',
            '.conversation-filters input,.conversation-filters select', '.conversation-filters select',
        }
        for rule, body in re.findall(r'([^{}]*\bselect\b[^{}]*)\{([^}]*)\}', CSS):
            rule = rule.strip()
            if (rule.startswith('select') or rule == 'input,select,textarea'
                    or rule.startswith('input:where(') or ':focus' in rule
                    or 'font:inherit' in body or 'touch-action' in body or rule in variants):
                continue
            self.assertNotRegex(body, r'(?:^|;)(?:padding|font-size|height|background|border)\b', rule)
