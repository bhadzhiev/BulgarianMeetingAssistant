"""Meeting types: the purpose of a meeting changes its preparation, its notes and its review.

Every type keeps the common notes (summary, decisions, tasks, questions). A type only adds a few short
sections, because each extra section makes the local model write a longer answer. A series has a default
type; a new meeting of the series starts with it, and a person can change it for one meeting.
"""
from __future__ import annotations

DEFAULT = 'general'

# key: (English title for the app, Bulgarian title for the Markdown export, instruction for the model,
#       review question for "Needs attention" in the singular and plural, or None)
TYPES = {
    'general': dict(
        label='General',
        description='Summary, decisions, tasks and open questions.',
        task_title='Tasks',
        sections={},
        prompt=''),
    'daily': dict(
        label='Daily stand-up',
        description='Plans for today, blockers and what needs coordination. Prepare me shows the blockers of the last daily and stalled tasks.',
        task_title='Tasks',
        sections={
            'today': ('Plans for today', 'Днес',
                      'какво всеки участник ще прави днес. Започни текста с името му, ако е известно. Не повтаряй задачите.',
                      None),
            'blockers': ('Blockers', 'Блокери',
                         'какво пречи на някого да продължи: кой е блокиран и от какво. Само изрично казани пречки.',
                         ('Check {n} blocker and agree who helps', 'Check {n} blockers and agree who helps')),
            'coordination': ('Needs coordination', 'Нужна координация',
                             'теми, по които двама или повече души трябва да се разберат след срещата.',
                             None),
        },
        prompt='Това е кратка ежедневна среща (daily stand-up). Пиши кратко: едно изречение на елемент.'),
    'incident': dict(
        label='Incident / postmortem',
        description='Facts, a timeline, hypotheses and corrective actions. A hypothesis is never written as a fact.',
        task_title='Corrective actions',
        sections={
            'facts': ('Facts', 'Факти',
                      'потвърдени факти за инцидента: какво се случи, кои системи и потребители са засегнати, какво е въздействието. '
                      'Само казаното като сигурно.',
                      ('Check {n} fact against the recording', 'Check {n} facts against the recording')),
            'incident_timeline': ('Timeline', 'Хронология',
                                  'събитията на инцидента по ред, с часа, ако е казан (например „14:05 — deploy на версия 2.3“). '
                                  'Не измисляй часове.',
                                  None),
            'hypotheses': ('Hypotheses', 'Хипотези',
                           'непотвърдени предположения за причината. Пиши ги като хипотези, не като факти.',
                           ('Confirm or reject {n} hypothesis', 'Confirm or reject {n} hypotheses')),
        },
        prompt='Това е среща за инцидент или postmortem. Разграничавай строго факт от хипотеза. '
               'В tasks запиши коригиращите действия и проверките, които потвърждават или отхвърлят хипотеза.'),
}
SECTION_FIELDS = tuple(key for kind in TYPES.values() for key in kind['sections'])
TITLES_BG = {key: section[1] for kind in TYPES.values() for key, section in kind['sections'].items()}


def check(value) -> str:
    if value not in TYPES:
        raise ValueError('Choose a meeting type')
    return value


def of(meeting) -> str:
    """The type of a saved meeting. Meetings from before types existed are general."""
    value = (meeting or {}).get('meeting_type')
    return value if value in TYPES else DEFAULT


def sections(kind) -> tuple:
    return tuple(TYPES.get(kind, TYPES[DEFAULT])['sections'])


def prompt(kind) -> str:
    """Extra instructions for the notes model. Empty for the general type, so its prompt stays as before."""
    definition = TYPES.get(kind, TYPES[DEFAULT])
    if not definition['sections']:
        return ''
    lines = [definition['prompt']] + [f'{key}: {section[2]}' for key, section in definition['sections'].items()]
    lines.append('Всеки елемент в ' + ', '.join(definition['sections']) + ' е обект с text и evidence_timestamp, както summary.')
    return '\n'.join(lines)


def public() -> list[dict]:
    """The types for the app, in a fixed order."""
    return [dict(id=key, label=value['label'], description=value['description'], task_title=value['task_title'],
                 sections=[dict(key=name, title=section[0], attention=section[3]) for name, section in value['sections'].items()])
            for key, value in TYPES.items()]
