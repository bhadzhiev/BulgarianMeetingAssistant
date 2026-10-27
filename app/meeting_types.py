"""Meeting types: the purpose of a meeting changes its preparation, its notes and its review.

Every type keeps the common notes (summary, decisions, tasks, questions). A type only adds a few short
sections, because each extra section makes the local model write a longer answer. A series has a default
type; a new meeting of the series starts with it, and a person can change it for one meeting.

A person can also make an own template: up to three sections, each with a title and an instruction, and
the agenda style of a built-in type. A meeting keeps a copy of its template, so later edits of the
template never change the notes of a saved meeting.
"""
from __future__ import annotations

import re
import uuid

DEFAULT = 'general'
CUSTOM_SECTIONS = ('custom_1', 'custom_2', 'custom_3')
CUSTOM_ID = re.compile(r'custom-[a-f0-9]{8}')
MAX_TEMPLATES = 30


def _section(key, title, title_bg, instruction, attention=None):
    """attention: the review question for "Needs attention" in the singular and plural, or None."""
    return dict(key=key, title=title, title_bg=title_bg, instruction=instruction, attention=attention)


TYPES = {
    'general': dict(
        label='General',
        description='Summary, decisions, tasks and open questions.',
        task_title='Tasks', export='Meeting summary',
        sections=[],
        prompt=''),
    'daily': dict(
        label='Daily stand-up',
        description='Plans for today, blockers and what needs coordination. Prepare me shows the blockers of the last daily and stalled tasks.',
        task_title='Tasks', export='Daily update',
        sections=[
            _section('today', 'Plans for today', 'Днес',
                     'какво всеки участник ще прави днес. Започни текста с името му, ако е известно. Не повтаряй задачите.'),
            _section('blockers', 'Blockers', 'Блокери',
                     'какво пречи на някого да продължи: кой е блокиран и от какво. Само изрично казани пречки.',
                     ('Check {n} blocker and agree who helps', 'Check {n} blockers and agree who helps')),
            _section('coordination', 'Needs coordination', 'Нужна координация',
                     'теми, по които двама или повече души трябва да се разберат след срещата.'),
        ],
        prompt='Това е кратка ежедневна среща (daily stand-up). Пиши кратко: едно изречение на елемент.'),
    'sprint_review': dict(
        label='Sprint review',
        description='What was delivered, what is not finished and the feedback. Prepare me shows the tasks done since the last review.',
        task_title='Tasks', export='Sprint review summary',
        sections=[
            _section('delivered', 'Delivered', 'Завършено',
                     'какво е завършено или показано в спринта. Посочи кой го е направил, ако е казано.'),
            _section('carry_over', 'Not finished', 'Незавършено',
                     'какво не е завършено и защо, както е казано.',
                     ('Agree what happens with {n} unfinished item', 'Agree what happens with {n} unfinished items')),
            _section('feedback', 'Feedback', 'Обратна връзка',
                     'обратна връзка и нови искания от участниците или от клиента.'),
        ],
        prompt='Това е преглед на спринт (sprint review). Разграничавай завършено от незавършено.'),
    'planning': dict(
        label='Planning',
        description='Goals, risks and what is out of scope. Prepare me shows the tasks without an owner or a date.',
        task_title='Planned tasks', export='Plan',
        sections=[
            _section('goals', 'Goals', 'Цели', 'целите за периода, които участниците приеха.'),
            _section('risks', 'Risks', 'Рискове', 'рискове за плана, както са казани. Не измисляй рискове.',
                     ('Check {n} risk and agree who watches it', 'Check {n} risks and agree who watches them')),
            _section('out_of_scope', 'Out of scope', 'Извън обхвата', 'какво изрично няма да се прави в този период.'),
        ],
        prompt='Това е среща за планиране. В tasks запиши само работа, която е изрично планирана.'),
    'cross_team': dict(
        label='Cross-team',
        description='Dependencies, handoffs and escalations between teams. Prepare me starts with the open dependencies.',
        task_title='Tasks', export='Cross-team summary',
        sections=[
            _section('dependencies', 'Dependencies', 'Зависимости',
                     'кой екип или човек чака друг и за какво. Посочи двете страни.',
                     ('Check {n} dependency and its owner', 'Check {n} dependencies and their owners')),
            _section('handoffs', 'Handoffs', 'Предаване на работа', 'какво се предава от един екип на друг и кога.'),
            _section('escalations', 'Escalations', 'Ескалации', 'въпроси, които участниците не можаха да решат и изпращат нагоре.'),
        ],
        prompt='Това е среща между екипи. Посочвай кой екип или човек е отговорен за всяко нещо.'),
    'client': dict(
        label='Client meeting',
        description='Client requests, our commitments and concerns. The client summary leaves out private and internal notes.',
        task_title='Tasks', export='Client summary',
        sections=[
            _section('client_requests', 'Client requests', 'Искания на клиента', 'какво клиентът поиска, с неговите думи, кратко.'),
            _section('commitments', 'Our commitments', 'Наши ангажименти',
                     'какво нашият екип обеща на клиента, със срока, ако е казан.',
                     ('Check {n} commitment before you share it', 'Check {n} commitments before you share them')),
            _section('client_concerns', 'Client concerns', 'Притеснения на клиента', 'притеснения или недоволство, които клиентът изрази.'),
        ],
        prompt='Това е среща с клиент. Пиши ясно и неутрално, защото част от текста може да се сподели с клиента.'),
    'incident': dict(
        label='Incident / postmortem',
        description='Facts, a timeline, hypotheses and corrective actions. A hypothesis is never written as a fact.',
        task_title='Corrective actions', export='Postmortem',
        sections=[
            _section('facts', 'Facts', 'Факти',
                     'потвърдени факти за инцидента: какво се случи, кои системи и потребители са засегнати, какво е въздействието. '
                     'Само казаното като сигурно.',
                     ('Check {n} fact against the recording', 'Check {n} facts against the recording')),
            _section('incident_timeline', 'Timeline', 'Хронология',
                     'събитията на инцидента по ред, с часа, ако е казан (например „14:05 — deploy на версия 2.3“). Не измисляй часове.'),
            _section('hypotheses', 'Hypotheses', 'Хипотези',
                     'непотвърдени предположения за причината. Пиши ги като хипотези, не като факти.',
                     ('Confirm or reject {n} hypothesis', 'Confirm or reject {n} hypotheses')),
        ],
        prompt='Това е среща за инцидент или postmortem. Разграничавай строго факт от хипотеза. '
               'В tasks запиши коригиращите действия и проверките, които потвърждават или отхвърлят хипотеза.'),
}
SECTION_FIELDS = tuple(s['key'] for kind in TYPES.values() for s in kind['sections']) + CUSTOM_SECTIONS
TITLES_BG = {s['key']: s['title_bg'] for kind in TYPES.values() for s in kind['sections']}


