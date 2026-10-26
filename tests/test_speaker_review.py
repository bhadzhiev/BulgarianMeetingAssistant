import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from app import speaker_alignment as alignment, processing, correction, diarization
from app.service import MeetingService, DEFAULTS
from app.storage import atomic_json
from app.items import WorkItemConflict
from tests.test_calendar import FakeGoogle
from tests import test_http

PROJECT = Path(__file__).resolve().parents[1]


def unit(start, end, text, speaker=None):
    return dict(start=start, end=end, text=text, speaker=speaker)


def fixture():
    units = [unit(0, 1, 'Да,'), unit(1, 2, 'започваме.'), unit(2, 3, 'Не,'), unit(3, 4, 'изчакай.')]
    source = alignment.group_units(units)
    saved = dict(version=1, units=units, source_revision=alignment.revision(source))
    timeline = [dict(start=0, end=2, speaker='SPEAKER_00'), dict(start=2, end=4, speaker='SPEAKER_01')]
    return source, saved, timeline


class SpeakerAlignmentTests(unittest.TestCase):
    def test_change_inside_one_segment_splits_without_changing_words_or_times(self):
        source, saved, timeline = fixture()
        self.assertEqual(len(source), 1)
        result = alignment.align(source, saved, timeline)
        self.assertEqual(result, [unit(0, 2, 'Да, започваме.', 'SPEAKER_00'), unit(2, 4, 'Не, изчакай.', 'SPEAKER_01')])
        self.assertEqual(' '.join(s['text'] for s in result), source[0]['text'])
        self.assertIsNone(saved['units'][0]['speaker'])

    def test_existing_note_timestamp_boundaries_survive_alignment(self):
        units=[unit(0,1,'Първа'),unit(1,2,'реплика.'),unit(2,3,'Втора'),unit(3,4,'реплика.')]
        source=[unit(0,2,'Първа реплика.'),unit(2,4,'Втора реплика.')]
        saved=dict(version=1,units=units,source_revision=alignment.revision(source))
        result=alignment.align(source,saved,[dict(start=0,end=4,speaker='SPEAKER_00')])
        self.assertEqual([s['start'] for s in result],[0,2])
        self.assertEqual([s['text'] for s in result],[s['text'] for s in source])

    def test_equal_overlap_and_gaps_do_not_guess_a_speaker(self):
        source = [unit(0, 2, 'Неизвестно'), unit(4, 5, 'Пауза')]
        saved = dict(version=1, source_revision=alignment.revision(source), units=source)
        result = alignment.align(source, saved, [unit(0, 1, '', 'A'), unit(1, 2, '', 'B')])
        self.assertEqual([s['speaker'] for s in result], [None, None])

    def test_edited_transcript_or_invented_word_text_rejects_alignment(self):
        source, saved, timeline = fixture()
        source[0]['text'] += ' Редакция'
        with self.assertRaisesRegex(ValueError, 'current transcript'):
            alignment.align(source, saved, timeline)
        saved['source_revision'] = alignment.revision(source)
        with self.assertRaisesRegex(ValueError, 'text does not match'):
            alignment.align(source, saved, timeline)

    def test_invalid_word_times_do_not_produce_fake_boundaries(self):
        for start, end in [(float('nan'), 2), (2, 1), (-1, 2), ('0', 2)]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                alignment.group_units([unit(start, end, 'Дума')])

    def test_local_transcription_requests_and_publishes_native_word_boundaries(self):
        calls = []
        class Model:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, audio, **kwargs):
                calls.append(kwargs)
                return [SimpleNamespace(t0=i*100, t1=(i+1)*100, text=t) for i,t in enumerate(['Да,', 'започваме.', 'Не,', 'изчакай.'])]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with wave.open(str(directory/'recording.wav'), 'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000*4)
            with patch('pywhispercpp.model.Model', Model), patch('app.processing.ensure_model', return_value='unused'):
                processing.transcribe(directory, dict(DEFAULTS, models_dir=tmp, whisper_vad=False), lambda _: None)
            self.assertTrue(calls[0]['token_timestamps'])
            self.assertTrue(calls[0]['split_on_word'])
            self.assertEqual(calls[0]['max_len'], 1)
            source = json.loads((directory/'transcript.json').read_text())
            saved = json.loads((directory/'transcript.alignment.json').read_text())
            self.assertEqual(saved['source_revision'], alignment.revision(source))
            self.assertEqual(len(saved['units']), 4)
            self.assertEqual(len(source), 1)

    def test_correction_refuses_changed_numbers_negation_and_known_names(self):
        for before, after in [('Сумата е 1200 лева.', 'Сумата е 12000 лева.'),
                              ('Не приемаме офертата.', 'Приемаме офертата.'),
                              ('Мария ще изпрати офертата.', 'Марина ще изпрати офертата.')]:
            self.assertFalse(correction.accept(before, after, ['Мария']))
        self.assertTrue(correction.accept('мария ще изпрати 1200 лева', 'Мария ще изпрати 1200 лева.', ['Мария']))


class SpeakerReviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        self.meeting = self.service.library.create('Synthetic speaker review', 'in_person', dict(DEFAULTS, auto_title=False))
        self.mid = self.meeting['id']; self.directory = self.service.library.directory(self.mid)
        self.service.library.update(self.mid, status='ready', duration=4)
        self.source, self.saved, self.timeline = fixture()
        atomic_json(self.directory/'transcript.json', self.source)
        atomic_json(self.directory/'transcript.alignment.json', self.saved)

    def tearDown(self):
        self.service.close();self.tmp.cleanup()

    def identify(self):
        with patch.object(self.service, '_execute', return_value=self.timeline):
            self.service._run_diarization(self.mid, self.directory, lambda _: None)
        return json.loads((self.directory/'transcript.json').read_text())

    def test_post_recording_alignment_keeps_before_snapshot_and_enables_correction_restore(self):
        result = self.identify()
        self.assertEqual(len(result), 2)
        self.assertEqual(json.loads((self.directory/'transcript.before-speakers.json').read_text()), self.source)
        self.assertIn('word boundaries', self.service.detail(self.mid)['transcript_metadata']['speaker_alignment']['method'])
        with patch('app.correction.ask', return_value={'segments':[dict(id=i,text=s['text']) for i,s in enumerate(result)]}):
            correction.correct(self.directory, dict(DEFAULTS, transcript_correction='local'), lambda _: None)
        self.assertEqual(json.loads((self.directory/'transcript.raw.json').read_text()), result)

    def test_stale_alignment_falls_back_without_overwriting_edited_text(self):
        edited = [dict(self.source[0], text='Ръчно редактиран текст.')]
        atomic_json(self.directory/'transcript.json', edited)
        self.assertEqual(self.identify()[0]['text'], edited[0]['text'])
        self.assertEqual(self.service.detail(self.mid)['transcript_metadata']['speaker_alignment']['method'], 'segment overlap')

    def test_manual_names_are_not_overwritten_by_another_diarization_run(self):
        named = [dict(self.source[0], speaker='Мария')]
        atomic_json(self.directory/'transcript.json', named)
        with patch.object(self.service, '_execute') as model:
            self.service._run_diarization(self.mid, self.directory, lambda _: None)
        model.assert_not_called()
        self.assertEqual(json.loads((self.directory/'transcript.json').read_text()), named)

    def test_confirmed_name_updates_all_turns_and_rejects_stale_review(self):
        self.identify()
        atomic_json(self.directory/'speaker-timeline.json', self.timeline)
        atomic_json(self.directory/'speaker-turns.json', self.timeline)
        revision = self.service.detail(self.mid)['transcript_revision']
        result = self.service.edit(self.mid, dict(speaker_name=dict(speaker='SPEAKER_00', name='Мария', revision=revision)))
        self.assertEqual(result['transcript'][0]['speaker'], 'Мария')
        for filename in ['speaker-timeline.json','speaker-turns.json']:
            self.assertEqual(json.loads((self.directory/filename).read_text())[0]['speaker'], 'Мария')
        with self.assertRaises(WorkItemConflict):
            self.service.edit(self.mid, dict(speaker_name=dict(speaker='SPEAKER_01', name='Иван', revision=revision)))
        self.assertEqual(json.loads((self.directory/'transcript.before-speakers.json').read_text()), self.source)

    def test_explicit_speaker_job_needs_audio_and_final_transcript(self):
        with self.assertRaisesRegex(ValueError, 'saved recording'):
            self.service.process(self.mid, 'speakers')
        self.assertNotIn(self.mid, self.service.busy)


class SpeakerReviewHTTPTests(unittest.TestCase):
    setUp, tearDown, request = test_http.HTTPTests.setUp, test_http.HTTPTests.tearDown, test_http.HTTPTests.request

    def test_stale_speaker_review_returns_conflict(self):
        meeting = self.service.library.create('Synthetic review', 'in_person', dict(DEFAULTS, auto_title=False))
        self.service.library.update(meeting['id'], status='ready', duration=2)
        atomic_json(self.service.library.directory(meeting['id'])/'transcript.json', [unit(0, 2, 'Здравей', 'SPEAKER_00')])
        status, body, _ = self.request('/api/meetings/'+meeting['id']+'/edit', dict(speaker_name=dict(speaker='SPEAKER_00', name='Мария', revision='stale')))
        self.assertEqual(status, 409, body)


class DiarizationOutputTests(unittest.TestCase):
    def test_exclusive_turns_are_saved_separately_from_overlap_statistics(self):
        import sys
        from types import ModuleType
        regular = [(SimpleNamespace(start=0, end=3), None, 'SPEAKER_00'), (SimpleNamespace(start=2, end=4), None, 'SPEAKER_01')]
        exclusive = [(SimpleNamespace(start=0, end=2), None, 'SPEAKER_00'), (SimpleNamespace(start=2, end=4), None, 'SPEAKER_01')]
        output = SimpleNamespace(speaker_diarization=SimpleNamespace(itertracks=lambda **_:iter(regular)),
                                 exclusive_speaker_diarization=SimpleNamespace(itertracks=lambda **_:iter(exclusive)))
        fake_audio = ModuleType('pyannote.audio');fake_audio.Pipeline = object
        fake_torch = ModuleType('torch')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {'torch':fake_torch, 'pyannote.audio':fake_audio}), patch('app.diarization._pipeline', lambda _:output):
            directory=Path(tmp);(directory/'recording.wav').write_bytes(b'not read by fake model')
            timeline=diarization.diarize(directory)
            turns=json.loads((directory/'speaker-turns.json').read_text())
            self.assertEqual(timeline[0]['end'],3)
            self.assertEqual(turns[0]['end'],2)
            self.assertTrue(json.loads((directory/'speaker-diarization.json').read_text())['exclusive'])

    def test_runtime_check_does_not_import_or_initialize_torch(self):
        diarization.availability.cache_clear()
        try:
            with patch('app.diarization.importlib.util.find_spec', return_value=None) as lookup:
                self.assertFalse(diarization.availability()['available'])
                self.assertEqual(lookup.call_count,1)
        finally:diarization.availability.cache_clear()


