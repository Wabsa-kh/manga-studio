"""Library manager and bounded GitHub worker entry point."""
import argparse,os,time,sys,traceback,shutil
from pathlib import Path
from .core import read,save,digest,utc,Singleton,Pending,Attention,event
from .ingest import manga_url,download
from .storage import Snapshot,LocalStore,RcloneStore

def settings(path):
 cfg=read(path)
 if not cfg:raise ValueError('Settings JSON is missing')
 cfg['state_root']=str(Path(os.environ.get('MANGA_STATE_ROOT',cfg.get('state_root','state'))).resolve());return cfg

def add(root,url,title=None):
 root=Path(root);url=manga_url(url);ident=digest(url)[:12];path=root/'library.json';library=read(path,{'version':1,'manga':[]})
 if not any(m['id']==ident for m in library['manga']):library['manga'].append(dict(id=ident,url=url,title=title or url.rsplit('/',1)[-1],directory=str((root/'manga'/ident).resolve()),state='queued',created_utc=utc(),resume_epoch=0))
 save(path,library);return ident

def report(root):
 root=Path(root);library=read(root/'library.json',{'manga':[]});lines=['# Manga production library','']
 for item in library['manga']:
  status=read(Path(item['directory'])/'job/status.json',{});item['production']=status;parts=list((Path(item['directory'])/'job/parts').glob('*/complete.json'));item['finished_minutes']=sum(read(p)['duration']/60 for p in parts)
  lines.append(f"- **{item['title']}** — {item['state']}; downloaded chapters {item.get('downloaded_chapters',0)}/{item.get('expected_chapters','?')}; pages read {status.get('pages_read',0)}/{status.get('total_pages','?')}; video parts {len(parts)}, {item['finished_minutes']:.1f} finished minutes.")
  if item.get('reason'):lines.append('  '+item['reason'])
 from .core import Budget
 library['usage']=Budget(root/'provider-state/budget.sqlite').summary();library['finished_minutes']=sum(m.get('finished_minutes',0) for m in library['manga']);save(root/'dashboard.json',library);(root/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');return library

def doctor(cfg):
 checks=dict(python=sys.version.split()[0],ffmpeg=bool(shutil.which('ffmpeg')),rclone=bool(shutil.which('rclone')),gemini_key_configured=bool(os.environ.get('GEMINI_API_KEY')),storage=cfg['storage']['backend'],remote_configured=bool(os.environ.get(cfg['storage'].get('remote_env','MANGA_STORE_REMOTE'))),colab_cli=bool(shutil.which('colab')),youtube_enabled=cfg['youtube']['enabled'])
 checks['drive_credentials_configured']=bool(os.environ.get('MANGA_RCLONE_CONFIG'));checks['colab_credentials_configured']=bool(os.environ.get('COLAB_ADC_JSON'))
 checks['storage_ready']=cfg['storage']['backend']=='local' or checks['rclone'] and checks['remote_configured'] and checks['drive_credentials_configured']
 checks['publishing_ready']=checks['storage_ready'] and checks['youtube_enabled'] and bool(os.environ.get('YOUTUBE_TOKEN_JSON')) and bool(os.environ.get('YOUTUBE_CHANNEL_ID'))
 checks['production_ready']=checks['ffmpeg'] and checks['gemini_key_configured'] and checks['storage_ready'] and (not cfg['upscale']['enabled'] or checks['colab_cli'] and checks['colab_credentials_configured']);return checks

def upscale_handoff(snapshot,manga_id,cfg):
 from .colab_bridge import launch
 failure=None
 try:launch(manga_id,cfg)
 except Exception as exc:failure=exc
 # Colab is an exclusive writer while it owns the GPU task. Always restore
 # its last published checkpoint, including after a disconnect/timeout.
 if not snapshot.restore():raise Attention('No GPU handoff checkpoint could be restored')
 return read(snapshot.root/'library.json'),failure

def pull(cfg,manga_id,part_id,destination):
 import re
 if not re.fullmatch(r'part-\d{3,}',part_id):raise ValueError('Use a part ID such as part-001')
 root=Path(cfg['state_root']);store=LocalStore(os.environ.get('MANGA_LOCAL_ARCHIVE',str(root.parent/'archive'))) if cfg['storage']['backend']=='local' else RcloneStore(os.environ.get(cfg['storage'].get('remote_env','MANGA_STORE_REMOTE')))
 snapshot=Snapshot(root,store,lazy_upscale=True,lazy_media=True,lazy_source=True)
 try:
  if not snapshot.restore():raise Attention('No saved production archive found')
  item=next((m for m in read(root/'library.json')['manga'] if m['id']==manga_id),None)
  if not item:raise ValueError('Unknown manga ID')
  source=Path(item['directory'])/'job/parts'/part_id;complete=read(source/'complete.json')
  if not complete:raise Attention('That part has not completed')
  destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True);prefix=source.relative_to(root).as_posix()+'/'
  for name in snapshot.entries:
   if name.startswith(prefix) and '/' not in name[len(prefix):]:
    path=root/name;snapshot.ensure_path(path);shutil.copy2(path,destination/path.name)
  print('Part downloaded:',destination/'video.mp4')
 finally:
  if hasattr(store,'close'):store.close()

