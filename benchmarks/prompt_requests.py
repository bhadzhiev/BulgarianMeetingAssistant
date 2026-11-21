"""Compare request structure offline, or run the synthetic excerpts through an explicit API."""
import argparse
import copy
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import meeting_assistant as meeting
from app import local_ai, team_analysis
from app.meeting_automation import TITLE_SYSTEM

# Human reference for commitments, attribution, dates, and the distinction from status.
CASES = (
    ('Ана: Аз ще проверя архива до петък.', 'Един ангажимент на Ана със срок до петък.'),
    ('Ана: Може би ще помоля Борис да провери архива.', 'Няма договорен ангажимент или отговорник.'),
    ('Борис: Пуснах промяната вчера; още не сме проверили резултата.', 'Съобщено изпълнение, липсва проверка.'),
    ('Ана: Първо предложихме DNS промяната днес.\nБорис: Съгласен съм да я направим в петък.', 'Последното изрично съгласие е за петък.'),
    ('Ана: Борис да провери CI. Срок ще уточним утре.', 'Борис отговаря за проверката. Утре е за уточняване, а срокът е неизвестен.'),
    ('Борис: Не сме пускали миграцията.\nАна: Аз ще проверя статуса утре.', 'Отрицанието се пази; Ана проверява утре.'),
    ('Ана: Чакаме достъп от клиента за вече започналата миграция.', 'Блокер по съществуваща работа.'),
    ('Борис: Аз ще проверя dev, а Ана пое проверката на prod.', 'Две отделни задачи за различни среди.'),
    ('Ана: Решихме да оставим staging включен.\nБорис: Аз ще прегледам разходите.', 'Едно решение и отделна задача на Борис.'),
    ('Борис: Проверих с клиента, потвърди че PDF файлът се отваря.', 'Съобщена конкретна проверка и резултат.'),
    ('Ана: Готово е наполовина.\nБорис: С какво мога да помогна?', 'Частичен напредък и предложение за помощ.'),
    ('Борис: Не мога да пусна deploy без достъп.\nАна: Ще поискам достъп днес.', 'Блокер на Борис и ангажимент на Ана днес.'),
    ('Ана: Стойността е 15 ms, не 50 ms.', 'Пази точно числата, единицата и отрицанието.'),
    ('Борис: Архивът е стар.\nАна: Да проверим ли и копието в S3?', 'Факт и въпрос, без поет ангажимент.'),
    ('Ана: Аз ще обновя Terraform модула до края на месеца.\nБорис: Аз ще проверя rollback в dev, без срок.', 'Две задачи; само първата има срок.'),
)


def requests(text):
    segments = [meeting.TranscriptSegment(index * 10, index * 10 + 8, line.split(': ', 1)[1], line.split(': ', 1)[0])
                for index, line in enumerate(text.splitlines())]
    transcript = meeting.transcript_for_llm(segments)
    stamps = [meeting.timestamp(row.start) for row in segments]
    notes = meeting.minutes_messages(transcript, meeting_date='2026-11-19')
    schema = meeting.minutes_schema()
    title = [{'role': 'system', 'content': TITLE_SYSTEM}, {'role': 'user', 'content': 'Meeting transcript:\n' + text}]
    title_schema = dict(type='object', additionalProperties=False, required=['title'], properties=dict(title=dict(type='string')))
    combined = copy.deepcopy(notes)
    combined[0]['content'] += '\n\n' + TITLE_SYSTEM + ' Put the title in the title field of the notes JSON.'
    combined_schema = copy.deepcopy(schema)
    combined_schema['properties']['title'] = title_schema['properties']['title']
    combined_schema['required'].append('title')
    team = 'Мениджър: Ана\nУчастници: Ана, Борис\n\nТРАНСКРИПТ:\n' + transcript
    parts = [(*team_analysis.request_for(team, stamps, 'Ана', keys), 'team_analysis') for keys in team_analysis.PARTS]
    keys = tuple(key for part in team_analysis.PARTS for key in part)
    return {
        'notes_and_title_current': [(notes, schema, 'meeting_minutes'), (title, title_schema, 'meeting_title')],
        'notes_and_title_combined': [(combined, combined_schema, 'meeting_minutes')],
        'team_current': parts,
        'team_combined': [(*team_analysis.request_for(team, stamps, 'Ана', keys), 'team_analysis')],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', help='Run real requests using this explicit OpenAI-compatible URL')
    parser.add_argument('--model')
    parser.add_argument('--case', type=int, choices=range(1, len(CASES) + 1))
    args = parser.parse_args()
    if bool(args.base_url) != bool(args.model):
        parser.error('--base-url and --model must be supplied together')
    settings = dict(local_ai_base_url=args.base_url, local_ai_model=args.model, local_ai_format='json_schema')
    for number, (text, reference) in enumerate(CASES, 1):
        if args.case and number != args.case:
            continue
        report = dict(case=number, excerpt=text, expected=reference, variants={})
        for label, calls in requests(text).items():
            variant = dict(requests=len(calls), message_characters=sum(
                len(message['content']) for messages, schema, stage in calls
                for message in local_ai.request_messages(settings, messages, schema, stage)))
            if args.base_url:
                started = time.monotonic()
                usage = []
                post_json = meeting.post_json

                def measure(*args, **kwargs):
                    response = post_json(*args, **kwargs)
                    usage.append(response.get('usage', {}))
                    return response

                def run(call):
                    messages, schema, stage = call
                    try:
                        return local_ai.complete_json(settings, messages, schema, stage,
                            max_tokens=team_analysis.OUTPUT_LIMIT if stage == 'team_analysis' else 4096,
                            api_key=os.getenv('ATLANTA_BENCHMARK_API_KEY', ''))
                    except ValueError as exc:
                        return dict(error=str(exc))

                with patch.object(meeting, 'post_json', side_effect=measure):
                    if label == 'team_current':
                        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                            variant['answers'] = list(pool.map(run, calls))
                    else:
                        variant['answers'] = [run(call) for call in calls]
                variant.update(seconds=round(time.monotonic() - started, 2), usage=usage)
            report['variants'][label] = variant
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
