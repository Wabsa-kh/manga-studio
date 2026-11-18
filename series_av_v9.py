"""Measured speech -> source-linked immersed camera -> per-chapter and full MP4."""
import argparse,hashlib,json,math,os,subprocess,time,wave,shutil
from pathlib import Path
from PIL import Image,ImageDraw
from storybench import inventory,DEFAULT_SOURCE,dump
from series_video_v9 import OUT
from series_inventory import chapter_sort
from tts_jobs import synthesize_chunks
from job_store import JobStore
from camera_engine import align_beats,ff_axis,sample
from smooth_camera import plan_smooth
from series_names_v9 import delivery_draft

FPS=24;WIDTH=1280;HEIGHT=720;POLICY='v9-immersed-207wpm-v2'
def ff(args):subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True,capture_output=True)
def duration(path):
 with wave.open(str(path)) as w:return w.getnframes()/w.getframerate()
def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)]))

def chapter_audio(draft,target):
 os.environ['MANGA_DAILY_REQUESTS']='100';os.environ['MANGA_DAILY_TOKEN_RESERVATION']='2000000'
 prepared=target/'audio-prepared.json'
 if prepared.exists():
  p=json.loads(prepared.read_text(encoding='utf-8'))
  if p['text_sha256']!=draft['text_sha256'] or hashlib.sha256(Path(p['path']).read_bytes()).hexdigest()!=p['audio_sha256']:raise ValueError('Prepared audio does not match the current narration')
  manifest=[dict(path=p['path'],digest=p['audio_sha256'],duration=p['duration'],model=p['model'])]
 else:manifest=synthesize_chunks(draft,target/'audio',max_words=420,store=JobStore(OUT/'audio-budget.sqlite'),evaluation=True)
 listing=target/'audio-concat.txt';listing.write_text('\n'.join("file '"+Path(r['path']).as_posix()+"'" for r in manifest),encoding='utf-8')
 final=target/'narration.wav';note=target/'narration-source.json';signature=hashlib.sha256(json.dumps(dict(chunks=[r['digest'] for r in manifest],policy=POLICY)).encode()).hexdigest()
 if not final.exists() or not note.exists() or json.loads(note.read_text())['signature']!=signature:
  raw_duration=sum(r['duration'] for r in manifest);raw_wpm=draft['words']/raw_duration*60;tempo=max(.8,min(1.15,207/raw_wpm))
  ff(['-f','concat','-safe','0','-i',listing,'-af',f'atempo={tempo:.8f},loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-ac','1',final]);dump(note,dict(signature=signature,text_sha256=draft['text_sha256'],model=manifest[0]['model'],voice='Charon',raw_words_per_minute=raw_wpm,atempo=tempo,effective_words_per_minute=draft['words']/duration(final)*60,policy=POLICY))
 return final

def timing(draft,target,audio):
 import numpy as np
 from faster_whisper import WhisperModel
 digest=hashlib.sha256(audio.read_bytes()).hexdigest();path=target/'speech-timing.json'
 if path.exists() and json.loads(path.read_text())['audio_sha256']==digest:return json.loads(path.read_text())
 wav=target/'timing.wav';ff(['-i',audio,'-ac','1','-ar','16000',wav])
 with wave.open(str(wav)) as f:signal=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16).astype(np.float32)/32768
 model=WhisperModel('tiny.en',device='cpu',compute_type='int8',cpu_threads=4,download_root=str(Path('video-preview-v5/local-model-cache').resolve()))
 rows,_=model.transcribe(signal,language='en',word_timestamps=True,beam_size=5,vad_filter=False,initial_prompt='Yuu Satou. Stella Foddo. Hugg Pocho. Reemu. Resser. Magic Eye of Another World. HP and MP.')
 words=[dict(word=w.word,start=w.start,end=w.end) for segment in rows for w in segment.words]
 cues,ratio=align_beats(draft['beats'],words,duration(audio),{'yuu':'you','hugg':'hug','satou':'sato'})
 result=dict(audio_sha256=digest,method='Local Whisper tiny.en approximate word alignment',words=words,cues=cues,alignment_ratio=ratio);dump(path,result);return result