def _text(value, field, limit):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f'{field} must be one line of 1 to {limit} characters')
    return ' '.join(value.split())


def check_template(value) -> dict:
    """A valid own template. The ID is new unless an existing one is given."""
    if not isinstance(value, dict):
        raise ValueError('Invalid template')
    template_id = value.get('id') or 'custom-' + uuid.uuid4().hex[:8]
    if not isinstance(template_id, str) or not CUSTOM_ID.fullmatch(template_id):
        raise ValueError('Invalid template ID')
    label = _text(value.get('label'), 'Name', 60)
    if label.casefold() in {kind['label'].casefold() for kind in TYPES.values()}:
        raise ValueError('A built-in type already has this name')
    description = value.get('description') or ''
    description = _text(description, 'Description', 300) if description.strip() else ''
    prepare = value.get('prepare') or DEFAULT
    if prepare not in TYPES:
        raise ValueError('Choose the agenda of a built-in type')
    sections = value.get('sections')
    if not isinstance(sections, list) or not 1 <= len(sections) <= len(CUSTOM_SECTIONS):
        raise ValueError(f'A template has 1 to {len(CUSTOM_SECTIONS)} sections')
    checked = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('Invalid section')
        checked.append(dict(title=_text(section.get('title'), 'Section title', 60),
                            instruction=_text(section.get('instruction'), 'Instruction', 300),
                            review=section.get('review') is True))
    if len({s['title'].casefold() for s in checked}) < len(checked):
        raise ValueError('Each section needs its own title')
    return dict(id=template_id, label=label, description=description, prepare=prepare, sections=checked,
                revision=value.get('revision'))


def definition(kind, template=None) -> dict:
    """Everything that a type changes. An own type comes from its template, or from the copy in a meeting."""
    if kind in TYPES:
        value = TYPES[kind]
        return dict(id=kind, label=value['label'], description=value['description'], task_title=value['task_title'],
                    export=value['export'], style=kind, prompt=value['prompt'], custom=False, sections=value['sections'])
    if isinstance(kind, str) and CUSTOM_ID.fullmatch(kind) and isinstance(template, dict):
        sections = [_section(key, s['title'], s['title'], s['instruction'],
                             (f'Check {{n}} item in {s["title"]}', f'Check {{n}} items in {s["title"]}') if s.get('review') else None)
                    for key, s in zip(CUSTOM_SECTIONS, template.get('sections', []))]
        return dict(id=kind, label=template['label'], description=template.get('description') or 'Your own template.',
                    task_title='Tasks', export=template['label'] + ' summary', style=template.get('prepare', DEFAULT),
                    prompt=f'Това е среща от вида „{template["label"]}“.', custom=True, sections=sections)
    return definition(DEFAULT)


def of(meeting) -> dict:
    """The type of a saved meeting. Meetings from before types existed are general."""
    meeting = meeting or {}
    return definition(meeting.get('meeting_type'), meeting.get('meeting_template'))


def sections(kind) -> tuple:
    return tuple(s['key'] for s in (kind if isinstance(kind, dict) else definition(kind))['sections'])


def prompt(kind) -> str:
    """Extra instructions for the notes model. Empty for the general type, so its prompt stays as before."""
    value = kind if isinstance(kind, dict) else definition(kind)
    if not value['sections']:
        return ''
    keys = [s['key'] for s in value['sections']]
    lines = [value['prompt']] + [f'{s["key"]}: {s["instruction"]}' for s in value['sections']]
    lines.append('Всеки елемент в ' + ', '.join(keys) + ' е обект с text и evidence_timestamp, както summary.')
    return '\n'.join(lines)


def titles_bg(meeting) -> dict:
    """Section titles for the Markdown export of one meeting."""
    return {s['key']: s['title_bg'] for s in of(meeting)['sections']} | {k: v for k, v in TITLES_BG.items()}


def public(templates=()) -> list[dict]:
    """The types for the app: the built-in ones in a fixed order, then the own templates."""
    result = []
    for value in [definition(key) for key in TYPES] + [dict(definition(t['id'], t), template=t) for t in templates]:
        result.append(dict({k: v for k, v in value.items() if k not in ('prompt',)},
                           sections=[dict(key=s['key'], title=s['title'], attention=s['attention']) for s in value['sections']]))
    return result
