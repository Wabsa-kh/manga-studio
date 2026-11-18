"""Checkpointed tasks shared by Colab downloads and GPU upscaling."""
import time,traceback
from pathlib import Path
from .core import read,save,Pending,Attention

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
    item['download_complete']=download(state,item,cfg,checkpoint)
    if not item['download_complete']:raise Pending('More chapters remain; Colab download receipts preserved',time.time()+60)
   item.update(state='ready_for_upscale' if cfg.get('upscale',{}).get('enabled') else 'ready_for_story',reason='Original pages downloaded and verified in Colab',resume_epoch=0)
  else:
   from .upscale import run
   if not item.get('download_complete'):raise Attention('Download must complete before GPU upscaling')
   target=directory/'upscaled';item['state']='upscaling';checkpoint()
   run(item['source'],target,state,mode=cfg.get('upscale',{}).get('color_mode','bw'),checkpoint=checkpoint)
   item.update(upscale_complete=True,upscaled_source=str(target),state='ready_for_story',reason='Verified 4x upscale complete',resume_epoch=0)
 except Pending as exc:item.update(state='waiting',reason=exc.reason,resume_epoch=exc.resume)
 except Attention as exc:item.update(state='needs_review',reason=str(exc))
 except Exception:
  item.update(state='technical_error',reason='Colab task failed; private traceback retained',resume_epoch=time.time()+3600)
  (directory/'colab-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
  raise
 finally:checkpoint()
 return item
