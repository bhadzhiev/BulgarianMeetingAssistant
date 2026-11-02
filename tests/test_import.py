import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.transcripts import parse_transcript
from tests.test_calendar import FakeGoogle
from tests.test_http import HTTPTests

PROJECT=Path(__file__).resolve().parents[1]
EMAIL='''Transcript: DevOps sync, 19 Oct 2026
Inbox

DevOps sync, 19 Oct 2026: transcript
Ivan Petrov, Maria Georgieva. Bulgarian, clean verbatim, from the recording (42 min).

[00:00:00] Ivan Petrov: Добро утро. Да започваме.
Продължение на същия ред.

[00:01:07] Maria Georgieva: Добре, това е новият график.

[00:01:17] Ivan Petrov: Исках да питам: това ли е графикът?

[00:01:51] Защото пише: версия 2.


         Ivan Petrov
Project Manager
'''


class ParseTests(unittest.TestCase):
    def test_email_transcript(self):
        result=parse_transcript(EMAIL)
        self.assertEqual((result['title'],result['date']),('DevOps sync, 19 Oct 2026',dt.date(2026,10,19)))
        segments=result['segments']
        self.assertEqual([s['speaker'] for s in segments],['Ivan Petrov','Maria Georgieva','Ivan Petrov',None])
        self.assertEqual(segments[0]['text'],'Добро утро. Да започваме. Продължение на същия ред.')
        self.assertEqual(segments[2]['text'],'Исках да питам: това ли е графикът?')
        self.assertEqual(segments[3]['text'],'Защото пише: версия 2.')  # the signature after a blank line is dropped
        self.assertEqual((segments[0]['end'],segments[1]['start']),(67,67))
    def test_srt(self):
        segments=parse_transcript('1\n00:00:01,000 --> 00:00:03,500\nИван: здравей\n')['segments']
        self.assertEqual(segments,[dict(start=1,end=3.5,text='здравей',speaker='Иван')])
    def test_rejects_reversed_cues_and_impossible_times(self):
        for text in ['1\n00:00:05,000 --> 00:00:02,000\nТекст\n', '1\n00:75:00,000 --> 00:76:00,000\nТекст\n',
                     '1\n00:00:01,000 --> 00:00:61,000\nТекст\n', '[00:00:75] Иван: Здравей\n', '[01:60:00] Иван: Здравей\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_transcript(text)
        self.assertEqual(parse_transcript('[75:30] Иван: Здравей\n')['segments'][0]['start'], 4530)

    def test_rejects_text_without_timestamps_or_going_back(self):
        with self.assertRaisesRegex(ValueError,'No timestamps'):parse_transcript('Просто текст')
        with self.assertRaisesRegex(ValueError,'forward'):parse_transcript('[00:01:00] a\n[00:00:10] b\n')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle())
        self.service.settings.update(auto_process=False)
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def test_import_creates_ready_meeting_with_same_markdown(self):
        d=self.service.import_transcript(EMAIL,'mail.txt')
        self.assertEqual((d['title'],d['mode'],d['status']),('DevOps sync, 19 Oct 2026','imported','ready'))
        self.assertTrue(d['created'].startswith('2026-10-19'))
        self.assertEqual(len(d['transcript']),4);self.assertNotIn('recording.wav',d['files'])
        text=(self.service.library.directory(d['id'])/'transcript.md').read_text()
        self.assertTrue(text.startswith('# DevOps sync, 19 Oct 2026: transcript\n\nIvan Petrov, Maria Georgieva. 2 min.\n\n[00:00:00] Ivan Petrov: Добро'))
        self.assertIn('\n\n[00:01:07] Maria Georgieva: Добре, това е новият график.\n',text)
        self.assertIn('Maria Georgieva',self.service.library.speakers())
        with self.assertRaisesRegex(ValueError,'no audio'):self.service.process(d['id'],'transcribe')
    def test_rename_updates_markdown_heading(self):
        d=self.service.import_transcript('[00:00:00] Иван: здравей\n','среща.md')
        self.assertEqual(d['title'],'среща')
        self.service.edit(d['id'],{'title':'Нова среща'})
        self.assertTrue((self.service.library.directory(d['id'])/'transcript.md').read_text().startswith('# Нова среща: transcript'))


class ImportHTTPTests(unittest.TestCase):
    setUp,tearDown,request=HTTPTests.setUp,HTTPTests.tearDown,HTTPTests.request
    def test_import_route(self):
        self.service.settings.update(auto_process=False)
        status,body,_=self.request('/api/import',{'text':EMAIL,'filename':'mail.txt'})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['mode'],'imported')
        status,body,_=self.request('/api/import',{'text':'без време'})
        self.assertEqual(status,400);self.assertIn('No timestamps',json.loads(body)['error'])


if __name__=='__main__':
    unittest.main()
