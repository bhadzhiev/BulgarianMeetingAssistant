"""One list of the background jobs: the single source for their status in the app.

Each job family keeps its own job record (the 1:1 AI run, the GitHub collection, the prompt test,
email AI, repository reports, meeting processing). This registry reads them and gives one
lifecycle to all: queued, running, completed, failed or cancelled. A failed job stays in the list
until the person dismisses it; a completed or cancelled job stays for a short time.
"""
import threading
import time

KEEP_ENDED = 10 * 60  # seconds that a completed or cancelled job stays in the list


def _state(job):
    """The lifecycle state of one job record of a family."""
    status = str(job.get('status') or '')
    if job.get('running'):
        return 'queued' if status.lower() == 'queued' else 'running'
    if job.get('error'):
        return 'failed'
    if status.lower().startswith('cancel'):
        return 'cancelled'
    if not status or status.lower() == 'idle':
        return None
    return 'completed'


class Jobs:
    def __init__(self, service, clock=time.time):
        self.service, self.clock = service, clock
        self.lock = threading.Lock()
        self.ended = {}       # job id -> the first time the registry saw it end
        self.dismissed = set()

    def _families(self):
        s = self.service
        review_name = {}

        def person(review_id):
            if review_id not in review_name:
                try:
                    review_name[review_id] = s.team_reviews.get(review_id).get('person_name') or ''
                except Exception:
                    review_name[review_id] = ''
            return review_name[review_id]

        rows = []

        def add(family, job, label, target, key=None):
            state = _state(job)
            if not state:
                return
            ident = key or job.get('id') or job.get('job_id') or job.get('report_id') or job.get('started_at') or 'current'
            progress = dict(done=job['done'], total=job['total']) if job.get('total') else None
            rows.append(dict(id=f'{family}:{ident}', family=family, label=label, target=target, state=state,
                             phase=str(job.get('status') or ''), error=job.get('error') or None, progress=progress,
                             started_at=job.get('started_at')))

        for family, owner, label in (('team_ai', getattr(s, 'team_ai', None), 'Preparing the 1:1 with AI'),
                                     ('team_github', getattr(s, 'team_github', None), 'Collecting GitHub for the 1:1')):
            job = dict(getattr(owner, 'job', None) or {}) if owner else {}
            if job.get('id'):
                name = person(job.get('review_id'))
                add(family, job, label + (' · ' + name if name else ''), dict(view='team', id=job.get('review_id')))
        lab = getattr(s, 'prompt_lab', None)
        if lab and lab.job.get('id'):
            add('prompt_test', dict(lab.job), 'Testing AI instructions', dict(view='settings', id='prompts'))
        mail = getattr(s, 'gmail_ai', None)
        if mail:
            job = dict(mail.job)
            add('gmail_ai', job, 'Email AI' + (' · ' + job['model'] if job.get('model') else ''), dict(view='work', id='gmail'))
        reports = getattr(s, 'repo_reports', None)
        if reports:
            add('repo_report', dict(reports.job), 'Repository report', dict(view='work', id='github-reports'))
        # Meeting processing and AI titles: running jobs only. Their results and errors show on the meeting.
        for meeting in s.library.list():
            title = meeting.get('title') or 'Untitled meeting'
            if meeting.get('status') == 'processing':
                rows.append(dict(id='meeting:' + meeting['id'], family='meeting', label='Processing · ' + title,
                                 target=dict(view='meeting', id=meeting['id']), state='running',
                                 phase=meeting.get('progress') or 'Processing', error=None, progress=None, started_at=None))
            if meeting.get('title_status') == 'generating':
                rows.append(dict(id='title:' + meeting['id'], family='title', label='Generating AI title · ' + title,
                                 target=dict(view='meeting', id=meeting['id']), state='running',
                                 phase='Generating AI title', error=None, progress=None, started_at=None))
        return rows

    def listing(self):
        rows, now = self._families(), self.clock()
        with self.lock:
            current = {row['id'] for row in rows}
            self.ended = {key: at for key, at in self.ended.items() if key in current}
            self.dismissed &= current
            shown = []
            for row in rows:
                if row['id'] in self.dismissed:
                    continue
                if row['state'] in ('completed', 'cancelled', 'failed'):
                    row['ended_at'] = self.ended.setdefault(row['id'], now)
                    # A failure stays until it is dismissed; a success goes after a short time.
                    if row['state'] != 'failed' and now - row['ended_at'] > KEEP_ENDED:
                        continue
                shown.append(row)
        order = dict(failed=0, running=1, queued=2, cancelled=3, completed=4)
        shown.sort(key=lambda row: order[row['state']])
        summary = dict(running=sum(r['state'] == 'running' for r in shown), queued=sum(r['state'] == 'queued' for r in shown),
                       failed=sum(r['state'] == 'failed' for r in shown), completed=sum(r['state'] == 'completed' for r in shown),
                       cancelled=sum(r['state'] == 'cancelled' for r in shown))
        return dict(jobs=shown, summary=summary)

    def dismiss(self, job_id):
        """Hide an ended job. A running job cannot be dismissed: stop it first."""
        rows = {row['id']: row for row in self._families()}
        row = rows.get(str(job_id or ''))
        if not row:
            raise ValueError('This job is no longer in the list')
        if row['state'] in ('running', 'queued'):
            raise ValueError('A running job cannot be dismissed. Stop it first.')
        with self.lock:
            self.dismissed.add(row['id'])
        return self.listing()
