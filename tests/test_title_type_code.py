"""A generated title starts with the code of the meeting type (2026-11-13)."""
import unittest

from app import meeting_types


class TypeCodeTests(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(meeting_types.code({}), 'GEN')
        self.assertEqual(meeting_types.code(dict(meeting_type='daily')), 'DLY')
        self.assertEqual(meeting_types.code(dict(meeting_type='incident')), 'INC')
        self.assertEqual(set(meeting_types.CODES), set(meeting_types.TYPES), 'every built-in type has a code')
        own = dict(meeting_type='custom-0a1b2c3d', meeting_template=dict(label='1:1 разговор', sections=[]))
        self.assertEqual(meeting_types.code(own), '11Р')
        nameless = dict(meeting_type='custom-0a1b2c3d', meeting_template=dict(label='—', sections=[]))
        self.assertEqual(meeting_types.code(nameless), 'MTG')

    def test_the_code_of_another_type_is_replaced_not_repeated(self):
        daily = dict(meeting_type='daily')
        self.assertEqual(meeting_types.with_code('Бюджет за 2027', daily), 'DLY · Бюджет за 2027')
        self.assertEqual(meeting_types.with_code('GEN · Бюджет за 2027', daily), 'DLY · Бюджет за 2027')
        self.assertEqual(meeting_types.with_code('DLY · Бюджет', daily), 'DLY · Бюджет')
        # Words before the separator that are no code stay.
        self.assertEqual(meeting_types.with_code('SAP · Lift', daily), 'DLY · SAP · Lift')
        # The code of an own type goes when the type changes.
        own = dict(meeting_type='custom-0a1b2c3d', meeting_template=dict(label='Ретро', sections=[]))
        self.assertEqual(meeting_types.with_code('РЕТ · Изводи', daily, own), 'DLY · Изводи')


if __name__ == '__main__':
    unittest.main()
