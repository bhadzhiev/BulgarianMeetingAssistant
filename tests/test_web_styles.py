from pathlib import Path
import re
import unittest

CSS = re.sub(r'/\*.*?\*/', '', (Path(__file__).resolve().parents[1] / 'web' / 'style.css').read_text(), flags=re.S)


class SelectStyleTests(unittest.TestCase):
    def test_every_select_has_one_style(self):
        # The native select looks different in WebKit (desktop window) and Chromium and ignores padding.
        self.assertRegex(CSS, r'(?m)^select\{-webkit-appearance:none;appearance:none;height:44px;')
        # Page rules may place a select (width, margin), but must not change its size or look.
        for rule, body in re.findall(r'([^{}]*\bselect\b[^{}]*)\{([^}]*)\}', CSS):
            # The shared base rule for all fields comes first; the later select rule overrides it.
            if rule.strip().startswith('select') or rule.strip() == 'input,select,textarea' or ':focus' in rule or 'font:inherit' in body or 'touch-action' in body:
                continue
            self.assertNotRegex(body, r'(?:^|;)(?:padding|font-size|height|background|border)\b', rule.strip())
