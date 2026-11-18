"""Optional image-grounded subjects for framing, separate from story writing."""
from pathlib import Path
from .core import read,save,event,Attention
from evidence_v5 import obj,arr,S
from efficient_pipeline import schema_errors

BOX=obj(**{k:{'type':'integer','minimum':0,'maximum':1000} for k in ['left','top','right','bottom']})
SCHEMA=obj(pages=arr(obj(page_id=S,anchors=arr(obj(panel_id=S,source_ids=arr(S),subject_box=BOX,kind={'type':'string','enum':['character','action','object','setting']},confidence={'type':'number','minimum':0,'maximum':1},description=S)))))
PROMPT='''Locate visual attention targets in these ORIGINAL manga pages for a recap
camera. This is geometry work, not a story rewrite. Return DATA, not the schema.
For each supplied panel, locate the actual face/body, creature, meaningful action,
object or setting that the audience should watch while its cited text is spoken.
Prefer the speaking/thinking character or a reaction/action subject over the
speech balloon. A creature is a character. Preserve room around heads and hands.
Follow a balloon tail when associating dialogue with a visible subject; if unsure
give a lower confidence and a wider character group. Do not invent an off-screen
body. Do not use the text balloon itself as a character target. Text can remain
visible incidentally. A written document/status is an object when it is the topic.
Use only supplied panel_id and source_ids from that same panel. A subject can
support several source IDs. Include silent meaningful actions too. Subject boxes
are named INTEGER left/top/right/bottom EDGES, 0..1000 relative to the ORIGINAL WHOLE PAGE,
not relative to a panel. Keep boxes inside their cited panel and page. Inspect
the source image rather than estimating a box from a textual description.
'''

def capture(api,root,pages):
 root=Path(root);missing=[p for p in pages if not (root/'visual-layout'/(p['page_id']+'.json')).exists()]
 if not missing:return
 payload=[];allowed={};panel_boxes={}
 for p in missing:
  reading=read(root/'pages'/(p['page_id']+'.json'))['reading']['pages'][0];panels=[]
  for panel in reading['panels']:
   items=[dict(id=b['id'],text=b['text'],speaker=b['speaker_description']) for b in panel['texts']]
   items += [dict(id=panel['id']+f'-event-{i+1:03}',text=text,speaker=None) for i,text in enumerate(panel['visible_events'])]
   allowed[panel['id']]={r['id'] for r in items}
   panel_boxes[panel['id']]=panel['region']
   panels.append(dict(panel_id=panel['id'],box=[round(x*1000) for x in panel['region']],items=items))
  payload.append(dict(page_id=p['page_id'],panels=panels))
 response=api.generate('reader',PROMPT,{'pages':payload},missing,SCHEMA,16384)
 data=response.get('output');errors=schema_errors(SCHEMA,data) if response.get('complete') else ['Incomplete visual layout']
 if not errors and [p['page_id'] for p in data['pages']]!=[p['page_id'] for p in missing]:errors=['Visual page IDs differ']
 if not errors:
  for p in data['pages']:
   for a in p['anchors']:
    b=a['subject_box'];x,y,x2,y2=[b[k] for k in ['left','top','right','bottom']]
    if x2<=x or y2<=y:errors.append('Invalid visual box')
    if not a['panel_id'].startswith(p['page_id']+'-panel-') or a['panel_id'] not in allowed or any(r not in allowed.get(a['panel_id'],set()) for r in a['source_ids']):errors.append('Visual target points outside its panel')
 if errors:
  if len(missing)>1:
   for p in missing:capture(api,root,[p])
   return
  raise Attention('Visual layout failed validation: '+str(errors[:3]))
 for p,layout in zip(missing,data['pages']):
  for a in layout['anchors']:
   b=a['subject_box'];a['subject_box']=[b['left']/1000,b['top']/1000,(b['right']-b['left'])/1000,(b['bottom']-b['top'])/1000];a['panel_box']=panel_boxes[a['panel_id']]
  save(root/'visual-layout'/(p['page_id']+'.json'),{**layout,'source_sha256':p['sha256'],'model':response['config']['model']})
 event(root,'visual_layout_saved',pages=[p['page_id'] for p in missing])

def main():
 import argparse,time
 from concurrent.futures import ThreadPoolExecutor,as_completed
 from .providers import Google
 from .core import Pending
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--unit',default='unit-0001');a=p.parse_args();root=Path(a.job);config=read(root/'config.json');api=Google(root,config.get('provider_state'));unit=next(u for u in read(root/'inventory.json')['units'] if u['id']==a.unit);draft=read(root/'units'/a.unit/'draft.json');pids={b['page_id'] for b in draft['beats']};pages=[p for p in unit['pages'] if p['page_id'] in pids];pending=[pages[i:i+2] for i in range(0,len(pages),2)];deadline=time.time()+600;issues=[]
 while pending and time.time()<deadline:
  retry=[];waits=[]
  with ThreadPoolExecutor(max_workers=2) as pool:
   futures={pool.submit(capture,api,root,g):g for g in pending}
   for future in as_completed(futures):
    try:future.result()
    except Pending as exc:retry.append(futures[future]);waits.append(exc.resume)
    except Attention as exc:issues.append(dict(pages=[p['page_id'] for p in futures[future]],reason=str(exc),fallback='enclosing panel'))
  pending=retry
  if pending:
   resume=min(waits)
   if resume>deadline:break
   while time.time()<resume:time.sleep(min(20,max(.1,resume-time.time())))
 missing=[p['page_id'] for p in pages if not (root/'visual-layout'/(p['page_id']+'.json')).exists()];save(root/'units'/a.unit/'visual-layout-report.json',dict(total_pages=len(pages),captured=len(pages)-len(missing),missing=missing,issues=issues));print('Subject layout pages:',len(pages)-len(missing),'/',len(pages),'fallbacks:',missing,flush=True)
if __name__=='__main__':main()
