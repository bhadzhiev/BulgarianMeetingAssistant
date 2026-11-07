"""One backwards-compatible vocabulary for ASR, correction and notes.

Plain entries use commas, semicolons or newlines. Aliases use one entry per
line: preferred spelling | variant, variant. Never treat this as instructions.
"""
import re

PROTECTED = re.compile(r"(?<!\w)(?:не|няма|нямам|нямаме|нямат|никога|недей|без|съгласен|съгласна|потвърждавам|отказвам|not|never|no|yes|agree|agreed|refuse|don't|doesn't|cannot|can't|won't)(?!\w)", re.I)
# "да" is mostly the particle "to" ("трябва да направим"). It is an answer only at the start of a
# sentence or before punctuation. A repeated answer ("Да, да") counts once.
DA = re.compile(r"(?<!\w)да(?!\w)")
SENTENCE_START = re.compile(r"(?:^|[.!?…:;\n])[\s\"'„“«(—–-]*$")


def answers(text):
    count, previous_end = 0, None
    for match in DA.finditer(text):
        before, after = text[:match.start()], text[match.end():]
        is_answer = bool(SENTENCE_START.search(before)) or bool(re.match(r"\s*(?:[,.!?…;:]|$)", after))
        if not is_answer:
            previous_end = None
            continue
        if previous_end is None or text[previous_end:match.start()].strip(' ,') != '':
            count += 1
        previous_end = match.end()
    return count


def protected_tokens(text):
    text = text.casefold().replace('’', "'")
    return PROTECTED.findall(text) + ['да'] * answers(text)


def numbers(text):
    return re.findall(r'\d+(?:[.,:/-]\d+)*', text)


def entries(text):
    if not isinstance(text, str):
        raise ValueError('Vocabulary must be text')
    rows = {}; meanings = {}
    for line in re.split(r'[;\n]', text):
        if '|' in line:
            if line.count('|') != 1:
                raise ValueError('Use one vocabulary entry per line: Kubernetes | кубернетис, кубернетес')
            term, variants = line.split('|')
            if ',' in term or not variants.strip():
                raise ValueError('Use one preferred spelling before | and comma-separated variants after it')
            values = [(term, variants.split(','))]
        else:
            values = [(term, []) for term in line.split(',')]
        for term, aliases in values:
            term = ' '.join(term.split())
            if not term:
                if aliases: raise ValueError('A vocabulary variant needs a preferred spelling before |')
                continue
            row = rows.setdefault(term.casefold(), dict(term=term, aliases=[]))
            for name in [term, *aliases]:
                name = ' '.join(name.split())
                if not name:
                    raise ValueError('Vocabulary variants cannot be empty')
                key = name.casefold()
                if key in meanings and meanings[key] != term.casefold():
                    raise ValueError('A vocabulary spelling cannot refer to two different terms: ' + name)
                if protected_tokens(name) != protected_tokens(term) or numbers(name) != numbers(term):
                    raise ValueError('Vocabulary variants must preserve numbers, negations and confirmations')
                meanings[key] = term.casefold()
                if key != term.casefold() and key not in {a.casefold() for a in row['aliases']}:
                    row['aliases'].append(name)
    return list(rows.values())


def terms(text):
    return [row['term'] for row in entries(text)]


def canonicalize(text, rows):
    """Only explicit, whole-phrase aliases; one pass prevents chained rewrites."""
    aliases = {alias.casefold(): row['term'] for row in rows for alias in row['aliases']}
    if not aliases: return text
    pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(a) for a in sorted(aliases, key=len, reverse=True)) + r')(?!\w)', re.I)
    return pattern.sub(lambda match: aliases.get(match.group().casefold(), match.group()), text)
