"""Map exact narration phrases to already verified image subjects."""
import re,difflib
from .core import read,save,digest,Attention
from evidence_v5 import obj,arr,S
from efficient_pipeline import schema_errors

SCHEMA=obj(beats=arr(obj(beat_id=S,cues=arr(obj(anchor_id=S,phrase=S,reason=S)))))
PROMPT='''Plan visual attention for this ALREADY WRITTEN manga recap. Never rewrite
the narration. Choose 1..3 visual anchors per spoken beat from its page. Prefer
characters, expressions and meaningful actions over speech bubbles. A mentioned
object/setting can take priority at its actual mention. Think about what the
audience should SEE during each part of the line, not just the first source ID.
For each cue, quote an EXACT contiguous phrase from that beat's narration to mark
when that subject becomes relevant. Use 3..10 words where possible. Do not quote
manga dialogue unless those words also appear in the supplied narration. Keep
cues in spoken order. Do not put a reaction before the action that prompts it.
Do not pick every balloon or move at every clause. Hold the useful character or
group while the same exchange continues; repeat a subject only if attention
actually returns to it. Use ONLY that page's supplied anchor_id values.
Return one beat entry for every supplied beat. Empty cues are allowed when no
reliable anchor is available, with panel-center framing then used locally.
'''

def normalize(word):return re.sub('[^a-z0-9]','',word.lower())

def make(api,root,unit_id):
 folder=root/'units'/unit_id;draft=read(folder/'draft.json');speech=read(folder/'speech-timing.json');layouts={};payload=[]
 for b in draft['beats']:
  pid=b['page_id']
  if pid not in layouts:layouts[pid]=read(root/'visual-layout'/(pid+'.json'),{})
  anchors=layouts[pid].get('anchors',[]);available=[dict(anchor_id=pid+f'-subject-{i:03}',kind=a['kind'],description=a['description'],source_ids=a['source_ids']) for i,a in enumerate(anchors) if a['confidence']>=.5]
  payload.append(dict(beat_id=b['id'],text=b['text'],available_anchors=available))
 signature=digest(dict(payload=payload,speech=speech['signature'],version=1));path=folder/'focus-timing.json';old=read(path)
 if old and old.get('signature')==signature:return old
 result=api.generate('reader',PROMPT,{'beats':payload},[],SCHEMA,12288)
 output=result.get('output');errors=schema_errors(SCHEMA,output) if result.get('complete') else ['Incomplete visual focus plan']
 if errors:raise Attention(str(errors[:3]))
 if [b['beat_id'] for b in output['beats']]!=[b['id'] for b in draft['beats']]:raise Attention('Visual focus plan omitted/reordered beats')
 tokens=[normalize(w) for b in draft['beats'] for w in b['text'].split()];asr=[normalize(w['word']) for w in speech['words']];match=difflib.SequenceMatcher(None,tokens,asr,autojunk=False);mapping={a+i:b+i for a,b,n in match.get_matching_blocks() for i in range(n)};offset=0;timings={c['beat_id']:c for c in speech['cues']};cues={};warnings=[]
 for beat,entry,request in zip(draft['beats'],output['beats'],payload):
  valid={a['anchor_id'] for a in request['available_anchors']};rows=[];last=-1
  for c in entry['cues']:
   pos=beat['text'].lower().find(c['phrase'].lower())
   if c['anchor_id'] not in valid or pos<0:
    warnings.append(dict(beat_id=beat['id'],reason='Unknown anchor or nonliteral phrase rejected'));continue
   word=len(beat['text'][:pos].split());glob=offset+word
   choices=[k for k in mapping if offset<=k<offset+len(beat['text'].split())]
   if not choices:continue
   nearest=min(choices,key=lambda k:abs(k-glob));at=speech['words'][mapping[nearest]]['start'];at=max(timings[beat['id']]['start'],min(timings[beat['id']]['end'],at))
   if at<last:warnings.append(dict(beat_id=beat['id'],reason='Out-of-order focus phrase rejected'));continue
   last=at;anchor_index=int(c['anchor_id'].rsplit('-',1)[1]);anchor=layouts[beat['page_id']]['anchors'][anchor_index];rows.append(dict(at=at,phrase=c['phrase'],anchor_id=c['anchor_id'],anchor=anchor,reason=c['reason']))
  cues[beat['id']]=rows;offset+=len(beat['text'].split())
 data=dict(signature=signature,cues=cues,warnings=warnings,model=result['config']['model'],narration_changed=False);save(path,data);return data

if __name__=='__main__':
 import argparse
 from pathlib import Path
 from .providers import Google
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--unit',default='unit-0001');a=p.parse_args();root=Path(a.job);cfg=read(root/'config.json');r=make(Google(root,cfg.get('provider_state')),root,a.unit);print('Timed visual beats:',sum(bool(v) for v in r['cues'].values()),'warnings:',len(r['warnings']))
