"""Speech-cued 2D camera over intact page assets; deterministic under seeking."""
import difflib,math,re

def align_beats(beats,words,duration,aliases=None):
    aliases=aliases or {}
    def norm(w):
        w=re.sub('[^a-z0-9]','',w.lower());return aliases.get(w,w)
    tokens=[w for b in beats for w in b['text'].split()]
    match=difflib.SequenceMatcher(None,[norm(w) for w in tokens],[norm(w['word']) for w in words],autojunk=False)
    mapping={a+i:b+i for a,b,n in match.get_matching_blocks() for i in range(n)}
    if not mapping or match.ratio()<.88:raise ValueError('Speech alignment is too uncertain for automatic camera cues')
    starts=[0.0];offset=0
    for beat in beats[:-1]:
        offset+=len(beat['text'].split());index=min(mapping,key=lambda k:(abs(k-offset),k<offset))
        t=words[mapping[index]]['start']
        if t<=starts[-1]:raise ValueError('Ambiguous/nonmonotonic spoken beat timing')
        starts.append(t)
    starts.append(duration)
    return [dict(beat_id=b['id'],start=starts[i],end=starts[i+1]) for i,b in enumerate(beats)],match.ratio()

def ease(t,name):
    t=max(0,min(1,t))
    if name=='power1.out':return 1-(1-t)**2
    if name=='power2.out':return 1-(1-t)**3
    if name=='power3.out':return 1-(1-t)**4
    if name=='power2.inOut':return 4*t**3 if t<.5 else 1-(-2*t+2)**3/2
    return t

def focus_pose(items,width,height):
    boxes=[i['region'] for i in items]
    if not boxes or any(len(b)!=4 or any(not math.isfinite(v) or v<0 or v>1 for v in b) or b[2]<=0 or b[3]<=0 or b[0]+b[2]>1.00001 or b[1]+b[3]>1.00001 for b in boxes):raise ValueError('Invalid evidence region')
    x=min(b[0] for b in boxes);y=min(b[1] for b in boxes)
    right=max(b[0]+b[2] for b in boxes);bottom=max(b[1]+b[3] for b in boxes)
    cx=(x+right)/2;cy=(y+bottom)/2
    # Include visual context around a dialogue balloon rather than magnifying text alone.
    bw=max(.55,right-x)*1.12;bh=max(.30,bottom-y)*1.12
    page_width=width/height*1080
    z=max(1,min(3.2,1920/(bw*page_width),1080/(bh*1080)))
    px=(1920-page_width)/2+cx*page_width;py=cy*1080
    return dict(z=z,x=max(-960*(z-1),min(960*(z-1),z*(960-px))),
        y=max(-540*(z-1),min(540*(z-1),z*(540-py))))

def sample(shot,time):
    pose=dict(shot.get('initial',dict(z=1.0,x=0.0,y=0.0)))
    for m in shot['moves']:
        if time<m['at']:break
        if time>=m['at']+m['duration']:pose=m['to'];continue
        u=ease((time-m['at'])/m['duration'],m['ease'])
        return {k:m['from'][k]+(m['to'][k]-m['from'][k])*u for k in pose}
    return pose

def plan_camera(beats,timings,item_map,page_map):
    timing={r['beat_id']:r for r in timings};shots=[]
    for beat in beats:
        cue=timing[beat['id']];focus=[item_map[i] for i in beat['focus_source_ids']]
        if len({i['page_id'] for i in focus})!=1:raise ValueError('A spoken cue cannot focus different pages simultaneously')
        pid=focus[0]['page_id'];page=page_map[pid];target=focus_pose(focus,*page['size'])
        new=not shots or shots[-1]['page_id']!=pid
        if new:
            if shots:shots[-1]['end']=cue['start']
            shots.append(dict(page_id=pid,start=cue['start'],end=cue['end'],moves=[],cues=[]))
        shot=shots[-1];shot['end']=cue['end'];local=cue['start']-shot['start']
        begin=max(0,local-(0 if beat['intent']=='discovery' else .22))
        if shot['moves']:begin=max(begin,shot['moves'][-1]['at']+shot['moves'][-1]['duration'])
        previous=sample(shot,begin);distance=math.hypot((target['x']-previous['x'])/1920,(target['y']-previous['y'])/1080)
        available=max(0,cue['end']-shot['start']-begin-.25)
        length=min(1.05 if distance>.4 else .65,available)
        easing={'dialogue':'power2.inOut','reaction':'power1.out','action':'power2.out','discovery':'power3.out','transition':'power2.inOut'}[beat['intent']]
        def move(a,dt,p,q,e):
            if dt>0:shot['moves'].append(dict(at=a,duration=dt,**{'from':dict(p),'to':dict(q)},ease=e,beat_id=beat['id']))
        if length>.12 and (distance>.035 or abs(target['z']-previous['z'])>.1):
            if not new and distance>.4 and length>.65:
                z=min(previous['z'],target['z'],1.5)
                def wide(p):return dict(z=z,x=max(-960*(z-1),min(960*(z-1),p['x']*z/p['z'])),y=max(-540*(z-1),min(540*(z-1),p['y']*z/p['z'])))
                context=wide(previous);destination=wide(target)
                move(begin,length*.25,previous,context,'power2.inOut')
                move(begin+length*.25,length*.45,context,destination,'power2.inOut')
                move(begin+length*.70,length*.30,destination,target,easing)
            else:move(begin,length,previous,target,easing)
        shot['cues'].append(dict(beat_id=beat['id'],start=cue['start'],end=cue['end'],intent=beat['intent'],source_ids=beat['focus_source_ids'],target=target))
    return shots

def ff_ease(t,name):
    if name=='power2.inOut':return f'if(lt({t},0.5),4*pow({t},3),1-pow(-2*{t}+2,3)/2)'
    exponent={'power1.out':2,'power2.out':3,'power3.out':4}.get(name)
    return f'1-pow(1-{t},{exponent})' if exponent else t

def ff_axis(shot,axis,fps=30):
    expr=str(shot.get('initial',dict(z=1,x=0,y=0))[axis])
    for move in shot['moves']:
        a=move['at']*fps;n=max(1,move['duration']*fps);t=f'max(0,min(1,(on-{a:.5f})/{n:.5f}))'
        u=ff_ease(t,move['ease']);p=move['from'][axis];q=move['to'][axis]
        expr=f'if(lt(on,{a:.5f}),{expr},if(lt(on,{a+n:.5f}),{p:.6f}+({q-p:.6f})*({u}),{q:.6f}))'
    return expr
