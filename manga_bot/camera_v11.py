"""Subject-led moves with brief travel, long holds and continuous subpixel poses."""
import math
from .core import digest

DEFAULTS=dict(width=1280,height=720,fps=30,zoom_relax=.94,move_seconds=.62,
 minimum_hold=2.0,max_targets_per_beat=3,drift=.004,zoom_drift=.004,
 yaw_degrees=.65,transition_seconds=.28,transitions=['dissolve','wipe_right'],
 interpolation='cubic',background='sample_paper',motion_blur=.25,crf=19)

def policy(overrides=None):
 if overrides and set(overrides)-set(DEFAULTS):raise ValueError('Unknown camera settings: '+str(sorted(set(overrides)-set(DEFAULTS))))
 result={**DEFAULTS,**(overrides or {})}
 if not 0<result['move_seconds']<=2 or not 0<=result['yaw_degrees']<=2:raise ValueError('Camera movement/yaw outside supported range')
 if result['fps'] not in [24,30,48,60]:raise ValueError('Supported frame rates: 24,30,48,60')
 if not .85<=result['zoom_relax']<=1.05:raise ValueError('zoom_relax must be between .85 and 1.05')
 if not result['transitions'] or any(t not in ['dissolve','wipe_right','wipe_left'] for t in result['transitions']):raise ValueError('Unsupported transition')
 if result['interpolation'] not in ['cubic','lanczos']:raise ValueError('Unsupported interpolation')
 if not 0<=result['motion_blur']<=1 or not 0<=result['drift']<=.03:raise ValueError('Motion blur/drift outside supported range')
 if any(not isinstance(result[k],int) or result[k]<64 or result[k]%2 for k in ['width','height']):raise ValueError('Output dimensions must be even integers, at least 64 pixels')
 bg=result['background']
 if bg!='sample_paper' and not (isinstance(bg,list) and len(bg)==3 and all(isinstance(v,int) and 0<=v<=255 for v in bg)):raise ValueError('Background must be sample_paper or an RGB integer list')
 return result

def ease(t):t=max(0,min(1,t));return t*t*t*(t*(t*6-15)+10)

def pose(box,panel,page,cfg):
 w,h=page['size'];pw=w/h*1080
 # About six percent less magnification than the old cover floor. White paper
 # can extend beyond the page edges into a sampled-paper canvas.
 floor=max(1920/(pw*.95),1/.98)*1.025*cfg['zoom_relax']
 z=max(floor,min(floor*1.22,1920/(pw*max(panel[2],.2)*1.10),1/(max(panel[3],.18)*1.10)))
 cx=box[0]+box[2]/2;cy=box[1]+box[3]/2
 # Prioritize the body/face group, with a small pull toward its panel context.
 cx=.85*cx+.15*(panel[0]+panel[2]/2);cy=.85*cy+.15*(panel[1]+panel[3]/2)
 hx=960/(pw*z);hy=.5/z;cx=max(min(.5,hx),min(max(.5,1-hx),cx));cy=max(hy,min(1-hy,cy))
 return dict(z=z,x=z*pw*(.5-cx),y=z*1080*(.5-cy))

def subject_for(ref,index,layouts):
 item=index[ref];anchors=layouts.get(item['page_id'],{}).get('anchors',[])
 explicit=[a for a in anchors if ref in a['source_ids'] and a['confidence']>=.5]
 if not explicit:
  explicit=[a for a in anchors if a['confidence']>=.65 and a['kind']=='character' and a.get('panel_box')==item['panel']]
 if explicit:
  a=max(explicit,key=lambda a:a['confidence']+(.15 if a['kind']=='character' else 0));return a['subject_box'],a['kind'],'vision_subject'
 # With no verified subject geometry, center the enclosing panel rather than
 # guessing a face location from a speech balloon.
 return item['panel'],'panel','panel_context_fallback'

