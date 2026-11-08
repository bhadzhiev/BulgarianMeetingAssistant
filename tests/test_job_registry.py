import unittest
from types import SimpleNamespace

from app.job_registry import Jobs, KEEP_ENDED


class Store:
    def __init__(self, job=None):
        self.job = job or {}


class Reviews:
    def get(self, review_id):
        return dict(person_name='Person A')


def service(**stores):
    meetings = stores.pop('meetings', [])
    base = dict(team_ai=Store(), team_github=Store(), prompt_lab=Store(), gmail_ai=Store(dict(running=False, status='idle', error=None)),
                repo_reports=Store(dict(running=False, status='idle', error=None)), team_reviews=Reviews(),
                library=SimpleNamespace(list=lambda: meetings))
    base.update(stores)
    return SimpleNamespace(**base)


class JobRegistryTest(unittest.TestCase):
    def test_one_lifecycle_for_every_family(self):
        s = service(team_ai=Store(dict(id='a1', review_id='r1', running=True, status='Preparing part 1 of 2', done=0, total=2)),
                    prompt_lab=Store(dict(id='p1', running=False, status='Failed', error='Server said no')),
                    gmail_ai=Store(dict(running=True, status='queued', error=None, model='m')),
                    meetings=[dict(id='m1', title='Weekly', status='processing', progress='Notes'),
                              dict(id='m2', title='Other', status='ready', title_status='generating'),
                              dict(id='m3', title='Done', status='ready')])
        data = Jobs(s).listing()
        states = {row['id']: row['state'] for row in data['jobs']}
        self.assertEqual(states, {'team_ai:a1': 'running', 'prompt_test:p1': 'failed', 'gmail_ai:current': 'queued',
                                  'meeting:m1': 'running', 'title:m2': 'running'})
        # A failure comes first, so a success never hides it.
        self.assertEqual(data['jobs'][0]['state'], 'failed')
        self.assertEqual(data['summary'], dict(running=3, queued=1, failed=1, completed=0, cancelled=0))
        team = next(row for row in data['jobs'] if row['family'] == 'team_ai')
        self.assertEqual(team['label'], 'Preparing the 1:1 with AI · Person A')
        self.assertEqual(team['progress'], dict(done=0, total=2))
        self.assertEqual(team['target'], dict(view='team', id='r1'))

    def test_failure_stays_until_dismissed_and_success_goes_after_a_while(self):
        now = [1000.0]
        s = service(prompt_lab=Store(dict(id='p1', running=False, status='Failed', error='boom')),
                    repo_reports=Store(dict(running=False, status='Report saved', error=None, report_id='x')))
        jobs = Jobs(s, clock=lambda: now[0])
        self.assertEqual({r['id'] for r in jobs.listing()['jobs']}, {'prompt_test:p1', 'repo_report:x'})
        now[0] += KEEP_ENDED + 1
        self.assertEqual({r['id'] for r in jobs.listing()['jobs']}, {'prompt_test:p1'})
        self.assertEqual(jobs.dismiss('prompt_test:p1')['jobs'], [])

    def test_a_running_job_cannot_be_dismissed(self):
        jobs = Jobs(service(team_ai=Store(dict(id='a1', review_id='r1', running=True, status='Preparing'))))
        with self.assertRaisesRegex(ValueError, 'Stop it first'):
            jobs.dismiss('team_ai:a1')
        with self.assertRaisesRegex(ValueError, 'no longer in the list'):
            jobs.dismiss('team_ai:gone')

    def test_cancelled_and_idle(self):
        s = service(team_github=Store(dict(id='g1', review_id='r1', running=False, status='Cancelled', error=None)))
        self.assertEqual([r['state'] for r in Jobs(s).listing()['jobs']], ['cancelled'])


if __name__ == '__main__':
    unittest.main()
