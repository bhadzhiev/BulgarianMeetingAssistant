from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.github_links import parse
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
ROWS = [dict(start=0, end=10, speaker='SPEAKER_00', text='Добро утро.'),
        dict(start=12, end=20, speaker='Иван', text='Ще обновя Kubernetes клъстера до петък.'),
        dict(start=22, end=30, speaker='Мария', text='Решено: тестваме възстановяване всяка седмица.')]


class PeopleAndGitHubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'archives')
        self.addCleanup(self.s.close)
        self.project = self.s.create_project('Platform')['id']
        meeting = self.s.library.create('Platform sync', 'in_person', self.s.settings)
        self.meeting = meeting['id']
        self.s.library.update(self.meeting, created='2026-10-27T08:00:00Z', started_at='2026-10-27T08:00:00Z', status='ready', duration=40, project_id=self.project)
        atomic_json(self.s.library.directory(self.meeting) / 'transcript.json', ROWS)
        self.s.edit(self.meeting, dict(minutes=dict(summary=[], open_questions=[],
            tasks=[dict(task='Обнови Kubernetes клъстера', owner='Иван', deadline='петък', evidence_timestamp='00:00:12')],
            decisions=[dict(text='Тестваме възстановяване всяка седмица', evidence_timestamp='00:00:22', review='verified')])))
        self.task = next(i for i in self.s.item_list()['items'] if i['kind'] == 'task')

    def person(self, **values):
        return self.s.save_person(dict(dict(name='Иван Петров', aliases=['Иван'], emails=['ivan@example.invalid']), **values))['person']

    def test_people_keep_names_and_github_accounts_unique_and_check_revisions(self):
        ivan = self.person(github=dict(login='ivan-p', id=101))
        with self.assertRaisesRegex(ValueError, 'already belongs to Иван Петров'):
            self.s.save_person(dict(name='Друг', aliases=['ИВАН']))
        with self.assertRaisesRegex(ValueError, 'GitHub account already belongs'):
            self.s.save_person(dict(name='Мария', github=dict(login='other', id=101)))
        with self.assertRaisesRegex(ValueError, 'not an email'):
            self.s.save_person(dict(name='Мария', emails=['not-an-email']))
        updated = self.s.save_person(dict(ivan, notes='DevOps'))['person']
        self.assertEqual(updated['revision'], 2)
        with self.assertRaises(WorkItemConflict):
            self.s.save_person(dict(ivan, notes='old copy'))
        self.assertEqual(self.s.people.match('  иван ')['id'], ivan['id'])
        self.assertIn('people', self.s.snapshot())

    def test_profile_separates_confirmed_commitments_from_ai_suggestions(self):
        ivan = self.person()
        profile = self.s.person_profile(ivan['id'])
        self.assertEqual((profile['statements'], profile['meetings']), (1, 1))
        self.assertEqual(profile['said'][0]['text'], 'Ще обновя Kubernetes клъстера до петък.')
        self.assertEqual((profile['commitments'], [t['id'] for t in profile['suggested']]), ([], [self.task['id']]))
        self.s.update_item(self.task['id'], self.task['text'], {'owner': 'Иван'})
        profile = self.s.person_profile(ivan['id'])
        self.assertEqual(([t['id'] for t in profile['commitments']], profile['suggested']), ([self.task['id']], []))

    def test_project_repositories_are_validated_and_shared_between_projects(self):
        other = self.s.create_project('Infra')['id']
        self.assertEqual(self.s.set_project_repositories(self.project, ['org/deploy', ' Org/Deploy ', 'org/infra'])['repositories'], ['org/deploy', 'org/infra'])
        self.s.set_project_repositories(other, ['org/deploy'])
        with self.assertRaises(ValueError):
            self.s.set_project_repositories(self.project, ['not a repository'])
        self.assertEqual(self.s.projects.get('projects', other)['repositories'], ['org/deploy'])

    def test_issue_draft_quotes_the_moment_and_publishes_only_confirmed_owners(self):
        self.person(github=dict(login='ivan-p', id=101))
        self.s.set_project_repositories(self.project, ['org/deploy'])
        resource = dict(kind='item', id=self.task['id'])
        draft = self.s.github_draft(dict(resource=resource, format='issue'))
        self.assertEqual((draft['title'], draft['repository'], draft['assignee']), ('Обнови Kubernetes клъстера', 'org/deploy', None))
        self.assertIn('> Ще обновя Kubernetes клъстера до петък.', draft['body'])
        self.assertIn('Platform sync, 27 October 2026 · 00:00:12', draft['body'])
        self.assertIn('<!-- atlanta:resource=item:' + self.task['id'] + ' -->', draft['body'])
        self.assertNotIn('— Иван', draft['body'])
        self.assertNotIn('ivan@example.invalid', draft['body'])
        self.assertIn('The AI-suggested owner is not included; confirm the owner in Atlanta first.', draft['notes'])
        self.s.update_item(self.task['id'], self.task['text'], {'owner': 'Иван', 'due_date': '2026-10-30'})
        draft = self.s.github_draft(dict(resource=resource, format='comment', include_speaker=True, include_meeting=False))
        self.assertEqual(draft['assignee'], '@ivan-p')
        self.assertIn('Owner: @ivan-p · Due: 2026-10-30', draft['body'])
        self.assertIn('> — Иван', draft['body'])
        self.assertNotIn('Platform sync', draft['body'])
        self.assertTrue(draft['body'].startswith('**Task · A meeting on 27 October 2026 · 00:00:12**'))

    def test_references_parse_from_numbers_names_and_urls(self):
        self.assertEqual(parse('#12', 'org/deploy'), ('org/deploy', 12))
        self.assertEqual(parse('org/infra#7'), ('org/infra', 7))
        self.assertEqual(parse('https://github.com/org/deploy/pull/431/files'), ('org/deploy', 431))
        for bad in ('12', '#0', 'https://example.com/org/deploy/issues/1', 'org/deploy#x'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(bad, 'org/deploy')
        with self.assertRaisesRegex(ValueError, 'Choose the repository'):
            parse('#12')

    def test_link_existing_is_local_two_way_and_joins_the_project_trace(self):
        resource = dict(kind='item', id=self.task['id'])
        cached = dict(kind='pull_request', title='Upgrade the cluster', state='open', issue_id=900)
        with patch.object(self.s.github, 'find', return_value=cached):
            result = self.s.github_link(dict(resource=resource, reference='https://github.com/org/deploy/pull/431'))
        link = result['link']
        self.assertEqual((link['repository'], link['number'], link['kind'], link['verified']), ('org/deploy', 431, 'pull_request', True))
        back = self.s.github_links_for(repository='ORG/deploy', number='431')
        self.assertEqual((back[0]['resource_text'], back[0]['resource_kind']), ('Обнови Kubernetes клъстера', 'task'))
        timeline = self.s.project_workspace(self.project)['timeline']
        chain = next(c for c in timeline['chains'] if c['stages']['task'])
        self.assertEqual([n['ref']['url'] for n in chain['stages']['github']], ['https://github.com/org/deploy/pull/431'])
        self.assertIn('https://github.com/org/deploy/pull/431', [e.get('url') for e in timeline['events']])
        with self.assertRaises(WorkItemConflict):
            self.s.github_unlink(dict(id=link['id'], revision=99))
        self.s.github_unlink(dict(id=link['id'], revision=link['revision']))
        self.assertEqual(self.s.github_links_for('item', self.task['id']), [])

    def test_unverified_link_is_kept_when_github_is_offline(self):
        result = self.s.github_link(dict(resource=dict(kind='item', id=self.task['id']), reference='#5', repository='org/deploy'))
        self.assertEqual((result['link']['verified'], result['link']['kind'], result['link']['url']), (False, 'unknown', 'https://github.com/org/deploy/issues/5'))

    def test_people_links_and_project_repositories_survive_archive_and_restore(self):
        ivan = self.person()
        self.s.set_project_repositories(self.project, ['org/deploy'])
        link = self.s.github_link(dict(resource=dict(kind='item', id=self.task['id']), reference='org/deploy#5'))['link']
        name = self.s.create_backup()['created']['name']
        target = MeetingService(self.root / 'target', PROJECT, google=FakeGoogle(), backup_dir=self.s.backup_dir)
        self.addCleanup(target.close)
        target.restore_backup(name)
        self.assertEqual(target.people.list()[0]['id'], ivan['id'])
        self.assertEqual(target.github_links_for('item', self.task['id'])[0]['id'], link['id'])
        self.assertEqual(target.projects.get('projects', self.project)['repositories'], ['org/deploy'])

    def test_github_user_lookup_reads_only_a_username_path(self):
        with patch.object(self.s.github.connection, 'request', return_value=dict(data=dict(login='Ivan-P', id=101))) as request, \
                patch.object(self.s.github.connection, '_load', return_value=dict(token='github_pat_x', id=1)):
            self.assertEqual(self.s.github_user('@ivan-p'), dict(login='Ivan-P', id=101))
        self.assertEqual(request.call_args.args[0], '/users/ivan-p')
        with self.assertRaises(ValueError):
            self.s.github.connection.get('/users/../repos')
