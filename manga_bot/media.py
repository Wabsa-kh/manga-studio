"""Measured speech, source-linked cameras and reusable part assembly."""
import math,json,subprocess,wave,shutil,xml.etree.ElementTree as ET
from pathlib import Path
from .core import read,save,sha,digest,event,Attention,Pending
from camera_engine import align_beats
from smooth_camera import plan_smooth
import series_av_v9 as av

POLICY='generic-bot-v10-immersed-207'
_FFMAJOR=None
def ff(args):
 global _FFMAJOR
 if _FFMAJOR is None:
  import re
  version=subprocess.check_output(['ffmpeg','-version'],text=True);_FFMAJOR=int(re.search(r'ffmpeg version (\d+)',version)[1])
 args=list(map(str,args))
 if _FFMAJOR<8:args=[{'-/filter_complex':'-filter_complex_script','-/filter:v':'-filter_script:v'}.get(a,a) for a in args]
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*args],check=True,capture_output=True)
av.ff=ff

def visual_checks(target):
 from PIL import Image,ImageStat
 rows=read(target/'qa-samples.json',[]);groups={};results=[]
 for row in rows:
  with Image.open(row['path']) as image:
   gray=image.convert('L').resize((160,90));hist=gray.histogram();spread=ImageStat.Stat(gray).stddev[0];flat=spread<1.5 or max(sum(hist[:3]),sum(hist[253:]))/14400>.995
  groups.setdefault(row['page_id'],[]).append(flat);results.append(dict(page_id=row['page_id'],sample=row['label'],flat_frame=flat,contrast_stddev=spread))
 blank=[pid for pid,flags in groups.items() if flags and all(flags)];save(target/'visual-checks.json',dict(samples=results,suspected_blank_shots=blank))
 if blank:raise Attention('All entry/middle/exit samples are blank for '+', '.join(blank))

def listing(path,files):
 # ffconcat uses single quote escaping, including paths containing apostrophes.
 path.write_text('\n'.join("file '"+Path(p).resolve().as_posix().replace("'","'\\''")+"'" for p in files),encoding='utf-8')

def transcribe(audio,target,beats,names):
 import numpy as np
 from faster_whisper import WhisperModel
 signature=digest({'audio':sha(audio),'beats':beats,'names':names,'version':2});cache=target/'speech-timing.json';old=read(cache)
 if old and old.get('signature')==signature:return old
 wav=target/'timing.wav';ff(['-i',audio,'-ac','1','-ar','16000',wav])
 with wave.open(str(wav)) as f:signal=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16).astype(np.float32)/32768
 for name in ['tiny.en','base.en']:
  model=WhisperModel(name,device='cpu',compute_type='int8',cpu_threads=4,download_root=str(Path('video-preview-v5/local-model-cache').resolve()))
  segments,_=model.transcribe(signal,language='en',word_timestamps=True,beam_size=5,vad_filter=False,initial_prompt='. '.join(names)[:1000])
  words=[dict(word=w.word,start=w.start,end=w.end) for s in segments for w in s.words]
  try:cues,ratio=align_beats(beats,words,av.duration(audio));break
  except ValueError:
   if name=='base.en':raise Attention('Speech alignment failed after two local models')
 result=dict(signature=signature,method='Local Whisper '+name,words=words,cues=cues,alignment_ratio=ratio);save(cache,result);return result

def speech(api,root,draft,target):
 prepared=read(target/'audio-prepared.json')
 if prepared:
  path=Path(prepared['path'])
  if hasattr(api,'assets'):api.assets.ensure_path(path)
  if prepared['text_sha256']!=draft['text_sha256'] or not path.exists() or sha(path)!=prepared['audio_sha256']:raise Attention('Prepared speech does not match the frozen script/audio')
  return path
 from tts_jobs import chunks
 frozen=dict(text_sha256=draft['text_sha256'],chunks=chunks(draft['beats'],1400));path=target/'audio-scope.json';old=read(path)
 if old and old!=frozen:raise Attention('Frozen speech scope changed')
 save(path,frozen);files=[]
 for i,chunk in enumerate(frozen['chunks']):
  text=' '.join(b['text'] for b in chunk) if isinstance(chunk,list) else chunk['text']
  folder=target/'speech'/f'{i:03}';api.tts(text,folder);files.append(folder/'voice.wav')
 concat=target/'speech.txt';listing(concat,files);audio=target/'narration.wav';note=target/'audio.json';signature=digest({'sources':[sha(p) for p in files],'text':draft['text_sha256'],'policy':POLICY});old=read(note)
 if not audio.exists() or not old or old['signature']!=signature or old['audio_sha256']!=sha(audio):
  duration=sum(av.duration(p) for p in files);tempo=max(.8,min(1.15,207/(draft['words']/duration*60)))
  ff(['-f','concat','-safe','0','-i',concat,'-af',f'atempo={tempo:.8f},loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-ac','1',audio]);save(note,dict(signature=signature,audio_sha256=sha(audio),duration=av.duration(audio),words=draft['words'],effective_wpm=draft['words']/av.duration(audio)*60))
 return audio

