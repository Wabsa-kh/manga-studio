"""Checkpointed tasks shared by Colab downloads and GPU upscaling."""
import time,traceback,re
from pathlib import Path
from .core import read,save,digest,Pending,Attention

def process(snapshot,manga_id,stage,cfg):
 if stage not in ('download','upscale'):raise Attention('Unknown Colab task stage')
 state=snapshot.root;library=read(state/'library.json');item=next(m for m in library['manga'] if m['id']==manga_id)
 directory=Path(item['directory']);directory.mkdir(parents=True,exist_ok=True)
 def checkpoint():save(state/'library.json',library);snapshot.checkpoint()
 try:
  if stage=='download':
   from .ingest import download
   if not item.get('download_complete'):
    item.update(state='colab_downloading',reason='Downloading and verifying original pages inside Colab');checkpoint()
    item['download_complete']=download(state,item,{**cfg,'_saved_files':snapshot.entries},checkpoint)
    if not item['download_complete']:raise Pending('More chapters remain; Colab download receipts preserved',time.time()+60)
   item.update(state='ready_for_upscale' if cfg.get('upscale',{}).get('enabled') else 'ready_for_story',reason='Original pages downloaded and verified in Colab',resume_epoch=0)
  else:
   from .upscale import run,stream_chapters
   if not item.get('download_complete'):raise Attention('Download must complete before GPU upscaling')
   target=directory/'upscaled';item['state']='upscaling';checkpoint()
   options=cfg.get('upscale',{})
   task=read(directory/'upscale-task.json',{});part=task.get('part')
   if part:
    if not re.fullmatch(r'part-\d{3,}',part) or not snapshot.lazy_source:raise Attention('Invalid part upscale task')
    scope=directory/'job'/'parts'/part/'scope.json'
    if not scope.exists() or digest(read(scope))!=task['scope_hash'] or not task.get('originals'):raise Attention('Part scope changed before upscaling')
   render=run
   if snapshot.lazy_source:
    def render(source,target,state,**kwargs):return stream_chapters(snapshot,source,target,state,originals=task.get('originals') if part else None,deadline=cfg.get('_deadline',float('inf')),**kwargs)
   render(item['source'],target,state,mode=options.get('color_mode','bw'),checkpoint=checkpoint,checkpoint_pages=options.get('checkpoint_pages',16),checkpoint_seconds=options.get('checkpoint_seconds',60))
   if part:
    save(scope.parent/'upscale-complete.json',dict(scope_hash=task['scope_hash'],pages=len(task['originals'])))
    item.update(upscaled_source=str(target),state='ready_for_render',reason='Verified 4x pages for '+part,resume_epoch=0)
   else:item.update(upscale_complete=True,upscaled_source=str(target),state='ready_for_story',reason='Verified 4x upscale complete',resume_epoch=0)
 except Pending as exc:item.update(state='waiting',reason=exc.reason,resume_epoch=exc.resume)
 except Attention as exc:item.update(state='needs_review',reason=str(exc))
 except Exception:
  item.update(state='technical_error',reason='Colab task failed; private traceback retained',resume_epoch=time.time()+3600)
  (directory/'colab-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
  raise
 finally:checkpoint()
 return item
