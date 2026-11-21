"""Fractional-pixel page projection. Each frame is resampled from the original."""
import argparse,math,subprocess,time
from pathlib import Path
import numpy as np
from PIL import Image
from .core import read,save,sha,digest,event,Attention
from .camera_v11 import plan,sample,ease
from .media import ff,listing

def paper_color(image):
 a=np.asarray(image.convert('RGB'));h,w=a.shape[:2];border=np.concatenate([a[:max(1,h//80)].reshape(-1,3),a[-max(1,h//80):].reshape(-1,3),a[:,:max(1,w//80)].reshape(-1,3),a[:,-max(1,w//80):].reshape(-1,3)])
 # Bright border pixels provide the paper color, without averaging dark ink
 # into gray. The median stays robust against scanner noise and page numbers.
 bright=border[np.mean(border,axis=1)>220];return np.median(bright if len(bright) else border,axis=0).astype(np.uint8)

def matrix(size,pose,width,height,yaw=0):
 sw,sh=size;scale=1080/sh;pw=sw*scale;z=pose['z'];x=pose['x'];y=pose['y']
 affine=np.array([[z*scale,0,960*(1-z)+z*(1920-pw)/2+x],[0,z*scale,540*(1-z)+y],[0,0,1]],dtype=np.float64)
 output=np.diag([width/1920,height/1080,1.])
 angle=math.radians(yaw);f=width*1.8;center=np.array([[1,0,width/2],[0,1,height/2],[0,0,1.]])
 rotate=np.array([[math.cos(angle),0,0],[0,1,0],[math.sin(angle)/f,0,1.]])
 return center@rotate@np.linalg.inv(center)@output@affine

class Frames:
 def __init__(self,data):
  import cv2
  self.cv=cv2;cv2.setNumThreads(4);self.data=data;self.cfg=data['config'];self.cache={}
 def source(self,shot):
  path=shot['source_path']
  if path not in self.cache:
   if sha(path)!=shot['source_sha256']:raise Attention('Source changed before video rendering')
   with Image.open(path) as im:self.cache[path]=(np.asarray(im.convert('RGB')),paper_color(im) if self.cfg['background']=='sample_paper' else np.array(self.cfg['background']))
  return self.cache[path]
 def image(self,shot,t):
  img,bg=self.source(shot);cfg=self.cfg
  interpolation=self.cv.INTER_LANCZOS4 if cfg['interpolation']=='lanczos' else self.cv.INTER_CUBIC
  moving=any(m['at']<t<m['at']+m['duration'] for m in shot['moves']);delta=cfg['motion_blur']/cfg['fps']/2
  samples=[(t-delta,.25),(t,.5),(t+delta,.25)] if moving and delta>0 else [(t,1.)];result=None
  for moment,weight in samples:
   moment=max(0,min(shot['duration'],moment));p=sample(shot,moment,cfg);u=moment/max(.001,shot['duration']);yaw=cfg['yaw_degrees']*math.sin(math.pi*(u-.5));transform=matrix((img.shape[1],img.shape[0]),p,cfg['width'],cfg['height'],yaw)
   frame=self.cv.warpPerspective(img,transform,(cfg['width'],cfg['height']),flags=interpolation,borderMode=self.cv.BORDER_CONSTANT,borderValue=tuple(int(v) for v in bg))
   if len(samples)==1:return frame
   if result is None:result=frame.astype(np.float32)*weight
   else:result+=frame*weight
  return np.clip(result,0,255).astype(np.uint8)
 def frame(self,t):
  shots=self.data['shots'];i=next((i for i,s in enumerate(shots) if s['start']<=t<s['end']),len(shots)-1);s=shots[i];local=t-s['start'];front=self.image(s,local);transition=min(self.cfg['transition_seconds'],s['duration']/5);remaining=s['end']-t
  if i+1<len(shots) and remaining<transition:
   progress=ease(1-remaining/transition);back=self.image(shots[i+1],0)
   if s['transition'] in ['wipe_right','wipe_left']:
    # A feathered paper wipe, rather than a long double-exposure of two pages.
    w=self.cfg['width'];edge=progress*(w+64)-32;mask=np.clip((edge-np.arange(w)+32)/64,0,1)[None,:,None].astype(np.float32)
    if s['transition']=='wipe_left':mask=mask[:,::-1]
    front=(front*(1-mask)+back*mask).astype(np.uint8)
   else:front=self.cv.addWeighted(front,1-progress,back,progress,0)
  # Keep at most two original pages resident during long unattended renders.
  active={s['source_path']}
  if i+1<len(shots):active.add(shots[i+1]['source_path'])
  self.cache={k:v for k,v in self.cache.items() if k in active};return front

def render(data,audio,target):
 target=Path(target);target.mkdir(parents=True,exist_ok=True);cfg=data['config'];frames=math.ceil(data['duration']*cfg['fps']);duration=frames/cfg['fps'];portable={**data,'shots':[{k:v for k,v in s.items() if k!='source_path'} for s in data['shots']]};signature=digest(dict(plan=portable,audio_sha256=sha(audio),engine='cv-subpixel-v11-2'));done=read(target/'complete.json');final=target/'video.mp4'
 if done and done.get('signature')==signature and final.exists() and sha(final)==done['sha256']:return done
 source=Frames(data);start=time.monotonic();silent=target/'picture.partial.mp4';error=target/'encode-error.log';save(target/'camera-plan.json',data)
 command=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f"{cfg['width']}x{cfg['height']}",'-r',str(cfg['fps']),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf',str(cfg['crf']),'-pix_fmt','yuv420p','-threads','4',str(silent)]
 with error.open('wb') as log:
  process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
  try:
   for i in range(frames):
    process.stdin.write(source.frame(i/cfg['fps']).tobytes())
    if i%(cfg['fps']*2)==0:save(target/'render-progress.json',dict(frame=i,total_frames=frames,percent=100*i/frames,seconds=round(time.monotonic()-start,1)))
   process.stdin.close();code=process.wait()
   if code:raise RuntimeError('Video encoder failed; see encode-error.log')
  except BaseException:
   process.kill();process.wait();raise
 ff(['-i',silent,'-i',audio,'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','160k','-af','apad','-t',duration,'-movflags','+faststart',final])
 # Fully decode the output and independently verify actual frame count.
 ff(['-i',final,'-f','null','-']);info=__import__('json').loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(final)]));v=next(s for s in info['streams'] if s['codec_type']=='video')
 if int(v['nb_frames'])!=frames:raise Attention('Subpixel render frame count mismatch')
 if (v['width'],v['height'])!=(cfg['width'],cfg['height']):raise Attention('Subpixel render dimensions mismatch')
 result=dict(path=str(final.resolve()),sha256=sha(final),signature=signature,duration=duration,frames=frames,fps=cfg['fps'],width=v['width'],height=v['height'],render_seconds=round(time.monotonic()-start,2),technical_qa=True,publication_approved=False);save(target/'complete.json',result);save(target/'render-progress.json',dict(frame=frames,total_frames=frames,percent=100,complete=True))
 if silent.exists():silent.unlink()
 return result

def prepare(root,unit_id,overrides=None,seconds=None):
 root=Path(root);unit=next(u for u in read(root/'inventory.json')['units'] if u['id']==unit_id);folder=root/'units'/unit_id;draft=read(folder/'draft.json');timing=read(folder/'speech-timing.json');index=read(folder/'source-ledger.json')['index'];pages={p['page_id']:p for p in unit['pages'] if p['page_id'] not in draft.get('omitted_page_ids',[])};layouts={pid:read(root/'visual-layout'/(pid+'.json'),{}) for pid in pages}
 for pid,layout in layouts.items():
  if layout and layout.get('source_sha256')!=pages[pid]['sha256']:raise Attention('Visual anchors belong to a different original page')
 cfg=read(root/'config.json',{});upscaled=cfg.get('upscaled_source')
 if upscaled:
  from .upscale import verify
  original_root=Path(cfg['source']).resolve()
  for pid,page in pages.items():
   out=Path(upscaled)/Path(page['path']).resolve().relative_to(original_root).with_suffix('.png');metadata=read(out.with_suffix('.upscale.json'));actual=verify(page['path'],out)
   if not actual or actual!=metadata:raise Attention('Missing or invalid upscale for '+pid)
   pages[pid]={**page,'path':str(out),'sha256':actual['output_sha256'],'size':actual['size'],'original_sha256':page['sha256']}
 page_panels={}
 for pid in {beat['page_id'] for beat in draft['beats']}:
  reading=read(root/'pages'/(pid+'.json'),{})
  source_pages=reading.get('reading',{}).get('pages',[])
  if source_pages:page_panels[pid]=[panel['region'] for panel in source_pages[0]['panels']]
 focus=read(folder/'focus-timing.json',{});data=plan(draft['beats'],timing['cues'],index,pages,layouts,overrides,focus.get('cues',{}),page_panels)
 if seconds:
  data['duration']=min(data['duration'],seconds);data['shots']=[s for s in data['shots'] if s['start']<data['duration']]
  data['shots'][-1]['end']=data['duration'];data['shots'][-1]['duration']=data['duration']-data['shots'][-1]['start']
 data['visual_layout_pages']=sum(bool(v) for v in layouts.values());data['spoken_focus_beats']=sum(bool(v) for v in focus.get('cues',{}).values());return data,folder/'narration.wav'

def main():
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--unit',default='unit-0001');p.add_argument('--target',required=True);p.add_argument('--seconds',type=float);p.add_argument('--config');a=p.parse_args();cfg=read(a.config,{}) if a.config else {};data,audio=prepare(a.job,a.unit,cfg,a.seconds);print(render(data,audio,a.target),flush=True)
if __name__=='__main__':main()
