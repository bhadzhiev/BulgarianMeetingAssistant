import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import notes_consolidation as nc, processing
from app.local_ai import OutputTruncatedError
from app.service import DEFAULTS
from app.storage import atomic_json
from meeting_assistant import TranscriptSegment, timestamp, transcript_for_llm


def minutes(**fields):
    return dict(dict(summary=[], decisions=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[]), **fields)


def task(text='Обнови базата данни', stamp='00:00:00', **extra):
    return dict(task=text, owner='Иван', deadline=None, due_date=None, evidence_timestamp=stamp, **extra)


def grouped(settings, messages, schema, stage):
    facts = json.loads(messages[1]['content'])['untrusted_candidates']
    assert stage == 'meeting_consolidation'
    ids = [f['id'] for f in facts]
    if 'text' in schema['properties']['groups']['items']['properties']:
        return dict(groups=[dict(members=ids, text='Обсъдена е миграция на базата данни.')])
    return dict(groups=[dict(members=ids, representative=ids[0])])


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.segments = [TranscriptSegment(i*10, i*10+9, 'Обсъждаме базата данни.', 'Иван') for i in range(30)]
        self.settings = dict(DEFAULTS, summarizer='local')

    def run_consolidation(self, parts, fake=grouped):
        with patch('app.local_ai.complete_json', side_effect=fake) as model:
            result, audit = nc.consolidate(parts, self.segments, self.settings, self.root, lambda _: None, 'not-for-local')
        return result, audit, model

    def test_compact_input_keeps_every_anchor_and_short_answers(self):
        segments = [TranscriptSegment(0, 1, 'Миграция?', 'Иван'), TranscriptSegment(1, 2, 'Днес?', 'Иван'),
                    TranscriptSegment(2, 3, 'Не.', 'Мария'), TranscriptSegment(3, 4, 'Добре.', None),
                    TranscriptSegment(4, 5, 'Да.', None), TranscriptSegment(20, 21, 'Утре.', 'Иван')]
        before = copy.deepcopy(segments)
        text = transcript_for_llm(segments)
        self.assertEqual(segments, before)
        self.assertEqual(len(text.splitlines()), 5)
        for segment in segments:
            self.assertIn('['+timestamp(segment.start)+']', text)
            self.assertIn(segment.text, text)
        self.assertEqual(text.count('Иван:'), 2)

    def test_grouping_keeps_original_commitment_and_all_evidence(self):
        first, second = task(), task(stamp='00:00:10')
        result, audit, model = self.run_consolidation([minutes(tasks=[first]), minutes(tasks=[second])])
        self.assertEqual(result['tasks'], [first])
        proof = audit['groups'][nc.fact_key('tasks', first)]
        self.assertEqual(len(proof['members']), 2)
        self.assertEqual([e['start'] for e in proof['evidence']], [0, 10])
        self.assertEqual(len(audit['candidates']), 2)
        self.assertEqual(model.call_args.args[0]['local_ai_model'], self.settings['local_ai_model'])
        self.assertNotIn('not-for-local', json.dumps(model.call_args.args))

    def test_conflicting_details_veto_even_model_merge(self):
        variants = [dict(task='Не обновявай базата данни'), dict(owner='Мария'), dict(deadline='утре'),
                    dict(due_date='2026-11-08'), dict(task='Обнови базата данни в production'),
                    dict(task='Обнови базата данни версия 2')]
        for changes in variants:
            with self.subTest(changes=changes):
                a = task(); b = dict(a, evidence_timestamp='00:00:10', **changes)
                result, audit, _ = self.run_consolidation([minutes(tasks=[a]), minutes(tasks=[b])])
                self.assertEqual(result['tasks'], [a, b])
                self.assertEqual(len(audit['rejected']), 1)
        a = dict(id='a', field='tasks', value=task('Update database'))
        b = dict(id='b', field='tasks', value=task("Can't update database"))
        self.assertIsNotNone(nc.merge_conflict([a,b]))

    def test_decisions_and_tasks_stay_separate(self):
        result, _, _ = self.run_consolidation([minutes(tasks=[task()]), minutes(decisions=[dict(text='Обнови базата данни', evidence_timestamp='00:00:00')])])
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(len(result['decisions']), 1)

    def test_global_summary_bounded_and_all_sources_accounted(self):
        parts = [minutes(summary=[dict(text=f'Тема {i}', evidence_timestamp=timestamp(i*10))]) for i in range(25)]
        result, audit, model = self.run_consolidation(parts)
        self.assertLessEqual(len(result['summary']), 6)
        origins = {member for group in audit['groups'].values() for member in group['members']}
        self.assertEqual(origins, {f['id'] for f in audit['candidates']})
        self.assertLessEqual(model.call_count, nc.MAX_REQUESTS)
        for call in model.call_args_list:
            self.assertLessEqual(len(nc.canonical(call.args[1])), nc.MAX_BATCH_CHARS)

    def test_invalid_plans_cannot_drop_duplicate_or_invent_sources(self):
        facts = nc.candidates([minutes(tasks=[task(), task(stamp='00:00:10')])], self.segments)
        a,b = [f['id'] for f in facts]
        for groups in [[dict(members=[a], representative=a)],
                       [dict(members=[a,a,b], representative=a)],
                       [dict(members=[a,b,'fake'], representative=a)],
                       [dict(members=[a], representative=b),dict(members=[b],representative=b)],
                       [dict(members=[a,b], representative=a, owner='new')]]:
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                nc.validate_plan(dict(groups=groups), facts)

    def test_resume_validates_cached_responses(self):
        parts = [minutes(tasks=[task()]), minutes(tasks=[task(stamp='00:00:10')])]
        self.run_consolidation(parts)
        _, _, model = self.run_consolidation(parts)
        self.assertEqual(model.call_count, 0)
        path = self.root / '.consolidation-progress.json'
        saved = json.loads(path.read_text())
        saved['responses'] = {k: dict(groups=[]) for k in saved['responses']}
        atomic_json(path, saved)
        _, _, model = self.run_consolidation(parts)
        self.assertEqual(model.call_count, 1)

    def test_input_and_request_budgets_fail_without_publish(self):
        with self.assertRaisesRegex(ValueError, 'input budget'):
            self.run_consolidation([minutes(tasks=[task('x'*10000)]), minutes()])
        with patch.object(nc,'MAX_REQUESTS',0), self.assertRaisesRegex(ValueError,'budget reached'):
            self.run_consolidation([minutes(tasks=[task()]), minutes(tasks=[task(stamp='00:00:10')])])
        self.assertFalse((self.root/'minutes.json').exists())

    def test_audit_ignores_changed_transcript_or_statement_and_corruption(self):
        result,audit,_ = self.run_consolidation([minutes(tasks=[task()]), minutes(tasks=[task(stamp='00:00:10')])])
        atomic_json(self.root/'minutes.consolidation.json',audit)
        self.assertIsNotNone(nc.audit_for(self.root,result,self.segments))
        self.assertIsNone(nc.audit_for(self.root,result,[TranscriptSegment(0,1,'Different')]))
        self.assertEqual(nc.audit_for(self.root,minutes(tasks=[task('Edited')]),self.segments)['groups'],{})
        audit['candidates'][0]['evidence'] = ['broken']
        atomic_json(self.root/'minutes.consolidation.json',audit)
        self.assertIsNone(nc.audit_for(self.root,result,self.segments))

    def test_partial_review_only_promotes_accepted_proof(self):
        old, audit, _ = self.run_consolidation([minutes(tasks=[task()]),minutes(tasks=[task(stamp='00:00:10')])])
        atomic_json(self.root/'minutes.consolidation.json',audit)
        new, proposed, _ = self.run_consolidation([minutes(decisions=[dict(text='Запазваме базата.',evidence_timestamp='00:00:00')]),minutes()])
        atomic_json(self.root/'minutes.consolidation.proposed.json',proposed)
        nc.promote_audit(self.root,old,self.segments)
        proof=nc.audit_for(self.root,old,self.segments)
        self.assertEqual(set(proof['groups']),{nc.fact_key('tasks',old['tasks'][0])})
        self.assertEqual(len(proof['candidates']),2)

    def test_split_outputs_trigger_consolidation_and_preserve_saved_notes(self):
        atomic_json(self.root/'transcript.json',[dict(start=i,end=i+1,text='Test',speaker='Иван') for i in range(2)])
        saved = minutes(tasks=[task('Ръчно редактирана задача')])
        atomic_json(self.root/'minutes.json',saved)
        def extract(args, group):
            if len(group)>1: raise OutputTruncatedError('length')
            return minutes(tasks=[task(stamp=timestamp(group[0].start))])
        with patch('meeting_assistant.generate_minutes',side_effect=extract), patch('app.local_ai.complete_json',side_effect=grouped) as model:
            processing.summarize(self.root,self.settings,lambda _:None)
        self.assertEqual(model.call_count,1)
        self.assertEqual(json.loads((self.root/'minutes.json').read_text()),saved)
        self.assertEqual(len(json.loads((self.root/'minutes.proposed.json').read_text())['tasks']),1)
        self.assertTrue((self.root/'minutes.consolidation.proposed.json').exists())

    def test_reducer_failure_keeps_extraction_then_retry_reuses_it(self):
        atomic_json(self.root/'transcript.json',[dict(start=i*10,end=i*10+9,text='Text '*600,speaker='Иван') for i in range(2)])
        saved=minutes(tasks=[task('Ръчно')]); atomic_json(self.root/'minutes.json',saved)
        fake=lambda args,group:minutes(tasks=[task(stamp=timestamp(group[0].start))])
        with patch('meeting_assistant.generate_minutes',side_effect=fake), patch('app.local_ai.complete_json',side_effect=ValueError('bad response')):
            with self.assertRaisesRegex(ValueError,'consolidation incomplete'):
                processing.summarize(self.root,self.settings,lambda _:None)
        self.assertEqual(json.loads((self.root/'minutes.json').read_text()),saved)
        self.assertTrue((self.root/'.notes-progress.json').exists())
        self.assertFalse((self.root/'minutes.proposed.json').exists())
        with patch('meeting_assistant.generate_minutes',side_effect=AssertionError('must reuse')), patch('app.local_ai.complete_json',side_effect=grouped):
            processing.summarize(self.root,self.settings,lambda _:None)
        self.assertFalse((self.root/'.notes-progress.json').exists())

    def test_cloud_provider_preserves_model_and_caps_output(self):
        self.settings.update(summarizer='openai', llm_model='chosen-model')
        def cloud(messages, schema, stage, model, api_key, **kwargs):
            self.assertEqual((model, api_key), ('chosen-model', 'test-cloud-key'))
            self.assertEqual(kwargs['max_completion_tokens'], 4096)
            return grouped({},messages,schema,stage)
        with patch('app.prompts.openai_json',side_effect=cloud), patch('app.local_ai.complete_json',side_effect=AssertionError('no fallback')):
            nc.consolidate([minutes(tasks=[task()]),minutes(tasks=[task(stamp='00:00:10')])],self.segments,self.settings,self.root,lambda _:None,'test-cloud-key')
        self.assertNotIn('test-cloud-key',(self.root/'.consolidation-progress.json').read_text())

    def test_only_consolidation_prompt_edit_reuses_extraction(self):
        from app.prompts import Prompts
        prompts = Prompts(self.root/'prompts.json')
        atomic_json(self.root/'transcript.json',[dict(start=i*10,end=i*10+9,text='Text '*600,speaker='Иван') for i in range(2)])
        settings=dict(self.settings,_prompt_snapshot=prompts.snapshot())
        fake=lambda args,group:minutes(tasks=[task(stamp=timestamp(group[0].start))])
        with patch('meeting_assistant.generate_minutes',side_effect=fake), patch('app.local_ai.complete_json',side_effect=ValueError('offline')):
            with self.assertRaises(ValueError): processing.summarize(self.root,settings,lambda _:None)
        snapshot=copy.deepcopy(settings['_prompt_snapshot'])
        snapshot['stages']['meeting_consolidation']['layers'].append(dict(text='More concise',revision=1))
        snapshot['revision']=1;snapshot['id']='changed'
        settings['_prompt_snapshot']=snapshot
        with patch('meeting_assistant.generate_minutes',side_effect=AssertionError('must reuse extraction')),patch('app.local_ai.complete_json',side_effect=grouped):
            processing.summarize(self.root,settings,lambda _:None)


if __name__ == '__main__': unittest.main()
