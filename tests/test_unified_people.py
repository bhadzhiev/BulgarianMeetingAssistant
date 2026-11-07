import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.people import People
from app.service import MeetingService
from app.storage import Library, atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class UnifiedPeopleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'library';self.root.mkdir()

    def service(self):
        service=MeetingService(self.root,PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'archives')
        self.addCleanup(service.close);return service

    def test_legacy_import_preserves_profiles_aliases_and_original_bytes(self):
        p=People(self.root/'people.json')
        old=p.save(dict(name='Мария Петрова',aliases=['Мария'],emails=['maria@example.invalid'],github=dict(login='maria',id=12)))
        raw='["Мария", "мария", "Иван", "SPEAKER_00"]\n'.encode()
        (self.root/'speakers.json').write_bytes(raw)
        library=Library(self.root)
        self.assertEqual(library.people.get(old['id']),old)
        self.assertEqual(set(library.speakers()),{'Мария Петрова','Иван'})
        self.assertEqual(len(library.people.list()),2)
        self.assertFalse((self.root/'speakers.json').exists())
        self.assertEqual((self.root/library.people_migration['source']).read_bytes(),raw)
        self.assertEqual(library.people_migration['unresolved'],[])
        ids={p['id'] for p in library.people.list()}
        self.assertEqual({p['id'] for p in Library(self.root).people.list()},ids)

    def test_deleted_person_does_not_return_from_migrated_registry(self):
        atomic_json(self.root/'speakers.json',['Иван'])
        library=Library(self.root);person=library.people.list()[0]
        library.people.delete(person['id'],person['revision'])
        self.assertEqual(Library(self.root).people.list(),[])

    def test_corrupt_sources_are_retained_and_not_replaced(self):
        for damaged in ('speakers.json','people.json'):
            with self.subTest(damaged=damaged),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                atomic_json(root/'speakers.json',['Иван'])
                (root/damaged).write_bytes(b'{broken')
                library=Library(root)
                self.assertIn('error',library.people_migration)
                self.assertEqual((root/damaged).read_bytes(),b'{broken')
                self.assertFalse(list(root.glob('speakers.migrated-*')))

    def test_ambiguous_legacy_name_requires_review_without_guessing(self):
        p=People(self.root/'people.json');a=p.save(dict(name='Мария Петрова'));b=p.save(dict(name='Мария Иванова'))
        rows=[dict(a,aliases=['Мария']),dict(b,aliases=['Мария'])]
        atomic_json(self.root/'people.json',rows)
        atomic_json(self.root/'speakers.json',['Мария'])
        library=Library(self.root)
        self.assertEqual(library.people.match('Мария'),None)
        self.assertEqual(library.people_migration['unresolved'],['Мария'])
        self.assertEqual({p['id'] for p in library.people.list()},{a['id'],b['id']})

    def test_ambiguous_name_does_not_attribute_statements_to_either_profile(self):
        p=People(self.root/'people.json');a=p.save(dict(name='Мария Петрова'));b=p.save(dict(name='Мария Иванова'))
        atomic_json(self.root/'people.json',[dict(a,aliases=['Мария']),dict(b,aliases=['Мария'])])
        s=self.service();mid=self.meeting(s,'Ambiguous')
        atomic_json(s.library.directory(mid)/'transcript.json',[dict(start=0,end=10,speaker='Мария',text='Аз ще проверя.')])
        self.assertEqual(s.person_profile(a['id'])['statements'],0)
        self.assertEqual(s.person_profile(b['id'])['statements'],0)

    def test_bulk_import_is_atomic_on_invalid_name_or_capacity(self):
        people=People(self.root/'people.json')
        for names in [['Иван','x'*81],['Иван',7]]:
            with self.subTest(names=names),self.assertRaises(ValueError):people.import_names(names)
            self.assertEqual(people.list(),[])
        with patch('app.people.MAX_PEOPLE',1),self.assertRaises(ValueError):people.import_names(['Иван','Мария'])
        self.assertFalse((self.root/'people.json').exists())

    def test_one_store_for_profiles_and_legacy_api_and_rename_keeps_identity(self):
        s=self.service();self.assertIs(s.people,s.library.people)
        person=s.save_person(dict(name='Мария'))['person']
        self.assertEqual(s.library.speakers(),['Мария'])
        renamed=s.save_person(dict(person,name='Мария Петрова'))['person']
        self.assertEqual(s.library.speakers(),['Мария Петрова'])
        self.assertEqual(s.people.match('Мария')['id'],person['id'])
        s.save_speakers(['Мария','Иван'])
        self.assertEqual(len(s.people.list()),2)
        s.save_speakers([])
        self.assertEqual(len(s.people.list()),2,'Old suggestion API must not delete contacts')
        self.assertFalse((self.root/'speakers.json').exists())

    def test_generic_labels_never_become_global_people(self):
        s=self.service();s.library.add_speakers(['SPEAKER_00','speaker_01','Иван'])
        self.assertEqual(s.library.speakers(),['Иван'])
        with self.assertRaisesRegex(ValueError,'Unidentified speakers'):s.save_person(dict(name='SPEAKER_02'))
        self.assertIsNone(s.people.match('SPEAKER_00'))

    def meeting(self,s,name):
        m=s.library.create(name,'in_person',s.settings)['id'];s.library.update(m,duration=20,status='ready')
        atomic_json(s.library.directory(m)/'transcript.json',[dict(start=0,end=10,speaker='SPEAKER_00',text='Да, ще проверя.')])
        return m

    def test_same_diarization_label_in_two_meetings_is_not_one_identity(self):
        s=self.service();maria=s.save_person(dict(name='Мария'))['person'];ivan=s.save_person(dict(name='Иван'))['person']
        a=self.meeting(s,'A');b=self.meeting(s,'B')
        for mid,person in [(a,maria),(b,ivan)]:
            detail=s.detail(mid)
            s.edit(mid,dict(speaker_name=dict(speaker='SPEAKER_00',name=person['name'],revision=detail['transcript_revision'])))
        self.assertEqual(s.detail(a)['transcript'][0]['speaker'],'Мария')
        self.assertEqual(s.detail(b)['transcript'][0]['speaker'],'Иван')
        self.assertEqual(s.person_profile(maria['id'])['meetings'],1)
        self.assertEqual(s.person_profile(ivan['id'])['meetings'],1)
        self.assertEqual(len(s.people.list()),2)

    def test_text_only_edit_does_not_recreate_deleted_contact(self):
        s=self.service();m=self.meeting(s,'Meeting');detail=s.detail(m)
        s.edit(m,dict(speaker_name=dict(speaker='SPEAKER_00',name='Иван',revision=detail['transcript_revision'])))
        person=s.people.list()[0];s.delete_person(person['id'],person['revision'])
        detail=s.detail(m);source=detail['transcript'];source[0]['text']='Да, проверих.'
        s.edit(m,dict(transcript=source,transcript_revision=detail['transcript_revision'],defer_analysis=True))
        self.assertEqual(s.people.list(),[])
        self.assertEqual(s.detail(m)['transcript'][0]['speaker'],'Иван')

    def test_task_identity_survives_person_rename_and_migration(self):
        s=self.service();person=s.save_person(dict(name='Мария'))['person']
        task=s.create_task(dict(request_id='1'*32,text='Провери достъпа',owner='Мария'))
        changed=s.save_person(dict(person,name='Мария Петрова'))['person']
        owner,how=s.people.owner_of(s.items.items[task['id']])
        self.assertEqual(owner['id'],person['id']);self.assertEqual(how,'name')
        self.assertEqual(changed['aliases'],['Мария'])

    def test_legacy_backup_people_are_restored_before_name_import(self):
        import tarfile
        from app import backup
        source=Path(self.tmp.name)/'source';source.mkdir()
        p=People(source/'people.json');person=p.save(dict(name='Мария Петрова',aliases=['Мария'],emails=['maria@example.invalid']))
        atomic_json(source/'speakers.json',['Мария'])
        archive=backup.create(source,Path(self.tmp.name)/'archives')
        s=self.service();s.restore_backup(archive['name'])
        self.assertEqual(len(s.people.list()),1)
        self.assertEqual(s.people.list()[0]['id'],person['id'])
        self.assertEqual(s.people.list()[0]['emails'],person['emails'])


if __name__=='__main__':unittest.main()