def worker(cfg,url=None,retry_id=None):
 root=Path(cfg['state_root']);root.mkdir(parents=True,exist_ok=True);backend=cfg['storage']['backend']
 if backend=='local':snapshot=Snapshot(root,LocalStore(os.environ.get('MANGA_LOCAL_ARCHIVE',str(root.parent/'archive'))),lazy_upscale=True,lazy_media=True)
 else:snapshot=Snapshot(root,RcloneStore(os.environ.get(cfg['storage'].get('remote_env','MANGA_STORE_REMOTE'))),lazy_upscale=True,lazy_media=True)
 if cfg.get('_console_log'):
  original_checkpoint=snapshot.checkpoint
  def checkpoint_with_console():
   log=cfg['_console_log'];log.flush();position=log.tell();log.seek(0);content=log.read();log.seek(position)
   folder=root/'diagnostics';folder.mkdir(parents=True,exist_ok=True);(folder/'latest-run.log').write_text(content[-1024*1024:],encoding='utf-8')
   return original_checkpoint()
  snapshot.checkpoint=checkpoint_with_console
 try:
  with Singleton(root.parent/'manga-manager.lock'):
   snapshot.restore()
   if url:add(root,url)
   library=read(root/'library.json',{'version':1,'manga':[]});deadline=time.time()+cfg.get('max_run_minutes',240)*60;cfg['_deadline']=deadline
   if retry_id:
    selected=next((m for m in library['manga'] if m['id']==retry_id),None)
    if not selected:raise ValueError('Unknown saved manga ID')
    selected.update(state='queued',resume_epoch=0,reason='Owner requested retry after review/configuration fix')
    from .core import Budget
    with Budget(root/'provider-state/budget.sqlite').db() as db:db.execute("DELETE FROM holds WHERE permanent=1 AND reason LIKE '%authentication%'")
    save(root/'library.json',library)
   for manga_id in [m['id'] for m in library['manga']]:
    item=next(m for m in library['manga'] if m['id']==manga_id)
    if time.time()>deadline:break
    job=Path(item['directory'])/'job'
    if (job/'config.json').exists():
     from .publishing import publish
     publish(job,cfg,snapshot)
    if cfg.get('_publish_only'):continue
    if item.get('resume_epoch',0)>time.time() or item['state'] in ['complete','needs_review']:continue
    storage_safe=True
    try:
     directory=Path(item['directory']);directory.mkdir(parents=True,exist_ok=True);item['state']='downloading';save(root/'library.json',library);snapshot.checkpoint()
     if not item.get('download_complete'):
      item['download_complete']=download(root,item,cfg,snapshot.checkpoint)
      if not item['download_complete']:item.update(state='downloading',reason='More chapters remain; saved download receipts');continue
     if cfg['upscale']['enabled'] and not item.get('upscale_complete'):
      item.update(state='waiting_upscale',reason='GPU upscale task exported for Colab');save(directory/'upscale-task.json',dict(source=item['source'],target=str(directory/'upscaled'),state=str(root),mode=cfg['upscale'].get('color_mode','bw')));save(root/'library.json',library);snapshot.checkpoint()
      storage_safe=False;library,failure=upscale_handoff(snapshot,item['id'],cfg);item=next(m for m in library['manga'] if m['id']==manga_id);storage_safe=True
      if failure:raise failure
      if not item.get('upscale_complete'):raise Attention('Colab returned without a verified completion receipt')
     from .worker import initialize,turn,status
     from .providers import Google
     jobcfg={**{k:v for k,v in cfg.items() if k!='_console_log'},'title':item['title'],'source':item['source'],'upscaled_source':item.get('upscaled_source'),'output':str(directory/'job'),'provider_state':str(root/'provider-state')};jobroot,inventory=initialize(jobcfg);api=Google(jobroot,root/'provider-state',cfg.get('providers'),snapshot.checkpoint);api.assets=snapshot;item['state']='producing'
     with Singleton(jobroot/'worker.lock'):
      while time.time()<deadline:
       progress=turn(jobroot,inventory,api,jobcfg)
       if cfg.get('youtube',{}).get('prepare_metadata'):
        from .publishing import queue
        queue(jobroot)
       snapshot.checkpoint()
       if cfg.get('youtube',{}).get('enabled'):
        from .publishing import publish
        publish(jobroot,cfg,snapshot)
       # Complete parts are acknowledged remotely before large local media
       # is released. Manifest references remain, so reruns can hydrate it.
       for complete in (jobroot/'parts').glob('*/complete.json'):
        scope=read(complete.parent/'scope.json')
        folders=[complete.parent]+[jobroot/'units'/u['id'] for u in scope['units']]
        for folder in folders:
         for asset in folder.rglob('*'):
          if asset.is_file() and snapshot.lazy(asset) and asset.relative_to(root).as_posix() in snapshot.entries:snapshot.evict_path(asset)
       if not progress:item['state']='complete';break
    except Pending as exc:item.update(state='waiting',reason=exc.reason,resume_epoch=exc.resume)
    except Attention as exc:item.update(state='needs_review',reason=str(exc));event(root,'job_attention',manga_id=item['id'],reason=str(exc))
    except Exception as exc:
     item.update(state='technical_error',reason=type(exc).__name__+': '+str(exc),resume_epoch=time.time()+3600);(Path(item['directory'])/'technical-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
     if not storage_safe:raise Attention('GPU checkpoint refresh failed; refusing to overwrite newer remote state')
     save(root/'library.json',library);report(root);snapshot.checkpoint()
   report(root);snapshot.checkpoint()
 finally:
  if hasattr(snapshot.store,'close'):snapshot.store.close()

def main():
 p=argparse.ArgumentParser();p.add_argument('--settings',default='config/settings.json');sub=p.add_subparsers(dest='command',required=True);a=sub.add_parser('add');a.add_argument('url');a.add_argument('--title');sub.add_parser('list');sub.add_parser('doctor');r=sub.add_parser('run');r.add_argument('--url');r.add_argument('--retry-id');sub.add_parser('report');fetch=sub.add_parser('pull');fetch.add_argument('manga_id');fetch.add_argument('part_id');fetch.add_argument('--destination',required=True);args=p.parse_args();cfg=settings(args.settings);root=Path(cfg['state_root'])
 if args.command=='add':print(add(root,args.url,args.title))
 elif args.command=='doctor':print(__import__('json').dumps(doctor(cfg),indent=2))
 elif args.command=='run':worker(cfg,args.url,args.retry_id)
 elif args.command=='pull':pull(cfg,args.manga_id,args.part_id,args.destination)
 else:print(__import__('json').dumps(report(root),indent=2))
if __name__=='__main__':main()