def unit_video(api,root,unit,draft):
 cfg=read(root/'config.json',{})
 if cfg.get('render',{}).get('engine')=='subpixel_v11':return subpixel_video(api,root,unit,draft,cfg)
 return legacy_unit_video(api,root,unit,draft)

def render_with_read_ahead(api,root,data,audio,target,render):
 """Use spare model capacity while the CPU renders a verified unit."""
 if not hasattr(api,'assets'):return render(data,audio,target)
 from concurrent.futures import ThreadPoolExecutor
 from .stages import read_batch
 cfg=read(root/'config.json',{})
 inventory=read(root/'inventory.json',{})
 pages=[page for page in inventory.get('pages',[]) if not (root/'pages'/(page['page_id']+'.json')).exists()]
 batch=pages[:cfg.get('reader_batch_pages',2)]
 if not batch:return render(data,audio,target)
 with ThreadPoolExecutor(max_workers=1) as pool:
  reader=pool.submit(read_batch,api,root,batch)
  result=render(data,audio,target)
  try:reader.result()
  except (Pending,Attention) as exc:event(root,'render_read_ahead_deferred',reason=type(exc).__name__)
 return result

def subpixel_video(api,root,unit,draft,cfg):
 for page in unit['pages']:
  if sha(page['path'])!=page['sha256']:raise Attention('Original page changed after inventory: '+page['page_id'])
 from .visual_layout import capture
 from .focus_timing import make
 from .render_v11 import prepare,render
 from .visual_review import inspect,editable
 import os
 target=root/'units'/unit['id'];audio=speech(api,root,draft,target);names=list(dict.fromkeys(e['name'] for e in draft['entities'] if e['name']));transcribe(audio,target,draft['beats'],names);visible={b['page_id'] for b in draft['beats']};pages=[p for p in unit['pages'] if p['page_id'] in visible]
 for i in range(0,len(pages),2):capture(api,root,pages[i:i+2])
 if cfg.get('upscaled_source') and hasattr(api,'assets'):
  for page in unit['pages']:
   out=Path(cfg['upscaled_source'])/Path(page['path']).resolve().relative_to(Path(cfg['source']).resolve()).with_suffix('.png');api.assets.ensure_path(out)
 make(api,root,unit['id']);overrides={k:v for k,v in cfg['render'].items() if k!='engine'};data,audio=prepare(root,unit['id'],overrides);result=render_with_read_ahead(api,root,data,audio,target,render)
 if not (target/'qa-manifest.json').exists() or read(target/'qa-manifest.json').get('video_sha256')!=result['sha256']:inspect(target)
 editable(target,data,audio);alias=target/'chapter.mp4'
 if alias.exists() and sha(alias)!=result['sha256']:alias.unlink()
 if not alias.exists():
  try:os.link(target/'video.mp4',alias)
  except OSError:shutil.copy2(target/'video.mp4',alias)
 info={**result,'words':draft['words'],'engine':'subpixel_v11'};save(target/'video.json',info)
 if cfg.get('upscaled_source') and hasattr(api,'assets'):
  for page in unit['pages']:
   out=Path(cfg['upscaled_source'])/Path(page['path']).resolve().relative_to(Path(cfg['source']).resolve()).with_suffix('.png');api.assets.evict_path(out)
 return info

