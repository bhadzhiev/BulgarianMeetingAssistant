"""My Work → Questions shows the open questions of meeting notes; a person answers or tracks them there."""
import unittest

from tests.test_consistency import ConsistencyBase, notes


def asked(text, stamp='00:00:00'):
    return dict(text=text, evidence_timestamp=stamp)


class MeetingQuestionTests(ConsistencyBase):
    def with_questions(self, open_questions=(), needs_decision=(), when='2026-10-19T10:00:00+03:00'):
        return self.meeting(dict(notes(), open_questions=list(open_questions), needs_decision=list(needs_decision)), when)

    def test_questions_of_every_meeting_show_newest_first_and_once(self):
        old = self.with_questions([asked('Кой поддържа резервния сървър?')])
        new = self.with_questions([asked('Кой поддържа резервния сървър?')], [asked('Да купим ли нов UPS?')], '2026-10-23T10:00:00+03:00')
        found = self.service.item_list()['meeting_questions']
        self.assertEqual([(q['text'], q['kind'], q['meeting_id']) for q in found],
                         [('Да купим ли нов UPS?', 'decide', new), ('Кой поддържа резервния сървър?', 'discuss', new)])
        self.assertNotIn(old, {q['meeting_id'] for q in found})

    def test_a_tracked_or_answered_question_moves_to_the_tracked_list_with_its_meeting(self):
        meeting_id = self.with_questions([asked('Кой поддържа резервния сървър?', '00:00:00'), asked('Има ли бюджет за 2027?')])
        source = dict(meeting_id=meeting_id, evidence_timestamp='00:00:00')
        self.service.work_graph_action('question', dict(text='Кой поддържа резервния сървър?', source=source, answer='Иван'))
        data = self.service.item_list()
        [item] = [i for i in data['items'] if i['kind'] == 'question']
        self.assertEqual((item['status'], item['answer'], item['origin']), ('answered', 'Иван', source))
        self.assertEqual([q['text'] for q in data['meeting_questions']], ['Има ли бюджет за 2027?'])
        # New notes of the meeting do not remove a tracked question.
        self.transcribe_again(meeting_id)
        self.new_notes(meeting_id, dict(notes(), open_questions=[asked('Има ли бюджет за 2027?')]))
        self.assertEqual([i['id'] for i in self.service.item_list()['items'] if i['kind'] == 'question'], [item['id']])

    def test_an_invalid_question_source_is_refused(self):
        for source in ('x', dict(meeting_id='nope'), dict(meeting_id='a' * 32, evidence_timestamp='3 min'), dict(meeting_id='a' * 32, other=1)):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.service.work_graph_action('question', dict(text='Въпрос?', source=source))


if __name__ == '__main__':
    unittest.main()