def plan(draft,target,audio):
 source={p['page_id']:p for p in inventory(Path(DEFAULT_SOURCE),['all'])};index=json.loads((target/'source-ledger.json').read_text(encoding='utf-8'))['index'];speech=timing(draft,target,audio);layout={};pages={}
 for pid,p in source.items():
  if not any(i['page_id']==pid for i in index.values()):continue
  with Image.open(p['path']) as im:size=list(im.size)
  pages[pid]={**p,'size':size,'art_bounds':[.025,.01,.95,.98]};layout[pid]=dict(panels={},item_panels={})
 for ident,item in index.items():
  pid=item['page_id'];key='panel-'+hashlib.sha256(json.dumps(item['panel']).encode()).hexdigest()[:10];layout[pid]['panels'][key]=item['panel'];layout[pid]['item_panels'][ident]=key
 beats=[]
 for b in draft['beats']:
  refs=[r for r in b['source_ids'] if index[r]['page_id']==b['page_id']][:5]
  beats.append({**b,'focus_source_ids':refs,'intent':'dialogue' if index[b['primary_source_id']]['kind']=='speech' else 'transition'})
 shots=plan_smooth(beats,speech['cues'],index,pages,layout)
 frames=math.ceil(duration(audio)*FPS)
 for i,s in enumerate(shots):
  s['start_frame']=round(s['start']*FPS);s['end_frame']=round(s['end']*FPS) if i<len(shots)-1 else frames;s['start']=s['start_frame']/FPS;s['end']=s['end_frame']/FPS;s['duration']=s['end']-s['start'];s['source_path']=source[s['page_id']]['path']
 result=dict(fps=FPS,width=WIDTH,height=HEIGHT,duration=frames/FPS,shots=shots,alignment_ratio=speech['alignment_ratio'],manual_prose_edits=False,publication_approved=False,policy=POLICY)
 dump(target/'camera-plan.json',result);return result

def camera_still(path,pose,out):
 # Same geometric viewport as the FFmpeg zoompan, directly from intact source.
 with Image.open(path).convert('RGB') as im:
  width,height=im.size;pw=width/height*1080;cx=.5-pose['x']/(pose['z']*pw);cy=.5-pose['y']/(pose['z']*1080);vw=1920/(pose['z']*pw)*width;vh=height/pose['z'];box=(cx*width-vw/2,cy*height-vh/2,cx*width+vw/2,cy*height+vh/2)
  im.crop(box).resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS).save(out)

def render(draft,target,audio,data):
 clips=target/'clips';clips.mkdir(exist_ok=True);outputs=[]
 for i,s in enumerate(data['shots']):
  output=clips/f'{i:03}.mp4';signature=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest();meta=output.with_suffix('.json');frames=s['end_frame']-s['start_frame']
  if frames<=0:continue
  if not output.exists() or not meta.exists() or json.loads(meta.read_text()).get('signature')!=signature:
   z,x,y=[ff_axis(s,k,FPS) for k in ['z','x','y']];base=f"scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:white,zoompan=z='{z}':x='iw/2-iw/(2*zoom)-({x})/zoom':y='ih/2-ih/(2*zoom)-({y})/zoom':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1"
   args=['-i',s['source_path']]
   if i+1<len(data['shots']) and s['duration']>.5:
    nextshot=data['shots'][i+1];still=clips/f'{i:03}-next.jpg';camera_still(nextshot['source_path'],nextshot['initial'],still)
    args+=['-loop','1','-framerate',FPS,'-i',still];fade=min(.16,s['duration']/5)
    vf=f"[0:v]{base},format=rgba,fade=t=out:st={s['duration']-fade}:d={fade}:alpha=1[front];[1:v]format=rgba[back];[back][front]overlay=shortest=1,format=yuv420p[out]"
    args+=['-/filter_complex',clips/f'{i:03}.filter','-map','[out]'];(clips/f'{i:03}.filter').write_text(vf,encoding='utf-8')
   else:
    (clips/f'{i:03}.filter').write_text(base+',format=yuv420p',encoding='utf-8');args+=['-/filter:v',clips/f'{i:03}.filter']
   ff([*args,'-frames:v',frames,'-r',FPS,'-c:v','libx264','-preset','veryfast','-crf','19','-threads','4',output]);dump(meta,dict(signature=signature,frames=frames,source_page=s['page_id']))
   print('render',draft['chapter'],s['page_id'],round(s['duration'],1),'seconds',flush=True)
  outputs.append(output)
 listing=target/'clips.txt';listing.write_text('\n'.join("file '"+p.as_posix()+"'" for p in outputs),encoding='utf-8');final=target/'chapter.mp4'
 ff(['-f','concat','-safe','0','-i',listing,'-i',audio,'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','160k','-af','apad','-t',data['duration'],'-movflags','+faststart',final])
 dump(target/'render-complete.json',dict(path=str(final.resolve()),duration=data['duration'],fps=FPS,width=WIDTH,height=HEIGHT,words=draft['words'],text_sha256=draft['text_sha256'],camera_pages=[s['page_id'] for s in data['shots']],publication_approved=False,policy=POLICY));return final

def qa_chapter(target,data):
 folder=target/'qa';folder.mkdir(exist_ok=True);samples=[]
 for i,s in enumerate(data['shots']):
  for label,at in [('mid',s['start']+s['duration']/2),('entry',s['start']+.04),('exit',s['end']-1.5/FPS)]:
   at=max(s['start'],min(s['end']-1.5/FPS,at));p=folder/f'{i:03}-{label}.jpg'
   ff(['-ss',at,'-i',target/'chapter.mp4','-frames:v','1',p]);samples.append(dict(page_id=s['page_id'],time=at,path=str(p.resolve()),label=label))
 for label in ['mid','entry','exit']:
  rows=[r for r in samples if r['label']==label];sheet=Image.new('RGB',(1280,205*math.ceil(len(rows)/4)),(30,30,30));draw=ImageDraw.Draw(sheet)
  for i,r in enumerate(rows):
   with Image.open(r['path']) as im:im=im.resize((320,180));x=i%4*320;y=i//4*205;sheet.paste(im,(x,y+25));draw.text((x+5,y+6),f"{r['time']:.1f}s {r['page_id']}",fill='white')
  sheet.save(target/('contact-'+label+'.jpg'),quality=85)
 dump(target/'qa-samples.json',samples)
 dump(target/'qa-manifest.json',dict(video_sha256=hashlib.sha256((target/'chapter.mp4').read_bytes()).hexdigest(),camera_plan_sha256=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(),samples=len(samples)))

