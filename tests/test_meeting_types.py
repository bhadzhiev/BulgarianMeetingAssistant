import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import meeting_types, notes, processing
from app.work_items import WorkItemConflict
from app.projects import Projects
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from meeting_assistant import TranscriptSegment, llm_prompt, minutes_schema, save_transcript, validate_minutes
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def item(text, stamp='00:00:00'):
    return dict(text=text, evidence_timestamp=stamp)


def minutes(**fields):
    return dict(dict(summary=[], decisions=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[]), **fields)


class MeetingTypeNotesTests(unittest.TestCase):
    def test_a_type_adds_only_its_own_sections_to_the_schema_and_prompt(self):
        self.assertNotIn('blockers', minutes_schema()['properties'])
        daily = minutes_schema(('today', 'blockers', 'coordination'))
        self.assertIn('blockers', daily['required'])
        self.assertEqual(daily['properties']['blockers'], daily['properties']['summary'])
        general = llm_prompt('[00:00:00] Да.')
        self.assertEqual(general, llm_prompt('[00:00:00] Да.', meeting_type='general'))
        incident = llm_prompt('[00:00:00] Да.', meeting_type='incident')
        self.assertIn('hypotheses: непотвърдени предположения', incident)
        self.assertIn('Разграничавай строго факт от хипотеза', incident)

    def test_sections_are_checked_like_statements_and_never_filled_in(self):
        value = minutes(blockers=[item('Чакам достъп до VPN')])
        validate_minutes(value, [TranscriptSegment(0, 2, 'Чакам достъп.')])
        self.assertEqual(value['blockers'][0]['review'], 'ai')
        self.assertNotIn('facts', value)
        with self.assertRaisesRegex(ValueError, 'does not reference'):
            validate_minutes(minutes(facts=[item('Сайтът спря', '00:09:00')]), [TranscriptSegment(0, 2, 'Да.')])
        with self.assertRaises(ValueError):
            validate_minutes(minutes(unknown=[]))
        changes = notes.changes(minutes(), minutes(hypotheses=[item('Причината е DNS')]))
        self.assertEqual([(c['field'], c['kind']) for c in changes], [('hypotheses', 'added')])


class MeetingTypeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'archives')
        self.addCleanup(self.s.close)
        self.project = self.s.create_project('Platform')['id']

    def series(self, name, kind):
        meeting = self.meeting(name + ' 0', '2026-10-01T09:00:00+03:00')
        self.s.set_scope(meeting, {'id': self.project}, {'name': name})
        series = next(s for s in self.s.projects.data['series'] if s['name'] == name)
        self.s.change_scope('series', series['id'], 'type', kind)
        return series['id']

    def meeting(self, title, when, value=None, series=None):
        meeting = self.s.library.create(title, 'in_person', dict(DEFAULTS, summarizer='local'))
        self.s.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        save_transcript(self.s.library.directory(meeting['id']), [TranscriptSegment(0, 5, 'Чакам достъп до VPN.'), TranscriptSegment(5, 9, 'Може би е DNS.')])
        if series:
            self.s.set_scope(meeting['id'], {'id': self.project}, {'id': series})
        if value:
            self.s.edit(meeting['id'], {'minutes': value})
        return meeting['id']

    def test_meetings_follow_the_series_type_until_a_person_chooses_another(self):
        daily, incidents = self.series('Daily', 'daily'), self.series('Incidents', 'incident')
        meeting = self.meeting('Daily 1', '2026-10-27T09:00:00+03:00', series=daily)
        self.assertEqual(self.s.library.get(meeting)['meeting_type'], 'daily')
        self.s.set_scope(meeting, {'id': self.project}, {'id': incidents})
        self.assertEqual(self.s.library.get(meeting)['meeting_type'], 'incident')
        self.assertEqual(self.s.set_meeting_type(meeting, 'general')['meeting_type'], 'general')
        self.s.set_scope(meeting, {'id': self.project}, {'id': daily})
        self.assertEqual(self.s.library.get(meeting)['meeting_type'], 'general')
        with self.assertRaisesRegex(ValueError, 'Choose a meeting type'):
            self.s.set_meeting_type(meeting, 'party')
        with self.assertRaisesRegex(ValueError, 'Invalid change'):
            self.s.change_scope('projects', self.project, 'type', 'daily')
        self.assertIn('incident', [t['id'] for t in self.s.snapshot()['meeting_types']])

    def test_notes_use_the_meeting_type_and_export_its_sections(self):
        meeting = self.meeting('Incident', '2026-10-27T09:00:00+03:00')
        self.s.set_meeting_type(meeting, 'incident')
        output = minutes(facts=[item('Сайтът не отговаря')], hypotheses=[item('Може би е DNS', '00:00:05')], incident_timeline=[])
        seen = []
        with patch('meeting_assistant.generate_minutes', side_effect=lambda args, group: seen.append(args.meeting_type['id']) or json.loads(json.dumps(output))):
            processing.summarize(self.s.library.directory(meeting), dict(DEFAULTS, summarizer='local'), lambda _: None)
        self.assertEqual(seen, ['incident'])
        directory = self.s.library.directory(meeting)
        saved = json.loads((directory / 'minutes.json').read_text())
        self.assertEqual(saved['hypotheses'][0]['text'], 'Може би е DNS')
        self.assertIn('## Хипотези\n- Може би е DNS (00:00:05)', (directory / 'minutes.md').read_text())

    def test_prepare_for_a_daily_starts_with_blockers_and_stalled_tasks(self):
        daily = self.series('Daily', 'daily')
        self.meeting('Daily 1', '2026-10-26T09:00:00+03:00', minutes(
            blockers=[item('Чакам достъп до VPN')], coordination=[item('Иван и Мария за deploy-а')],
            tasks=[dict(task='Обнови Kubernetes', owner='Иван', deadline=None, due_date=None, evidence_timestamp='00:00:00')]), daily)
        task = next(i for i in self.s.item_list()['items'] if i['kind'] == 'task')
        week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat() + 'T08:00:00+00:00'
        with self.s.items.lock:
            self.s.items.items[task['id']]['created'] = week_ago
            for event in self.s.items.items[task['id']]['history']:
                event['at'] = week_ago
        result = self.s.prepare(series_id=daily)
        self.assertEqual(result['meeting_type'], 'daily')
        titles = [entry['title'] for entry in result['agenda']]
        self.assertEqual(titles[:3], ['Blocker from the last daily: Чакам достъп до VPN', 'Coordinate: Иван и Мария за deploy-а',
                                      'No change for 7 days: Обнови Kubernetes (Иван)'])
        self.assertEqual(titles[-1], 'Plans for today and new blockers')
        self.assertEqual([s['key'] for s in result['sections']], ['blockers', 'coordination'])
        self.assertIn('## Blockers · last meeting\n- Чакам достъп до VPN', result['markdown'])

    def test_prepare_for_an_incident_review_asks_to_confirm_hypotheses(self):
        incidents = self.series('Incidents', 'incident')
        self.meeting('Outage', '2026-10-26T09:00:00+03:00', minutes(
            facts=[item('Сайтът спря за 20 минути')], hypotheses=[item('Може би е DNS', '00:00:05')],
            tasks=[dict(task='Добави алерт за DNS', owner='Мария', deadline=None, due_date='2099-01-01', evidence_timestamp='00:00:05')]), incidents)
        titles = [entry['title'] for entry in self.s.prepare(series_id=incidents)['agenda']]
        self.assertEqual(titles[:2], ['Confirm or reject: Може би е DNS', 'Corrective action: Добави алерт за DNS (Мария) · due 2099-01-01'])
        self.assertIn('What we learned and what changes', titles)
        # A project without a series keeps the general agenda.
        self.assertEqual(self.s.prepare(project_id=self.project)['meeting_type'], 'general')

    def template(self, **values):
        return self.s.save_template(dict(dict(label='Architecture review', prepare='planning',
            sections=[dict(title='Options', instruction='вариантите, които сравнихме', review=True)]), **values))['template']

    def test_own_templates_are_checked_and_meetings_keep_a_copy(self):
        template = self.template()
        for bad, message in ((dict(label='Daily stand-up'), 'built-in type'), (dict(sections=[]), '1 to 3 sections'),
                             (dict(prepare='party'), 'agenda of a built-in'), (dict(sections=[dict(title='A', instruction='x')] * 2), 'own title')):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                self.s.save_template(dict(dict(label='Other', sections=[dict(title='A', instruction='x')]), **bad))
        with self.assertRaisesRegex(ValueError, 'already has this name'):
            self.template(label='ARCHITECTURE review')
        meeting = self.meeting('ADR 12', '2026-10-27T09:00:00+03:00')
        self.s.set_meeting_type(meeting, template['id'])
        self.s.save_template(dict(template, sections=[dict(title='Choices', instruction='друго')]))
        with self.assertRaises(WorkItemConflict):
            self.s.save_template(dict(template, label='Old copy'))
        saved = self.s.library.get(meeting)
        self.assertEqual(saved['meeting_template']['sections'][0]['title'], 'Options')
        self.assertEqual(meeting_types.of(saved)['sections'][0]['attention'][1], 'Check {n} items in Options')
        output = minutes(custom_1=[item('Postgres или DynamoDB')])
        with patch('meeting_assistant.generate_minutes', side_effect=lambda args, group: seen.append(args.meeting_type) or json.loads(json.dumps(output))):
            seen = []
            processing.summarize(self.s.library.directory(meeting), dict(DEFAULTS, summarizer='local'), lambda _: None)
        self.assertEqual(meeting_types.sections(seen[0]), ('custom_1',))
        self.assertIn('custom_1: вариантите, които сравнихме', llm_prompt('[00:00:00] Да.', meeting_type=seen[0]))
        self.assertIn('## Options\n- Postgres или DynamoDB', (self.s.library.directory(meeting) / 'minutes.md').read_text())
        self.assertIn('Architecture review', [t['label'] for t in self.s.snapshot()['meeting_types']])

    def test_deleting_a_template_resets_series_and_keeps_meetings(self):
        template = self.template()
        series = self.series('ADR', template['id'])
        meeting = self.meeting('ADR 1', '2026-10-27T09:00:00+03:00', series=series)
        self.assertEqual(self.s.library.get(meeting)['meeting_type'], template['id'])
        self.assertEqual(self.s.prepare(series_id=series)['meeting_type'], template['id'])
        self.s.delete_template(template['id'], template['revision'])
        self.assertEqual(self.s.projects.series_type(series), 'general')
        self.assertEqual(meeting_types.of(self.s.library.get(meeting))['label'], 'Architecture review')
        with self.assertRaisesRegex(ValueError, 'Choose a meeting type'):
            self.s.set_meeting_type(meeting, template['id'])

    def test_templates_survive_archive_and_restore(self):
        template = self.template()
        name = self.s.create_backup()['created']['name']
        target = MeetingService(self.root / 'target', PROJECT, google=FakeGoogle(), backup_dir=self.s.backup_dir)
        self.addCleanup(target.close)
        target.restore_backup(name)
        self.assertEqual(target.templates.list()[0]['id'], template['id'])

    def test_sprint_review_starts_with_the_work_done_since_the_last_review(self):
        reviews = self.series('Reviews', 'sprint_review')
        self.meeting('Review 1', '2026-10-13T09:00:00+03:00', minutes(
            carry_over=[item('Миграцията не е готова')],
            tasks=[dict(task='Пусни новия login', owner='Мария', deadline=None, due_date=None, evidence_timestamp='00:00:00')]), reviews)
        task = next(i for i in self.s.item_list()['items'] if i['kind'] == 'task')
        self.s.update_item(task['id'], task['text'], {'status': 'done'})
        titles = [entry['title'] for entry in self.s.prepare(series_id=reviews)['agenda']]
        self.assertEqual(titles, ['Show: Пусни новия login (Мария)', 'Not finished last time: Миграцията не е готова', 'Feedback and new requests'])

    def test_each_type_exports_its_own_format(self):
        meeting = self.meeting('DNS outage', '2026-10-25T14:00:00+03:00', minutes(
            facts=[item('Сайтът спря за 20 минути')], hypotheses=[item('Причината е DNS', '00:00:05')],
            observations=[item('Иван изглежда притеснен')],
            tasks=[dict(task='Добави алерт за DNS', owner='Мария', deadline=None, due_date='2026-11-01', evidence_timestamp='00:00:05')]))
        self.s.set_meeting_type(meeting, 'incident')
        task = next(i for i in self.s.item_list()['items'] if i['kind'] == 'task')
        self.s.github_link(dict(resource=dict(kind='item', id=task['id']), reference='org/infra#7'))
        result = self.s.type_export(meeting)
        self.assertEqual((result['title'], result['filename']), ('Postmortem', 'postmortem.md'))
        self.assertIn('- Причината е DNS — непроверено', result['markdown'])
        self.assertIn('| Добави алерт за DNS | Мария | 2026-11-01 | Отворено | [org/infra#7](https://github.com/org/infra/issues/7) |', result['markdown'])
        self.assertNotIn('притеснен', result['markdown'])
        self.assertEqual(self.s.detail(meeting)['github_links'][0]['number'], 7)
        self.s.set_meeting_type(meeting, 'client')
        client = self.s.type_export(meeting)['markdown']
        self.assertNotIn('Добави алерт', client)
        self.assertNotIn('притеснен', client)
        self.s.set_meeting_type(meeting, 'daily')
        daily = self.s.type_export(meeting)['markdown']
        self.assertTrue(daily.startswith('**Daily · DNS outage · 25.10.2026**'))
        self.assertIn('**Блокери**\n- Няма блокери', daily)
        self.assertIn('- [ ] Добави алерт за DNS — Мария · до 2026-11-01', daily)

    def test_archived_series_keep_their_type(self):
        target = Projects(self.root / 'projects.json')
        target.merge(dict(projects=[dict(id='p1', name='Platform')],
                          series=[dict(id='s1', name='Daily', project_id='p1', type='daily'), dict(id='s2', name='Odd', project_id='p1', type='party')]))
        self.assertEqual([target.series_type('s1'), target.series_type('s2')], ['daily', 'general'])
        self.assertNotIn('type', target.get('series', 's2'))


if __name__ == '__main__':
    unittest.main()
