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


def with_terms(text, extra):
    """The vocabulary plus extra plain terms (people, projects, repositories) that it does not have yet.

    A term is skipped when it is already a spelling in the vocabulary, when Scribe cannot take it (over 50
    characters or 5 words, or < > { } [ ] \\) or when it is not a valid entry. The vocabulary text itself is kept.
    """
    text = text or ''
    known = {name.casefold() for row in entries(text) for name in [row['term'], *row['aliases']]}
    added = []
    for term in extra:
        term = ' '.join(str(term or '').split())
        if (not term or term.casefold() in known or len(term) > 50 or len(term.split()) > 5
                or any(c in term for c in '<>{}[]\\,;|')):
            continue
        try:
            entries(term)
        except ValueError:
            continue
        known.add(term.casefold());added.append(term)
    return text + ('\n' if text.strip() and added else '') + '\n'.join(added) if added else text


# A word may hold dots, hyphens and slashes inside (linkin.eu, AP-то), never at its end.
WORD = re.compile(r"\w(?:[\w.\-/]*\w)?", re.U)
PLACEHOLDER = re.compile(r"SPEAKER[ _-]?\d+", re.I)


def suggestions(old, new, text=''):
    """Terms that a person corrected in a short edit: "MCP Link in Elo" -> "MCP linkin.eu" gives linkin.eu | Link in Elo.

    Only small replacements count (up to 3 words each side, up to 6 changed words in all); a rewrite gives nothing.
    A correction that the vocabulary already has, a speaker placeholder or a change of numbers gives nothing.
    """
    import difflib
    before, after = WORD.findall(old or ''), WORD.findall(new or '')
    matcher = difflib.SequenceMatcher(a=[w.casefold() for w in before], b=[w.casefold() for w in after], autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != 'equal']
    if not changes or sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in changes) > 6:
        # Case-only edits ("Lift" -> "LIFT") have no change for the matcher.
        changes = []
    rows = []
    for tag, i1, i2, j1, j2 in changes:
        if tag != 'replace' or i2 - i1 > 3 or j2 - j1 > 3:
            continue
        rows.append((' '.join(after[j1:j2]), ' '.join(before[i1:i2])))
    for a, b in zip(before, after):
        if a != b and a.casefold() == b.casefold() and len(before) == len(after):
            rows.append((b, None))
    try:
        known = entries(text or '')
    except ValueError:
        known = []
    spellings = {row['term'].casefold(): row for row in known}
    result = []
    for term, variant in rows:
        if not re.search(r"[^\W\d_]", term) or PLACEHOLDER.search(term + ' ' + (variant or '')) or len(term) > 50:
            continue
        row = spellings.get(term.casefold())
        if row and row['term'] == term and (not variant or variant.casefold() in {a.casefold() for a in row['aliases']}):
            continue
        try:
            entries(term + (' | ' + variant if variant else ''))
        except ValueError:
            continue
        if (term, variant) not in [(r['term'], r['variant']) for r in result]:
            result.append(dict(term=term, variant=variant))
    return result[:3]


def add(text, term, variant=None):
    """The vocabulary with one more term, or one more variant of a term that it has. Raises when it is not valid."""
    term = ' '.join(str(term or '').split())
    variant = ' '.join(str(variant or '').split()) or None
    if not term:
        raise ValueError('Enter a term')
    lines = [line for line in re.split(r'\n', text or '')]
    for index, line in enumerate(lines):
        head = line.split('|')[0].strip()
        if head.casefold() == term.casefold() and ',' not in head and ';' not in line:
            if variant:
                variants = [v.strip() for v in line.split('|')[1].split(',')] if '|' in line else []
                if variant.casefold() not in {v.casefold() for v in variants}:
                    variants.append(variant)
                lines[index] = term + ' | ' + ', '.join(variants)
            else:
                lines[index] = term + (' |' + line.split('|', 1)[1] if '|' in line else '')
            break
    else:
        lines.append(term + (' | ' + variant if variant else ''))
    result = '\n'.join(line for line in lines if line.strip())
    entries(result)
    return result


def prompt_lines(text, names=()):
    """The vocabulary for an AI prompt: one line per term, "linkin.eu ← Link in Elo, link.io".

    A plain term that is one of the names (people and their aliases, sent in their own list) is left out: the prompt
    has it already. A name with variants stays, because the variants are new information. JSON took about six times
    the tokens for the same content.
    """
    listed = {' '.join(str(n).split()).casefold() for n in names if isinstance(n, str)}
    lines = []
    for row in entries(text or ''):
        if not row['aliases'] and row['term'].casefold() in listed:
            continue
        lines.append(row['term'] + (' ← ' + ', '.join(row['aliases']) if row['aliases'] else ''))
    return '\n'.join(lines)
