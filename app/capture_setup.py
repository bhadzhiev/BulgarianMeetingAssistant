"""Last successfully started capture, without titles or credentials."""
import copy
import datetime as dt
import threading
from .safe_json import SafeJSON

class CaptureSetup(SafeJSON):
    _data_attribute='data'
    def __init__(self,path):
        self.lock=threading.RLock();self.data=self._load_file(path,'Last recording setup',None,self._valid)
    def _valid(self,value):
        if value is None:return None
        fields={'version','project_id','series_id','meeting_type','mode','microphone_name','fallback_microphone','transcription_timing','saved_at'}
        if not isinstance(value,dict) or set(value)!=fields or value['version']!=1:raise ValueError('Invalid capture setup')
        for field in ('project_id','series_id'):
            if value[field] is not None and (not isinstance(value[field],str) or not 1<=len(value[field])<=64):raise ValueError('Invalid recording context')
        for field in ('meeting_type','microphone_name','fallback_microphone'):
            if not isinstance(value[field],str) or len(value[field])>300 or any(ord(c)<32 for c in value[field]):raise ValueError('Invalid capture selection')
        if not value['microphone_name'] or not value['meeting_type'] or value['mode'] not in {'online','in_person'} or value['transcription_timing'] not in {'after','live'}:raise ValueError('Invalid capture mode')
        dt.datetime.fromisoformat(value['saved_at']);return copy.deepcopy(value)
    def remember(self,meeting):
        settings=meeting['settings'];value=dict(version=1,project_id=meeting.get('project_id'),series_id=meeting.get('series_id'),meeting_type=meeting.get('meeting_type') or 'general',mode=meeting['mode'],microphone_name=settings['_capture_microphone'],fallback_microphone=settings.get('fallback_microphone',''),transcription_timing='live' if settings.get('live_transcription',True) else 'after',saved_at=dt.datetime.now(dt.timezone.utc).isoformat())
        with self.lock:self._write_file(value);self.data=value
    def public(self):
        with self.lock:return dict(data=copy.deepcopy(self.data),error=self.error)
    def merge(self,value):
        with self.lock:
            self.guard_write();self._valid(value)
            if self.data is None:self._write_file(value);self.data=copy.deepcopy(value)
