"""Run with python -m manga_bot.worker --config PATH [--once|--text-only]."""
import argparse,os,time,traceback,shutil
from pathlib import Path
from .core import read,save,sha,digest,event,utc,units_for,choose_part,Pending,Attention,Singleton
from .providers import Google
from .stages import read_batch,write_unit
from run import inventory

def initialize(config):
 root=Path(config['output']);root.mkdir(parents=True,exist_ok=True);save(root/'config.json',config)
 path=root/'inventory.json';data=read(path)
 if not data:
  pages=inventory(Path(config['source']),['all']);units=units_for(pages,config.get('unit_pages',40));data=dict(source=config['source'],pages=pages,units=units,signature=digest(pages),frozen_utc=utc());save(path,data)
 elif data['source']!=config['source']:raise Attention('Source directory changed for existing job')
 for p in data['pages']:
  if not Path(p['path']).exists():raise Attention('Source is missing: '+p['page_id'])
 code={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')}
 for name in ['reader_v3.py','series_video_v9.py','series_writing_v9.py','narration_contract.py','narration_style.txt','smooth_camera.py','camera_engine.py','series_av_v9.py','reference/style-calibration.json']:
  p=Path(__file__).parent.parent/name;code[name]=sha(p)
 signature=digest(code);old=read(root/'code-version.json')
 if not old or old['signature']!=signature:
  event(root,'technical_code_version',signature=signature,previous=(old or {}).get('signature'),manual_story_corrections=0);save(root/'code-version.json',dict(signature=signature,files=code))
 return root,data

def status(root,api,state,**fields):
 inv=read(root/'inventory.json');drafts=list((root/'units').glob('*/draft.json'));videos=list((root/'units').glob('*/video.json'));parts=list((root/'parts').glob('*/complete.json'));pages=len(list((root/'pages').glob('*.json')))
 data=dict(updated_utc=utc(),state=state,total_pages=len(inv['pages']),pages_read=pages,total_units=len(inv['units']),units_written=len(drafts),units_rendered=len(videos),parts_complete=len(parts),part_minutes_target=[45,60],manual_story_corrections=0,manual_prose_edits=0,usage=api.budget.summary(),evaluation_only=True,**fields);save(root/'status.json',data)
 text=f"# {read(root/'config.json')['title']} unattended test\n\nState: {state}\n\nPages read: {pages}/{len(inv['pages'])}; units written: {len(drafts)}/{len(inv['units'])}; rendered: {len(videos)}; complete parts: {len(parts)}.\n\nTarget: 45–60 minutes per part. Story and prose edits by the operator: 0. Outputs are evaluation cuts, not publication approval.\n\n"
 if fields.get('reason'):text+='Current condition: '+fields['reason']+'\n\n'
 for p in sorted(parts):
  r=read(p);text+=f"- [{p.parent.name}: {r['minutes']:.1f} minutes]({r['path']})\n"
 text+='\nProvider usage is recorded in status.json and individual request receipts. No paid fallback is configured. Local electricity/server costs are not measured.\n';(root/'REPORT.md').write_text(text,encoding='utf-8');return data

def turn(root,inv,api,config,text_only=False):
 if shutil.disk_usage(root).free<config.get('minimum_free_gb',4)*1024**3:raise Attention('Less than configured free disk space remains')
 # First finish any independently runnable media from earlier writing work.
 waits=[]
 batching=config.get('part_audio_batching',False);minimum,maximum=config.get('part_minutes',[45,60]);wpm=config.get('words_per_minute',207)
 if not text_only:
  from .media import unit_video,assemble
  if batching:
   from .part_audio import prepare
   for scope in sorted((root/'parts').glob('*/scope.json')):
    if not (scope.parent/'speech/complete.json').exists():
     try:prepare(api,root,read(scope),config)
     except Pending as exc:waits.append(exc)
     break
  for u in inv['units']:
   draft=read(root/'units'/u['id']/'draft.json')
   if draft and not (root/'units'/u['id']/'video.json').exists() and (not batching or (root/'units'/u['id']/'audio-prepared.json').exists()):
    try:status(root,api,'generating_audio_and_video',active_unit=u['id']);unit_video(api,root,u,draft);return True
    except Pending as exc:waits.append(exc);break
  for manifest in sorted((root/'parts').glob('*/scope.json')):
   part=read(manifest)
   if not (manifest.parent/'complete.json').exists() and all((root/'units'/u['id']/'video.json').exists() for u in part['units']):
    if hasattr(api,'assets'):
     for u in part['units']:
      for filename in ['chapter.mp4','narration.wav']:api.assets.ensure_path(root/'units'/u['id']/filename)
    status(root,api,'assembling_part',active_part=part['id']);assemble(root,part);return True
 # Draft sequentially: every unit sees all preceding memory, never future facts.
 previous=[];missing=None
 for u in inv['units']:
  d=read(root/'units'/u['id']/'draft.json')
  if not d:missing=u;break
  previous.append(d)
 # Freeze part membership once the story boundary is determined.
 covered=set();part_count=0
 for p in sorted((root/'parts').glob('*/scope.json')):
  part=read(p);covered.update(u['id'] for u in part['units']);part_count+=1
 pending=[]
 for d in previous:
  if d['chapter'] in covered:continue
  video=read(root/'units'/d['chapter']/'video.json')
  if not text_only and not batching and not video:break
  pending.append({**d,**({'duration_minutes':video['duration']/60} if video else {})})
 n=choose_part(pending,minimum,maximum,wpm,at_end=missing is None and (text_only or batching or len(pending)+len(covered)==len(previous)))
 if n:
  selected=pending[:n];part=dict(id=f'part-{part_count+1:03}',units=[dict(id=d['chapter'],chapters=d['chapters'],text_sha256=d['text_sha256'],words=d['words']) for d in selected],target_minutes=[minimum,maximum],estimated_minutes=sum(d['words'] for d in selected)/wpm,boundary=selected[-1]['boundary'],frozen_utc=utc());save(root/'parts'/part['id']/'scope.json',part);event(root,'part_scope_frozen',**part);return True
 if missing:
  # Bound ahead-of-speech work, so a quota hold cannot accumulate the whole book.
  unrendered=sum(not (root/'units'/d['chapter']/'video.json').exists() for d in previous)
  if not text_only and (batching or unrendered>=config.get('prefetch_units',2)) and waits:raise min(waits,key=lambda e:e.resume)
  status(root,api,'reading_and_writing',active_unit=missing['id'])
  from concurrent.futures import ThreadPoolExecutor,as_completed
  size=config.get('reader_batch_pages',2)
  with ThreadPoolExecutor(max_workers=2) as pool:
   futures=[pool.submit(read_batch,api,root,missing['pages'][i:i+size]) for i in range(0,len(missing['pages']),size)]
   failures=[]
   for future in as_completed(futures):
    try:future.result()
    except (Pending,Attention) as exc:failures.append(exc)
    status(root,api,'reading_and_writing',active_unit=missing['id'])
   if failures:
    fatal=next((e for e in failures if isinstance(e,Attention)),None)
    raise fatal or min(failures,key=lambda e:e.resume)
  try:write_unit(api,root,missing,previous);return True
  except Pending as exc:waits.append(exc)
 if waits:raise min(waits,key=lambda e:e.resume)
 if not missing:
  status(root,api,'text_complete' if text_only else 'complete');return False
 return True

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--text-only',action='store_true');args=parser.parse_args();config=read(args.config);root,inv=initialize(config);api=Google(root,config.get('provider_state'))
 with Singleton(root/'worker.lock'):
  event(root,'worker_started',pid=os.getpid(),text_only=args.text_only);save(root/'worker.json',dict(pid=os.getpid(),started_utc=utc()))
  while not (root/'STOP').exists():
   try:
    progress=turn(root,inv,api,config,args.text_only)
    if not progress or args.once:return
   except Pending as exc:
    status(root,api,'waiting',reason=exc.reason,resume_epoch=exc.resume);print('Waiting:',exc.reason,flush=True)
    if args.once:return
    # Short interruptible waits preserve responsiveness and durable progress.
    while time.time()<exc.resume and not (root/'STOP').exists():time.sleep(min(30,max(.1,exc.resume-time.time())))
   except Attention as exc:
    status(root,api,'needs_attention',reason=str(exc));event(root,'needs_attention',reason=str(exc));return
   except Exception as exc:
    # Preserve a local traceback; do not replay accepted provider operations.
    (root/'technical-error.txt').write_text(traceback.format_exc(),encoding='utf-8');status(root,api,'technical_error',reason=type(exc).__name__+': '+str(exc));event(root,'technical_error',kind_name=type(exc).__name__);raise
  status(root,api,'stopped_by_flag')

if __name__=='__main__':main()
