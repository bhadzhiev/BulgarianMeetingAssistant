import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.github_source import GitHubError
from app.service import MeetingService
from app.team_facts import _time
from app.team_github import Reader, collect, discover, is_noise, records, replace_section, section
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
START, END = _time('2026-11-01T00:00:00+02:00'), _time('2026-11-08T00:00:00+02:00')
API = 'https://api.github.com/repos/'


def pull(repo, number, title, author, merged_by=None, merged_at=None, created='2026-11-03T10:00:00Z', head='feature/x', base='main', sha=None):
    return dict(html_url=f'https://github.com/{repo}/pull/{number}', title=title, user=dict(login=author), merged_by=dict(login=merged_by) if merged_by else None,
                merged_at=merged_at, created_at=created, closed_at=merged_at, updated_at=created, state='closed' if merged_at else 'open',
                head=dict(ref=head, sha=sha or f'{number:040x}'), base=dict(ref=base), merge_commit_sha=None)


class FakeGitHub:
    """Search answers and pull requests of two repositories; one repository is denied."""

    def __init__(self, fail_after=None):
        self.calls, self.fail_after = [], fail_after
        search = lambda *rows: dict(data=dict(items=list(rows), incomplete_results=False), has_next=False)
        issue = lambda repo, n: dict(repository_url=API + repo, number=n, title='t', html_url=f'https://github.com/{repo}/pull/{n}')
        self.answers = {
            ('/search/issues', 'author'): search(issue('acme/app', 1), issue('acme/app', 2), issue('acme/app', 3), issue('acme/secret', 9), issue('acme/lib', 5)),
            ('/search/issues', 'reviewed-by'): search(issue('acme/app', 4)),
            ('/search/commits', ''): search(dict(repository=dict(full_name='acme/app'), sha='a' * 40, html_url='https://github.com/acme/app/commit/' + 'a' * 40, commit=dict(message='Fix login', author=dict(date='2026-11-04T09:00:00Z'))),
                                            dict(repository=dict(full_name='acme/app'), sha=f'{1:040x}', html_url='https://github.com/acme/app/commit/' + f'{1:040x}', commit=dict(message='Part of PR 1', author=dict(date='2026-11-03T09:00:00Z')))),
            '/repos/acme/app/pulls/1': dict(data=pull('acme/app', 1, 'Add VPN check', 'maria', merged_by='ivan', merged_at='2026-11-05T10:00:00Z'), has_next=False),
            '/repos/acme/app/pulls/2': dict(data=pull('acme/app', 2, 'Release 2.4', 'maria', head='release/2.4'), has_next=False),
            '/repos/acme/app/pulls/3': dict(data=pull('acme/app', 3, 'Hotfix: release login', 'maria', head='hotfix/login'), has_next=False),
            '/repos/acme/app/pulls/4': dict(data=pull('acme/app', 4, 'Ivan feature', 'ivan', merged_by='maria', merged_at='2026-11-06T10:00:00Z'), has_next=False),
            '/repos/acme/app/pulls/4/reviews': dict(data=[dict(user=dict(login='maria'), state='APPROVED', submitted_at='2026-11-05T12:00:00Z', html_url='https://github.com/acme/app/pull/4#r1'),
                                                          dict(user=dict(login='maria'), state='COMMENTED', submitted_at='2026-10-20T12:00:00Z', html_url='https://github.com/acme/app/pull/4#r0')], has_next=False),
            '/repos/acme/lib/pulls/5': dict(data=pull('acme/lib', 5, 'Lib change', 'maria'), has_next=False),
            '/repos/acme/app/commits/' + 'a' * 40 + '/pulls': dict(data=[], has_next=False),
        }

    def get(self, resource, query=None):
        self.calls.append(resource)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            error = GitHubError('GitHub request failed (HTTP 403).'); error.status = 403; error.rate_limited = True; raise error
        if resource == '/repos/acme/secret/pulls/9':
            error = GitHubError('GitHub request failed (HTTP 404).'); error.status = 404; raise error
        if resource.startswith('/search/'):
            q = query['q']
            key = (resource, 'reviewed-by' if 'reviewed-by:' in q else 'author' if resource == '/search/issues' else '')
            return self.answers[key]
        return self.answers[resource]


