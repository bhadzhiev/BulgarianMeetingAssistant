import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import backup,identity_channels
from app.people import People
from app.projects import Projects
from app.github_links import GitHubLinks
from app.meeting_templates import Templates
from app.service import MeetingService
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
STORES={'people.json':People,'projects.json':Projects,'github-links.json':GitHubLinks,'meeting-templates.json':Templates}


def add_record(name,store):
    if name=='people.json':return store.save(dict(name='Ivan'))
    if name=='projects.json':
        key=store.ensure_project(dict(name='Atlas'));store.save();return key
    if name=='github-links.json':return store.link(dict(kind='item',id='a'*12),'org/repo',7)
    return store.save(dict(label='Review',prepare='general',sections=[dict(title='Progress',instruction='Only observed progress',review=False)]))


def raw_save(name,store):
    return store.save_file() if name=='people.json' else store.save() if name=='projects.json' else store._save()


class MetadataStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_missing_is_empty_but_first_save_is_allowed(self):
        for name,cls in STORES.items():
            with self.subTest(name=name):
                store=cls(self.root/name);self.assertIsNone(store.error);add_record(name,store);self.assertTrue((self.root/name).exists());self.assertIsNone(cls(self.root/name).error)
    def test_corrupt_bytes_and_memory_survive_all_writes(self):
        for name,cls in STORES.items():
            with self.subTest(name=name):
                path=self.root/name;raw=b'{invalid JSON\xff';path.write_bytes(raw);store=cls(path);self.assertTrue(store.error)
                before=copy.deepcopy(getattr(store,store._data_attribute))
                for operation in [lambda:add_record(name,store),lambda:raw_save(name,store),lambda:store.merge([] if name in {'people.json','meeting-templates.json'} else dict(projects=[],series=[]) if name=='projects.json' else {})]:
                    with self.assertRaisesRegex(ValueError,name):operation()
                    self.assertEqual(path.read_bytes(),raw);self.assertEqual(getattr(store,store._data_attribute),before)
    def test_invalid_root_or_one_bad_row_blocks_the_whole_file(self):
        for name,cls in STORES.items():
            with self.subTest(name=name):
                path=self.root/name;store=cls(path);add_record(name,store);valid=json.loads(path.read_text())
                if isinstance(valid,list):partial=valid+[{'bad':'row'}];wrong={}
                elif name=='projects.json':partial=dict(valid,series=[dict(id='broken',name='Daily',project_id='missing')]);wrong=[]
                else:partial=dict(valid,broken={'bad':'row'});wrong=[]
                for document in [wrong,partial]:
                    raw=json.dumps(document).encode();path.write_bytes(raw);blocked=cls(path);self.assertTrue(blocked.error)
                    with self.assertRaises(ValueError):add_record(name,blocked)
                    self.assertEqual(path.read_bytes(),raw)
    def test_unreadable_file_is_not_treated_as_missing(self):
        original_read=Path.read_bytes
        for name,cls in STORES.items():
            path=self.root/name;path.write_bytes(b'original bytes')
            def read(p):
                if p==path:raise PermissionError('Access denied')
                return original_read(p)
            with patch.object(Path,'read_bytes',read):
                blocked=cls(path);self.assertTrue(blocked.error)
                with self.assertRaises(ValueError):add_record(name,blocked)
            self.assertEqual(path.read_bytes(),b'original bytes')
    def test_external_edits_are_not_overwritten_after_load(self):
        for name,cls in STORES.items():
            with self.subTest(name=name):
                path=self.root/name;store=cls(path);add_record(name,store);external=b'{external unfinished edit';path.write_bytes(external)
                with self.assertRaises(ValueError):add_record(name,store)
                self.assertEqual(path.read_bytes(),external);self.assertTrue(store.error)
    def test_failed_atomic_write_does_not_publish_candidate(self):
        for name in ('people.json','github-links.json','meeting-templates.json'):
            with self.subTest(name=name):
                store=STORES[name](self.root/name);before=copy.deepcopy(getattr(store,store._data_attribute))
                with patch('app.safe_json.atomic_json',side_effect=OSError('disk full')),self.assertRaises(OSError):add_record(name,store)
                self.assertEqual(getattr(store,store._data_attribute),before);self.assertFalse((self.root/name).exists())


class IdentityRemovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'archives');self.addCleanup(self.s.close)
    def linked_person(self):
        person=self.s.people.save(dict(name='Ivan',emails=['other@example.invalid']))
        for account in ('work','personal'):person=self.s.people.confirm_channel(person['id'],person['revision'],'gmail',account,'Ivan <ivan@example.invalid>')
        return self.s.people.confirm_channel(person['id'],person['revision'],'google_chat','work','users/123')
    def test_removal_uses_provider_account_and_external_id(self):
        person=self.linked_person();work=next(i for i in person['identities'] if i['provider']=='gmail' and i['account']=='work')
        saved=identity_channels.remove(self.s,dict(person_id=person['id'],revision=person['revision'],identity=work))['person']
        self.assertNotIn(work,saved['identities']);self.assertIn(dict(provider='gmail',account='personal',external_id='ivan@example.invalid'),saved['identities']);self.assertIn('ivan@example.invalid',saved['emails']);self.assertIn('other@example.invalid',saved['emails']);self.assertIn(dict(provider='google_chat',account='work',external_id='users/123'),saved['identities'])
        reloaded=People(self.s.library.root/'people.json').get(person['id']);self.assertEqual(saved,reloaded)
    def test_last_email_identity_removes_only_its_email(self):
        person=self.linked_person()
        for account in ('work','personal'):
            identity=next(i for i in person['identities'] if i['provider']=='gmail' and i['account']==account)
            person=identity_channels.remove(self.s,dict(person_id=person['id'],revision=person['revision'],identity=identity))['person']
        self.assertEqual(person['emails'],['other@example.invalid']);self.assertEqual([i['provider'] for i in person['identities']],['google_chat'])
    def test_stale_revision_cannot_remove_any_identity(self):
        person=self.linked_person();raw=(self.s.library.root/'people.json').read_bytes()
        with self.assertRaises(WorkItemConflict):identity_channels.remove(self.s,dict(person_id=person['id'],revision=person['revision']-1,identity=person['identities'][0]))
        self.assertEqual((self.s.library.root/'people.json').read_bytes(),raw)


class MetadataRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source=self.service('source');self.root.joinpath('target').mkdir()
        for name,store in self.source.metadata_stores():add_record(name,store)
        self.meeting=self.source.library.create('Saved meeting','imported',dict(self.source.settings))
        self.source.library.update(self.meeting['id'],status='ready')
        self.archive=self.source.create_backup()['created']['name']
    def service(self,name):
        service=MeetingService(self.root/name,PROJECT,google=FakeGoogle(),backup_dir=self.root/'archives');self.addCleanup(service.close);return service
    def corrupt_target(self):
        for name in STORES:(self.root/'target'/name).write_bytes(b'{damaged '+name.encode())
        return self.service('target')
    def test_external_changes_publish_state_events_and_recovery_warnings(self):
        target=self.service('target')
        for name in STORES:
            with self.subTest(name=name):
                events=target.watcher.events()
                try:
                    self.assertEqual(next(events)[0],'hello')
                    (target.library.root/name).write_bytes(b'{external incomplete write')
                    target.watcher.check()
                    self.assertEqual(next(events)[0],'state')
                    self.assertIn(name,target.snapshot()['storage_errors'])
                finally:events.close()

    def test_verified_restore_recovers_every_store_and_keeps_original_bytes(self):
        target=self.corrupt_target();self.assertEqual(set(target.snapshot()['storage_errors']),set(STORES))
        result=target.restore_backup(self.archive);self.assertEqual(set(result['recovered_metadata']),set(STORES));self.assertIn(self.meeting['id'],result['restored']);self.assertEqual(target.snapshot()['storage_errors'],{})
        for name,store in target.metadata_stores():
            with self.subTest(name=name):
                self.assertIsNone(store.error);self.assertEqual(getattr(store,store._data_attribute),getattr(dict(self.source.metadata_stores())[name],store._data_attribute))
                copies=list((self.root/'target').glob(Path(name).stem+'.corrupt-*.json'));self.assertEqual(len(copies),1);self.assertEqual(copies[0].read_bytes(),b'{damaged '+name.encode());self.assertIsNone(STORES[name](self.root/'target'/name).error)
        target.people.save(dict(name='Maya'));self.assertEqual(len(target.people.list()),2)
    def test_corrupt_metadata_cannot_be_archived_as_verified(self):
        target=self.corrupt_target();before=set(target.backup_dir.iterdir())
        with self.assertRaisesRegex(ValueError,'needs recovery'):target.create_backup()
        self.assertEqual(set(target.backup_dir.iterdir()),before)
        for name in STORES:self.assertEqual((self.root/'target'/name).read_bytes(),b'{damaged '+name.encode())
    def test_semantically_invalid_archive_is_rejected_before_meetings_move(self):
        path=self.source.library.root/'people.json';path.write_bytes(b'{bad archive metadata')
        archive=backup.create(self.source.library.root,self.source.backup_dir)['name'];target=self.service('target')
        person=target.people.save(dict(name='Local'));before=(target.library.root/'people.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'Invalid people.json'):target.restore_backup(archive)
        self.assertEqual(target.library.list(),[]);self.assertEqual((target.library.root/'people.json').read_bytes(),before);self.assertEqual(target.people.list(),[person])
    def test_missing_metadata_in_archive_cannot_clear_recovery_error(self):
        (self.source.library.root/'people.json').unlink();archive=backup.create(self.source.library.root,self.source.backup_dir)['name'];target=self.corrupt_target()
        with self.assertRaisesRegex(ValueError,'no people.json'):target.restore_backup(archive)
        self.assertEqual(target.library.list(),[]);self.assertTrue(target.people.error);self.assertEqual((target.library.root/'people.json').read_bytes(),b'{damaged people.json')
    def test_healthy_metadata_is_merged_without_a_corrupt_copy(self):
        target=self.service('target');local=target.people.save(dict(name='Maya'))
        target.restore_backup(self.archive)
        self.assertEqual({p['name'] for p in target.people.list()},{'Ivan','Maya'});self.assertEqual(target.people.get(local['id']),local);self.assertEqual(list(target.library.root.glob('*.corrupt-*.json')),[])
    def test_corrupt_projects_cannot_delete_a_template_or_change_meeting_scope(self):
        target=self.service('target');template=add_record('meeting-templates.json',target.templates)
        (target.library.root/'projects.json').write_bytes(b'{broken')
        before=(target.library.root/'meeting-templates.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'projects.json'):target.delete_template(template['id'],template['revision'])
        self.assertEqual((target.library.root/'meeting-templates.json').read_bytes(),before)


class MetadataHTTPTests(unittest.TestCase):
    from tests import test_http as _http
    setUp=_http.HTTPTests.setUp
    tearDown=_http.HTTPTests.tearDown
    request=_http.HTTPTests.request

    def test_read_only_state_is_visible_and_api_write_preserves_bytes(self):
        path=self.service.library.root/'people.json';raw=b'{invalid people';path.write_bytes(raw)
        status,response,_=self.request('/api/state')
        self.assertEqual(status,200);self.assertIn('people.json',json.loads(response)['storage_errors'])
        status,response,_=self.request('/api/people/save',dict(name='Do not overwrite'))
        self.assertEqual(status,400);self.assertIn('read-only',json.loads(response)['error']);self.assertEqual(path.read_bytes(),raw)
        status,html,_=self.request('/')
        self.assertEqual(status,200);self.assertIn(b'id="metadata-warning"',html);self.assertIn(b'Open Backup settings',html)