def qa_current(target,data):
 marker=target/'qa-manifest.json'
 if not marker.exists():return False
 m=json.loads(marker.read_text(encoding='utf-8'))
 return m.get('video_sha256')==hashlib.sha256((target/'chapter.mp4').read_bytes()).hexdigest() and m.get('camera_plan_sha256')==hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def follow(wait=False):
 source=inventory(Path(DEFAULT_SOURCE),['all']);labels=sorted({p['chapter'] for p in source},key=chapter_sort)
 for label in labels:
  target=OUT/'chapters'/('chapter-'+str(label));path=target/'draft.json'
  while not path.exists():
   if not wait:print('Waiting for draft',label,flush=True);return
   time.sleep(10)
  draft=delivery_draft(json.loads(path.read_text(encoding='utf-8')));dump(target/'delivery-draft.json',draft)
  done=target/'render-complete.json'
  if done.exists() and json.loads(done.read_text()).get('text_sha256')==draft['text_sha256'] and json.loads(done.read_text()).get('policy')==POLICY:
   current_plan=json.loads((target/'camera-plan.json').read_text())
   if not qa_current(target,current_plan):qa_chapter(target,current_plan)
   continue
  if wait:
   from quota_control import hold_reason
   from storybench import ROOT
   scope_path=OUT/'book-audio/scope.json';batched=scope_path.exists() and str(label) not in set(json.loads(scope_path.read_text())['retained_chapters'])
   while not (target/'audio-prepared.json').exists() and (batched or hold_reason(ROOT/'quota-state.json','gemini','gemini-3.8-flash-tts')):time.sleep(10)
   draft=delivery_draft(json.loads(path.read_text(encoding='utf-8')));dump(target/'delivery-draft.json',draft)
  print('AUDIO',label,draft['words'],'words',flush=True);audio=chapter_audio(draft,target);data=plan(draft,target,audio);render(draft,target,audio,data);qa_chapter(target,data)
  print('CHAPTER VIDEO READY',label,data['duration'],flush=True)
 assemble(labels)

def assemble(labels):
 parts=[];audio_parts=[];offset=0;metadata=[';FFMETADATA1'];markers=[]
 for label in labels:
  target=OUT/'chapters'/('chapter-'+str(label));r=json.loads((target/'render-complete.json').read_text());parts.append(target/'chapter.mp4');metadata+=['[CHAPTER]','TIMEBASE=1/1000',f'START={round(offset*1000)}',f'END={round((offset+r["duration"])*1000)}',f'title=Chapter {label}'];markers.append(dict(chapter=label,start=offset,duration=r['duration'],words=r['words']));offset+=r['duration']
  # Encode the final narration once. Frame-pad PCM before concatenating so
  # chapter AAC priming and sub-frame rounding cannot accumulate over the book.
  padded=target/'narration-timeline.wav'
  ff(['-i',target/'narration.wav','-af','apad','-t',r['duration'],'-ar','48000','-ac','1','-c:a','pcm_s16le',padded]);audio_parts.append(padded)
 listing=OUT/'chapters.txt';listing.write_text('\n'.join("file '"+p.as_posix()+"'" for p in parts));meta=OUT/'chapters.ffmeta';meta.write_text('\n'.join(metadata),encoding='utf-8');final=OUT/'full-manga-evaluation.mp4'
 audio_listing=OUT/'narration-chapters.txt';audio_listing.write_text('\n'.join("file '"+p.as_posix()+"'" for p in audio_parts),encoding='utf-8')
 ff(['-f','concat','-safe','0','-i',listing,'-f','concat','-safe','0','-i',audio_listing,'-f','ffmetadata','-i',meta,'-map','0:v','-map','1:a','-map_metadata','2','-c:v','copy','-c:a','aac','-b:a','160k','-t',offset,'-movflags','+faststart',final]);dump(OUT/'video-manifest.json',dict(path=str(final.resolve()),duration=offset,chapters=markers,width=WIDTH,height=HEIGHT,fps=FPS,audio_assembly='Single AAC encode from frame-padded 48kHz chapter WAVs',evaluation_only=True,manual_prose_edits=False,publication_approved=False));print('FULL VIDEO READY',final,offset,flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--wait-for-drafts',action='store_true');a=p.parse_args();follow(a.wait_for_drafts)