class TeamGitHubTests(unittest.TestCase):
    def run_collect(self, fake, cache=None, include=('acme/app', 'acme/secret')):
        reader = Reader(fake, {} if cache is None else cache, lambda data: None)
        return collect(reader, 'maria', START, END, set(include), lambda repo, n: n == 3)

    def test_discover_lists_repositories_with_counts(self):
        found = discover(Reader(FakeGitHub(), {}, lambda d: None), 'maria', START, END)
        self.assertEqual([(r['name'], r['authored'], r['reviewed']) for r in found['repositories']],
                         [('acme/app', 3, 1), ('acme/lib', 1, 0), ('acme/secret', 1, 0)])

    def test_author_reviewer_merger_noise_hotfix_and_commits(self):
        result = self.run_collect(FakeGitHub())
        titles = {p['title']: p for p in result['authored']}
        self.assertEqual(sorted(titles), ['acme/app #1: Add VPN check', 'acme/app #3: Hotfix: release login'])
        self.assertEqual([e for e, _ in titles['acme/app #1: Add VPN check']['events']], ['opened', 'merged'])
        self.assertEqual(titles['acme/app #1: Add VPN check']['commits'], 1)  # the commit joins its pull request
        self.assertTrue(titles['acme/app #3: Hotfix: release login']['hotfix'])
        self.assertEqual(result['noise'], 1)
        self.assertEqual(result['merged_for_others'], 1)  # merging #4 is not authorship
        self.assertEqual([(r['title'], r['state']) for r in result['reviews']], [('acme/app #4: Ivan feature', 'approved')])
        self.assertEqual([c['title'] for c in result['commits']], ['acme/app aaaaaaaa: Fix login'])
        self.assertIn('GitHub denied access to acme/secret. Its contribution is not in this review.', result['limitations'])
        self.assertNotIn('acme/lib #5: Lib change', titles)  # a repository that the person excluded

    def test_records_and_section(self):
        result = self.run_collect(FakeGitHub())
        rows = records(result, 'a1b2c3d4e5f6', 7)
        self.assertEqual([r['id'] for r in rows][:2], ['e7', 'e8'])
        self.assertEqual({r['source_ref']['provider'] for r in rows}, {'github'})
        text = section(result)
        self.assertIn('GitHub contribution is not added to the task counts.', text)
        self.assertIn('Release and back-merge pull requests: 1 (not listed)', text)
        self.assertIn('unlinked work', text.split('#1: Add VPN check')[1].splitlines()[0])
        self.assertNotIn('unlinked work', text.split('#3: Hotfix')[1].splitlines()[0])
        review = '# R\n\n## Tasks\n\nx\n\n## GitHub contribution\n\n_Not collected yet._\n\n## Questions for the conversation\n\n- q\n'
        replaced = replace_section(review, text)
        self.assertIn('## Questions for the conversation', replaced); self.assertNotIn('_Not collected yet._', replaced)
        self.assertEqual(replace_section(replaced, text), replaced)

    def test_rate_limit_keeps_the_read_parts(self):
        cache, first = {}, FakeGitHub(fail_after=4)
        with self.assertRaises(GitHubError): self.run_collect(first, cache)
        self.assertTrue(cache)
        second = FakeGitHub()
        self.run_collect(second, cache)
        # The second run asks GitHub only what the first run did not get.
        self.assertEqual(len(second.calls), len(self.calls_of_full_run()) - 4)

    def calls_of_full_run(self):
        fake = FakeGitHub(); self.run_collect(fake); return fake.calls

    def test_noise_rules(self):
        self.assertTrue(is_noise(dict(title='Back-merge main into develop', head=dict(ref='main'), base=dict(ref='develop'))))
        self.assertFalse(is_noise(dict(title='Hotfix release crash', head=dict(ref='hotfix/crash'), base=dict(ref='main'))))
        self.assertFalse(is_noise(dict(title='Add search', head=dict(ref='feature/search'), base=dict(ref='main'))))


class ApplyGitHubTests(unittest.TestCase):
    def test_new_records_follow_the_others_and_the_ai_part_goes(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        s = MeetingService(Path(tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(tmp.name) / 'backups'); self.addCleanup(s.close)
        person = s.save_person(dict(name='Maria', github=dict(login='maria')))['person']
        review = s.team_review_action('create', dict(person_id=person['id'], start='2026-11-01T00:00', end='2026-11-08T00:00'))
        folder = s.team_reviews.directory(review['id'])
        (folder / 'evidence.json').write_text(json.dumps([dict(id='e1', kind='task_open', source_ref=dict(provider='meeting'), facts={})]))
        (folder / 'review.md').write_text(review['review_md'].replace('## Questions for the conversation', '## AI observations\n\n- old [e1]\n\n## Questions for the conversation'))
        result = collect(Reader(FakeGitHub(), {}, lambda d: None), 'maria', START, END, {'acme/app'}, lambda r, n: False)
        for _ in range(2):
            review = s.team_reviews.get(review['id'])
            review = s.team_reviews.apply_github(review['id'], review['revision'], result, records, section, replace_section)
        ids = [r['id'] for r in review['evidence']]
        self.assertEqual(ids[0], 'e1'); self.assertEqual(ids[1], 'e2'); self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn('## AI observations', review['review_md'])
        self.assertEqual(review['review_md'].count('## GitHub contribution'), 1)
        self.assertIn('github', review['coverage']['sources'])


if __name__ == '__main__':
    unittest.main()