def legacy_unit_video(api,root,unit,draft):
 for page in unit['pages']:
  if sha(page['path'])!=page['sha256']:raise Attention('Original page changed after the inventory was frozen: '+page['page_id'])
 target=root/'units'/unit['id'];audio=speech(api,root,draft,target)
 index=read(target/'source-ledger.json')['index'];source={p['page_id']:p for p in unit['pages']};names=list(dict.fromkeys(e['name'] for e in draft['entities'] if e['name']))
 timing=transcribe(audio,target,draft['beats'],names);layout={};pages={}
 for pid,p in source.items():
  pages[pid]={**p,'art_bounds':[.025,.01,.95,.98]};layout[pid]=dict(panels={},item_panels={})
 for ident,item in index.items():
  pid=item['page_id'];key='panel-'+digest(item['panel'])[:10];layout[pid]['panels'][key]=item['panel'];layout[pid]['item_panels'][ident]=key
 beats=[]
 for b in draft['beats']:
  refs=[r for r in b['source_ids'] if index[r]['page_id']==b['page_id']][:5];beats.append({**b,'focus_source_ids':refs,'intent':'dialogue' if index[b['primary_source_id']]['kind']=='speech' else 'transition'})
 shots=plan_smooth(beats,timing['cues'],index,pages,layout);frames=math.ceil(av.duration(audio)*av.FPS)
 for i,s in enumerate(shots):
  s['start_frame']=round(s['start']*av.FPS);s['end_frame']=round(s['end']*av.FPS) if i<len(shots)-1 else frames;s['start']=s['start_frame']/av.FPS;s['end']=s['end_frame']/av.FPS;s['duration']=s['end']-s['start'];s['source_path']=source[s['page_id']]['path'];s['source_sha256']=source[s['page_id']]['sha256'];s['audio_sha256']=sha(audio)
 data=dict(fps=av.FPS,width=av.WIDTH,height=av.HEIGHT,duration=frames/av.FPS,shots=shots,alignment_ratio=timing['alignment_ratio'],manual_prose_edits=False,publication_approved=False,policy=POLICY)
 save(target/'camera-plan.json',data);signature=digest(data);done=read(target/'video.json');video=target/'chapter.mp4'
 if not done or done.get('signature')!=signature or not video.exists() or done.get('sha256')!=sha(video):
  av.render(draft,target,audio,data)
  if not av.qa_current(target,data):av.qa_chapter(target,data)
  visual_checks(target)
  # Decode the complete stream; do not approve based only on container metadata.
  ff(['-i',video,'-f','null','-']);info=av.probe(video);stream=next(s for s in info['streams'] if s['codec_type']=='video')
  if int(stream.get('nb_frames',0))!=frames:raise Attention('Rendered frame count differs from speech timeline')
  save(target/'video.json',dict(signature=signature,sha256=sha(video),duration=data['duration'],path=str(video),words=draft['words'],technical_qa=True,publication_approved=False));event(root,'unit_video_complete',unit=unit['id'],duration=data['duration'],path=str(video),manual_content_edits=0)
 # Every intermediate preview also has an editable timeline, so review does
 # not depend on waiting for an entire hour-long part to finish.
 visual_checks(target)
 padded=target/'narration-timeline.wav'
 if not padded.exists():ff(['-i',audio,'-af','apad','-t',data['duration'],'-ar','48000','-ac','1','-c:a','pcm_s16le',padded])
 shotcut(target,[dict(id=unit['id'],folder=str(target),chapters=unit['chapters'])])
 (target/'media-credits.txt').write_text('User-provided source manga pages. Gemini Flash TTS / Charon narration. No added music. Evaluation preview. Original image hashes: job inventory.json.\n',encoding='utf-8')
 return read(target/'video.json')

def shotcut(target,units):
 # Source-linked baked camera clips are editable; narration is a separate track.
 root=ET.Element('mlt',producer='tractor',version='7.24.0');profile=ET.SubElement(root,'profile',frame_rate_num='24',frame_rate_den='1',width='1280',height='720',progressive='1',sample_aspect_num='1',sample_aspect_den='1',display_aspect_num='16',display_aspect_den='9',colorspace='709')
 v=ET.SubElement(root,'playlist',id='video');a=ET.SubElement(root,'playlist',id='audio');markers=[];offset=0
 for unit in units:
  folder=Path(unit['folder']);plan=read(folder/'camera-plan.json');uid=unit['id'];frames=round(plan['duration']*24)
  for i,s in enumerate(plan['shots']):
   n=s['end_frame']-s['start_frame']
   if n<=0:continue
   ident=f'{uid}-clip-{i}';p=ET.SubElement(root,'producer',id=ident);ET.SubElement(p,'property',name='resource').text=str((folder/'clips'/f'{i:03}.mp4').resolve());ET.SubElement(p,'property',name='mlt_service').text='avformat';ET.SubElement(v,'entry',producer=ident,**{'in':'0','out':str(n-1)})
  p=ET.SubElement(root,'producer',id=uid+'-audio');ET.SubElement(p,'property',name='resource').text=str((folder/'narration-timeline.wav').resolve());ET.SubElement(p,'property',name='mlt_service').text='avformat';ET.SubElement(p,'property',name='video_index').text='-1';ET.SubElement(a,'entry',producer=uid+'-audio',**{'in':'0','out':str(frames-1)});markers.append({'start':offset,'end':offset,'text':'Chapters '+', '.join(unit['chapters'])});offset+=frames
 tractor=ET.SubElement(root,'tractor',id='tractor',shotcut='1',**{'out':str(offset-1)});ET.SubElement(tractor,'property',name='shotcut').text='1';ET.SubElement(tractor,'property',name='shotcut:markers').text=json.dumps(markers);ET.SubElement(tractor,'track',producer='audio',hide='video');ET.SubElement(tractor,'track',producer='video',hide='audio')
 # MLT producer definitions must precede playlist references.
 root[:]=[profile]+[e for e in root if e.tag=='producer']+[v,a,tractor]
 ET.indent(root);ET.ElementTree(root).write(target/'editable.mlt',encoding='utf-8',xml_declaration=True)