def plan(beats,timings,index,pages,layouts,overrides=None,focus_cues=None):
 cfg=policy(overrides);clock={c['beat_id']:c for c in timings};shots=[]
 for beat in beats:
  cue=clock[beat['id']];pid=beat['page_id'];page=pages[pid];duration=cue['end']-cue['start'];targets=[]
  refs=sorted([r for r in beat['source_ids'] if index[r]['page_id']==pid],key=lambda r:index[r]['order'])
  guided=(focus_cues or {}).get(beat['id'],[])
  for guide in guided:
   a=guide['anchor'];ref=next((r for r in a['source_ids'] if r in index and index[r]['page_id']==pid),refs[0]);p=pose(a['subject_box'],a['panel_box'],page,cfg)
   if not targets or math.hypot((p['x']-targets[-1]['pose']['x'])/1920,(p['y']-targets[-1]['pose']['y'])/1080)>.07:targets.append(dict(pose=p,source_id=ref,subject_box=a['subject_box'],kind=a['kind'],basis='spoken_phrase_subject',narration_at=guide['at'],phrase=guide['phrase']))
  for ref in ([] if targets else refs):
   box,kind,basis=subject_for(ref,index,layouts);p=pose(box,index[ref]['panel'],page,cfg)
   if not targets or math.hypot((p['x']-targets[-1]['pose']['x'])/1920,(p['y']-targets[-1]['pose']['y'])/1080)>.09:
    targets.append(dict(pose=p,source_id=ref,subject_box=box,kind=kind,basis=basis))
  if not targets:raise ValueError('A camera beat has no current-page evidence')
  cap=max(1,min(cfg['max_targets_per_beat'],int(duration/(cfg['minimum_hold']+cfg['move_seconds']))))
  if guided:targets=targets[:cap]
  elif len(targets)>cap:
   # Spread selections over the page reading path, instead of always taking
   # the first few balloons and ignoring the latter part of the exchange.
   selected=sorted(set(round(i*(len(targets)-1)/max(1,cap-1)) for i in range(cap)));targets=[targets[i] for i in selected]
  new=not shots or shots[-1]['page_id']!=pid
  if new:
   shots.append(dict(page_id=pid,start=cue['start'],end=cue['end'],initial=targets[0]['pose'],moves=[],cues=[],targets=[],transition=cfg['transitions'][(len(shots))%len(cfg['transitions'])]))
  shot=shots[-1];shot['end']=cue['end'];local=cue['start']-shot['start'];slot=duration/len(targets);scheduled=[]
  for i,t in enumerate(targets):
   at=local if i==0 else max(scheduled[-1][0]+cfg['minimum_hold'],t.get('narration_at',cue['start']+i*slot)-shot['start']-cfg['move_seconds']*.75)
   if i and at>cue['end']-shot['start']-cfg['minimum_hold']*.6:continue
   scheduled.append((at,t))
  for i,(at,t) in enumerate(scheduled):
   until=scheduled[i+1][0] if i+1<len(scheduled) else cue['end']-shot['start'];old=sample(shot,at,cfg,drift=False);length=0 if new and i==0 else min(cfg['move_seconds'],(until-at)*.24)
   if length>0:shot['moves'].append(dict(at=at,duration=length,**{'from':old,'to':t['pose']},ease='minimum_jerk',role='panel_transfer'))
   shot['targets'].append({**t,'at':at,'settled_at':at+length,'until':until})
  shot['cues'].append(dict(beat_id=beat['id'],start=cue['start'],end=cue['end'],source_ids=refs))
 for s in shots:
  s['duration']=s['end']-s['start'];s['start_frame']=round(s['start']*cfg['fps']);s['end_frame']=round(s['end']*cfg['fps']);s['source_path']=pages[s['page_id']]['path'];s['source_sha256']=pages[s['page_id']]['sha256']
 return dict(version='v11-subpixel-subjects',config=cfg,shots=shots,duration=shots[-1]['end'] if shots else 0,source_signature=digest([p['sha256'] for p in pages.values()]))

def sample(shot,time,cfg,drift=True):
 p=dict(shot['initial']);moving=False
 for m in shot['moves']:
  if time<m['at']:break
  if time<m['at']+m['duration']:
   u=ease((time-m['at'])/m['duration']);p={k:m['from'][k]+(m['to'][k]-m['from'][k])*u for k in p};moving=True;break
  p=dict(m['to'])
 # Never reset a drift abruptly when a new move starts: a zero-slope envelope
 # is zero at every settled hold's boundaries.
 if drift and not moving:
  for t in shot.get('targets',[]):
   if t['settled_at']<=time<=t['until']:
    u=(time-t['settled_at'])/max(.001,t['until']-t['settled_at']);envelope=math.sin(math.pi*u)**2;direction=-1 if shot['page_id'][-1:].isdigit() and int(shot['page_id'][-1])%2 else 1
    p['x']+=direction*cfg['drift']*1920*envelope;p['z']*=1+cfg['zoom_drift']*envelope;break
 return p
