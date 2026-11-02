"""Disposable local benchmark; no accounts, model requests or real meetings are read."""
import argparse
import json
from pathlib import Path
import resource
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage import Library
from app.conversations import Conversations
from app.repo_reports import analysis_batches

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args();results=[]
 with tempfile.TemporaryDirectory(prefix='atlanta-ux-benchmark-') as tmp:
  for count in [100,1000,5000]:
   root=Path(tmp)/str(count);root.mkdir();library=Library(root)
   for n in range(count):
    key=f'{n:032x}';folder=root/key;folder.mkdir()
    (folder/'meeting.json').write_text(json.dumps(dict(id=key,title=f'Synthetic {n}',created='2026-10-27T10:00:00+03:00',status='ready',duration=10)))
    (folder/'transcript.json').write_text(json.dumps([dict(start=0,end=10,speaker='Synthetic speaker',text='Discuss backup rollout and acceptance checks. '*25)]))
   optimized=library.get
   def uncached(key):
    with library.lock:
     library._finish_scope_batch()
     return json.loads((library.directory(key)/'meeting.json').read_text())
   modes={}
   for mode,getter in [('uncached_metadata',uncached),('cached_metadata',optimized)]:
    library.get=getter;browser=Conversations(SimpleNamespace(library=library));browser.attachments=lambda _:[];times=[]
    for _ in range(5):
     start=time.perf_counter();found=browser.listing(dict(source='meeting',q='backup'));times.append(time.perf_counter()-start);assert found['total']==count
    modes[mode]=dict(cold_seconds=round(times[0],4),warm_p50_seconds=round(statistics.median(times[1:]),4),warm_max_seconds=round(max(times[1:]),4))
   results.append(dict(meetings=count,**modes))
  evidence=[dict(id=str(i),change_id='pr:'+str(i//8),text='Synthetic code evidence. '*40) for i in range(80)]
  result=dict(library=results,report_plan=dict(previous_worker_steps=80,batched_worker_steps=len(analysis_batches(evidence))+1,includes_synthesis=True),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,model_inference_benchmarked=False)
  encoded=json.dumps(result,indent=2);print(encoded)
  if args.output:args.output.write_text(encoded+'\n')
if __name__=='__main__':main()