def assemble(root,part):
 target=root/'parts'/part['id'];target.mkdir(parents=True,exist_ok=True);units=part['units'];video=target/'video.mp4';signature=digest([read(root/'units'/u['id']/'video.json')['sha256'] for u in units]);done=read(target/'complete.json')
 if done and video.exists() and done.get('signature')==signature and done.get('sha256')==sha(video):return done
 clips=[];audios=[];offset=0;metadata=[';FFMETADATA1'];markers=[]
 for u in units:
  folder=root/'units'/u['id'];info=read(folder/'video.json');clips.append(folder/'chapter.mp4');padded=folder/'narration-timeline.wav';ff(['-i',folder/'narration.wav','-af','apad','-t',info['duration'],'-ar','48000','-ac','1','-c:a','pcm_s16le',padded]);audios.append(padded)
  metadata+=['[CHAPTER]','TIMEBASE=1/1000',f'START={round(offset*1000)}',f'END={round((offset+info["duration"])*1000)}','title=Chapters '+', '.join(u['chapters'])];markers.append(dict(unit=u['id'],start=offset,duration=info['duration']));offset+=info['duration']
 listing(target/'video.txt',clips);listing(target/'audio.txt',audios);(target/'chapters.txt').write_text('\n'.join(metadata),encoding='utf-8');ff(['-f','concat','-safe','0','-i',target/'video.txt','-f','concat','-safe','0','-i',target/'audio.txt','-f','ffmetadata','-i',target/'chapters.txt','-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2','-c:v','copy','-c:a','aac','-b:a','160k','-t',offset,'-movflags','+faststart',video]);ff(['-i',video,'-f','null','-'])
 modern=read(root/'config.json').get('render',{}).get('engine')=='subpixel_v11'
 if modern:
  from .visual_review import editable
  combined=[];offset_frames=0;cfg=None
  for u in units:
   plan=read(root/'units'/u['id']/'camera-plan.json');cfg=plan['config'];fps=cfg['fps'];length=read(root/'units'/u['id']/'video.json')['frames']
   for s in plan['shots']:combined.append({**s,'start':s['start']+offset_frames/fps,'end':s['end']+offset_frames/fps})
   offset_frames+=length
  combined_plan=dict(config=cfg,shots=combined,duration=offset);save(target/'camera-plan.json',combined_plan);ff(['-f','concat','-safe','0','-i',target/'audio.txt','-ar','48000','-ac','1',target/'narration.wav']);editable(target,combined_plan,target/'narration.wav',frames=offset_frames)
 else:shotcut(target,[{**u,'folder':str(root/'units'/u['id'])} for u in units])
 save(target/'markers.json',markers)
 from PIL import Image,ImageDraw
 samples=[]
 for u in units:
  rows=read(root/'units'/u['id']/'qa-samples.json',[]);middle=[r for r in rows if r['label']=='mid']
  if middle:
   for i in sorted(set([0,len(middle)//2,len(middle)-1])):samples.append((u['id'],middle[i]))
 if samples:
  sheet=Image.new('RGB',(960,205*math.ceil(len(samples)/3)),(24,24,24));draw=ImageDraw.Draw(sheet)
  for i,(uid,r) in enumerate(samples):
   with Image.open(r['path']) as im:sheet.paste(im.resize((320,180)),(i%3*320,i//3*205+25))
   draw.text((i%3*320+5,i//3*205+5),uid+' '+r['page_id'],fill='white')
  sheet.save(target/'contact-sheet.jpg',quality=87)
 (target/'media-credits.txt').write_text('Source: '+read(root/'config.json')['title']+'; user-provided manga pages.\nNarration: Google Gemini 3.8 Flash TTS, Charon.\nNo added music. Evaluation cut; no publication approval.\n',encoding='utf-8')
 result=dict(signature=signature,sha256=sha(video),path=str(video),duration=offset,minutes=offset/60,units=[u['id'] for u in units],technical_qa=True,publication_approved=False)
 if modern:result.update(frames=offset_frames,fps=cfg['fps'])
 save(target/'complete.json',result);event(root,'part_complete',part=part['id'],**result);return result