class WhisperEvaluationTests(unittest.TestCase):
    def test_human_reference_metric_counts_changed_words_and_ignores_case_punctuation(self):
        from scripts.evaluate_whisper import word_error_rate
        self.assertEqual(word_error_rate('Здравей, Мария!', 'здравей мария'),0)
        self.assertAlmostEqual(word_error_rate('Не приемаме офертата', 'Приемаме офертата'),1/3)
        self.assertAlmostEqual(word_error_rate('Сумата е 1200', 'Сумата е 12000'),1/3)
        with self.assertRaises(ValueError):word_error_rate('...','Нещо')


class SpeakerRuntimeCacheTests(unittest.TestCase):
    def test_speaker_worker_reuses_private_cache_for_same_bundle(self):
        import os
        from app.worker import configure_speaker_runtime
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MPLCONFIGDIR':'old-temporary-cache'}):
            directory=Path(tmp)/('a'*32);directory.mkdir()
            configure_speaker_runtime(directory)
            cache=Path(os.environ['MPLCONFIGDIR'])
            self.assertTrue(cache.is_dir())
            self.assertEqual(cache.parent.name,'.speaker-runtime-cache')
            self.assertEqual(os.environ['MPLBACKEND'],'Agg')
            configure_speaker_runtime(directory)
            self.assertEqual(Path(os.environ['MPLCONFIGDIR']),cache)
