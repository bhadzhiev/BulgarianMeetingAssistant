from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock
import wave

import numpy as np

from app import voices
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_people_github import PROJECT

MODEL = 'test-model'


def unit(*values):
    vector = np.zeros(8);vector[:len(values)] = values
    return vector / np.linalg.norm(vector)


def group(name, *vectors):
    return dict(name=name, vectors=[np.asarray(v) for v in vectors], meetings={'m1'})


def prints(**speakers):
    return dict(model=MODEL, speakers={k: dict(vector=list(v), seconds=30.0) for k, v in speakers.items()})


class SuggestTests(unittest.TestCase):
    """A suggestion needs a close voice, a clear gap to another person, and enough audio."""

    def test_close_voice_is_suggested(self):
        result = voices.suggest(prints(SPEAKER_00=unit(1, .1)), {'a': group('Мария', unit(1, .2)), 'b': group('Иван', unit(0, 1))}, set())
        self.assertEqual(result['SPEAKER_00']['name'], 'Мария')

    def test_far_voice_and_near_tie_are_not_suggested(self):
        groups = {'a': group('Мария', unit(1, 0)), 'b': group('Иван', unit(0, 1))}
        self.assertEqual(voices.suggest(prints(SPEAKER_00=unit(1, 1, 1, 1)), groups, set()), {})
        # Both voices are close to the speaker (0.77 and 0.79) but far from each other: no clear answer.
        a, b = np.radians(40), np.radians(38)
        tie = {'a': group('Мария', unit(np.cos(a), np.sin(a))), 'b': group('Иван', unit(np.cos(b), -np.sin(b)))}
        self.assertEqual(voices.suggest(prints(SPEAKER_00=unit(1, 0)), tie, set()), {})

    def test_the_same_voice_under_another_name_is_not_a_rival(self):
        groups = {'a': group('Мария Петрова', unit(1, .05)), 'b': group('Мария', unit(1, -.05))}
        self.assertEqual(voices.suggest(prints(SPEAKER_00=unit(1, .04)), groups, set())['SPEAKER_00']['name'], 'Мария Петрова')

    def test_a_person_wins_over_a_bare_name_of_the_same_voice(self):
        groups = {'a': group('Мария', unit(1, .02)), ('person', 'p1'): dict(group('Мария Петрова', unit(1, .2)), person=True)}
        self.assertEqual(voices.suggest(prints(SPEAKER_00=unit(1, 0)), groups, set())['SPEAKER_00']['name'], 'Мария Петрова')

    def test_people_in_the_meeting_short_audio_and_named_speakers_are_skipped(self):
        groups = {'a': group('Мария', unit(1, 0))}
        self.assertEqual(voices.suggest(prints(SPEAKER_00=unit(1, 0)), groups, {'a'}), {})
        short = prints(SPEAKER_00=unit(1, 0));short['speakers']['SPEAKER_00']['seconds'] = 4
        self.assertEqual(voices.suggest(short, groups, set()), {})
        self.assertEqual(voices.suggest(prints(Иван=unit(1, 0)), groups, set()), {})

    def test_one_person_goes_to_the_closest_speaker_only(self):
        result = voices.suggest(prints(SPEAKER_00=unit(1, .1), SPEAKER_01=unit(1, .3)), {'a': group('Мария', unit(1, 0))}, set())
        self.assertEqual(list(result), ['SPEAKER_00'])


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        rate = 16000
        with wave.open(str(self.dir / 'recording.wav'), 'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate)
            # Loud first half, quiet second half: the fake embedding tells the speakers apart.
            audio.writeframes(np.concatenate([np.full(rate * 30, 8000), np.full(rate * 30, 800)]).astype('<i2').tobytes())
        atomic_json(self.dir / 'speaker-turns.json', [dict(start=0, end=14, speaker='SPEAKER_00'), dict(start=14, end=14.5, speaker='SPEAKER_00'),
                                                     dict(start=30, end=55, speaker='SPEAKER_01')])
        self.embed = lambda samples: np.array([abs(samples).mean(), .1, 0])

    def test_prints_use_long_turns_and_follow_names(self):
        result = voices.compute(self.dir, self.embed, MODEL)
        # Each turn gives at most 10 s, and a turn under 1 s gives nothing.
        self.assertEqual({k: v['seconds'] for k, v in result.items()}, {'SPEAKER_00': 10.0, 'SPEAKER_01': 10.0})
        self.assertAlmostEqual(float(np.linalg.norm(result['SPEAKER_00']['vector'])), 1, places=4)
        self.assertTrue(voices.current(self.dir))
        voices.rename(self.dir, {'SPEAKER_00': 'Мария', 'SPEAKER_01': 'Мария'})
        merged = voices.read(self.dir)['speakers']
        self.assertEqual(list(merged), ['Мария']);self.assertEqual(merged['Мария']['seconds'], 20.0)

    def test_new_turns_make_prints_stale(self):
        voices.compute(self.dir, self.embed, MODEL)
        atomic_json(self.dir / 'speaker-turns.json', [dict(start=0, end=20, speaker='SPEAKER_00')])
        self.assertFalse(voices.current(self.dir))


class ServiceVoiceTests(unittest.TestCase):
    """The meeting view suggests a name from an earlier named meeting, and a name teaches the prints."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.s = MeetingService(root / 'library', PROJECT, google=FakeGoogle(), backup_dir=root / 'archives')
        self.addCleanup(self.s.close)
        self.known = self.meeting('Retro', 'Мария', unit(1, .1))
        self.new = self.meeting('Planning', 'SPEAKER_00', unit(1, .15))

    def meeting(self, title, speaker, vector):
        key = self.s.library.create(title, 'in_person', self.s.settings)['id']
        self.s.library.update(key, status='ready', duration=40)
        directory = self.s.library.directory(key)
        atomic_json(directory / 'transcript.json', [dict(start=0, end=20, speaker=speaker, text='Добре.')])
        atomic_json(directory / 'speaker-turns.json', [dict(start=0, end=20, speaker=speaker)])
        atomic_json(directory / voices.FILE, dict(model=MODEL, turns='x', speakers={speaker: dict(vector=list(vector), seconds=20.0)}))
        return key

    def test_detail_suggests_and_the_applied_name_renames_the_prints(self):
        detail = self.s.detail(self.new)
        self.assertEqual(detail['voice_suggestions']['SPEAKER_00']['name'], 'Мария')
        self.s.edit(self.new, dict(speaker_name=dict(speaker='SPEAKER_00', name='Мария', revision=detail['transcript_revision'])))
        self.assertEqual(list(voices.read(self.s.library.directory(self.new))['speakers']), ['Мария'])
        self.assertTrue(voices.current(self.s.library.directory(self.new)))
        self.assertEqual(self.s.detail(self.new)['voice_suggestions'], {})

    def test_a_person_alias_suggests_the_person_name(self):
        self.s.save_person(dict(name='Мария Петрова', aliases=['Мария']))
        self.assertEqual(self.s.detail(self.new)['voice_suggestions']['SPEAKER_00']['name'], 'Мария Петрова')

    def test_learning_runs_only_for_stale_prints(self):
        directory = self.s.library.directory(self.known)
        stale = self.meeting('Sync', 'Иван', unit(0, 1))
        for key in (self.known, self.new, stale):
            (self.s.library.directory(key) / 'recording.wav').write_bytes(b'')
        (directory / voices.FILE).write_text(json.dumps(dict(voices.read(directory), turns=__import__('hashlib').sha256((directory / 'speaker-turns.json').read_bytes()).hexdigest())))
        calls = []
        with mock.patch('app.diarization.availability', return_value=dict(available=True)), \
             mock.patch.object(self.s, '_execute', side_effect=lambda action, directory, *a, **k: calls.append((action, directory.name))):
            self.s.learn_voices()
            for thread in __import__('threading').enumerate():
                if thread.name != 'MainThread' and thread.daemon and 'learn' in str(getattr(thread, '_target', '')):
                    thread.join(5)
        self.assertEqual(sorted(name for _, name in calls), sorted([self.new, stale]))
        self.assertEqual({a for a, _ in calls}, {'voices'})
        self.assertFalse(self.s.voice_job['running'])

    def test_learning_needs_the_speaker_model(self):
        with mock.patch('app.diarization.availability', return_value=dict(available=False)):
            with self.assertRaisesRegex(ValueError, 'not installed'):
                self.s.learn_voices()


if __name__ == '__main__':
    unittest.main()
