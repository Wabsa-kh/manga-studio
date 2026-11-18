"""Preset camera core: continuous immersed reframing, no wide re-entry waypoint.

Input is geometry and timed source IDs, not generated animation code. Panel geometry
can be separately reviewed; this module does not pretend text boxes are panel bounds.
"""
import math
from camera_engine import sample

PRESETS={
    'reading_glide':dict(min_move=1.6,max_move=2.8,drift=.012,zoom_drift=.012,ease='power2.inOut'),
    'quiet_exchange':dict(min_move=1.8,max_move=3.0,drift=.006,zoom_drift=.008,ease='power2.inOut'),
}

def validate_box(box):
    if len(box)!=4 or any(not math.isfinite(v) or not 0<=v<=1 for v in box) or box[2]<=0 or box[3]<=0 or box[0]+box[2]>1.00001 or box[1]+box[3]>1.00001:
        raise ValueError('Invalid normalized panel/art/source geometry')

def pose_for(ref,panel,page):
    width,height=page['size']
    if width<=0 or height<=0:raise ValueError('Invalid page dimensions')
    pw=width/height*1080;art=page['art_bounds']
    for box in [ref['region'],panel,art]:validate_box(box)
    # Cover the authored art rectangle, including a small safety margin. This floor
    # is independent of raster resolution and prevents a full-page overview.
    floor=max(1920/(pw*art[2]),1/art[3])*1.025
    zoom=max(floor,min(floor*1.35,1920/(pw*panel[2]*1.04),1/(panel[3]*1.04)))
    region=ref['region'];cx=region[0]+region[2]/2;cy=region[1]+region[3]/2
    # Blend toward the enclosing panel to keep faces and surrounding artwork.
    cx=.55*cx+.45*(panel[0]+panel[2]/2);cy=.55*cy+.45*(panel[1]+panel[3]/2)
    return bounded_pose(cx,cy,zoom,page)

def bounded_pose(cx,cy,zoom,page):
    width,height=page['size'];pw=width/height*1080;ax,ay,aw,ah=page['art_bounds']
    halfx=960/(pw*zoom);halfy=1/(2*zoom)
    cx=max(ax+halfx,min(ax+aw-halfx,cx));cy=max(ay+halfy,min(ay+ah-halfy,cy))
    return dict(z=zoom,x=zoom*(960-((1920-pw)/2+cx*pw)),y=zoom*(540-cy*1080))

def plan_smooth(beats,timings,item_map,page_map,layout,preset='reading_glide'):
    policy=PRESETS[preset];times={r['beat_id']:r for r in timings};shots=[]
    for beat in beats:
        cue=times[beat['id']];pid=item_map[beat['primary_source_id']]['page_id'];page=page_map[pid]
        refs=[item_map[i] for i in beat['focus_source_ids']]
        if any(i['page_id']!=pid for i in refs):raise ValueError('Cue spans different focus pages')
        targets=[]
        # Preserve supplied source reading order, never sort all balloons by x/y.
        for ref in sorted(refs,key=lambda i:i['order']):
            panel_id=layout[pid]['item_panels'][ref['id']];panel=layout[pid]['panels'][panel_id]
            target=pose_for(ref,panel,page)
            if not targets or max(abs(target[k]-targets[-1][k])/(1920 if k=='x' else 1080 if k=='y' else 1) for k in target)>.025:targets.append(target)
        if not targets:raise ValueError('No panel-linked camera target')
        new=not shots or shots[-1]['page_id']!=pid
        if new:
            if shots:shots[-1]['end']=cue['start']
            shots.append(dict(page_id=pid,start=cue['start'],end=cue['end'],initial=targets[0],moves=[],cues=[],preset=preset))
        shot=shots[-1];shot['end']=cue['end'];start=cue['start']-shot['start'];duration=cue['end']-cue['start']
        if duration<=0 or start<0:raise ValueError('Invalid or reversed cue timing')
        available=max(.1,duration-.08);previous=sample(shot,start)
        def move(at,length,target,role):
            nonlocal previous
            if length>.02:
                shot['moves'].append(dict(at=at,duration=length,**{'from':dict(previous),'to':dict(target)},ease=policy['ease'],beat_id=beat['id'],role=role));previous=target
        # Direct simultaneous pan and scale; no zoom-out/transit/zoom-in sequence.
        distance=math.hypot((targets[0]['x']-previous['x'])/1920,(targets[0]['y']-previous['y'])/1080)
        entry=0 if new else min(available*.65,max(policy['min_move'],min(policy['max_move'],1.6+distance)))
        move(start,entry,targets[0],'direct_glide')
        remaining=available-entry
        if len(targets)>1:
            segment=remaining/(len(targets)-1)
            for index,target in enumerate(targets[1:]):move(start+entry+index*segment,segment,target,'reading_path')
        elif remaining>.25:
            z=previous['z']*(1+policy['zoom_drift']);pw=page['size'][0]/page['size'][1]*1080
            cx=.5-previous['x']/(previous['z']*pw);cy=.5-previous['y']/(previous['z']*1080)
            direction=-1 if len(shot['cues'])%2==0 else 1
            drift=bounded_pose(cx+direction*policy['drift'],cy+policy['drift']*.35,z,page)
            move(start+entry,remaining,drift,'subtle_drift')
        shot['cues'].append(dict(beat_id=beat['id'],start=cue['start'],end=cue['end'],intent=beat['intent'],source_ids=beat['focus_source_ids'],target=targets[-1]))
    return shots
