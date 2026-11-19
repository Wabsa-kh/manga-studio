"""Headless adapter for the user's Spladenly ESRGAN notebook models."""
import argparse,subprocess,sys,shutil,time
from pathlib import Path
from PIL import Image
from .core import read,save,sha,Attention
from .ingest import vendor

MODELS={'bw':'4x_eula_digimanga_bw_v2_nc1_307k.pth','color':'4x-AnimeSharp.pth'}

def verify(source,output,scale=4):
 try:
  with Image.open(source) as a,Image.open(output) as b:
   size=a.size;got=b.size;b.verify()
  if got!=(size[0]*scale,size[1]*scale):return None
  return dict(source_sha256=sha(source),output_sha256=sha(output),size=list(got),scale=scale)
 except (OSError,ValueError):return None

def stream_chapters(snapshot,source,target,state,originals=None,**options):
 """Read the next chapter into scratch space while the GPU renders this one."""
 import tempfile
 from concurrent.futures import ThreadPoolExecutor
 from .core import Pending
 source=Path(source);target=Path(target);prefix=source.relative_to(snapshot.root)
 chapters={};total=0
 for name,row in snapshot.entries.items():
  path=Path(name)
  if not path.is_relative_to(prefix) or path.suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:continue
  rel=path.relative_to(prefix)
  if originals is not None:
   if rel.as_posix() not in originals:continue
   if originals[rel.as_posix()]!=row['sha256']:raise Attention('Part scope refers to a different source page')
  out=(target/rel).with_suffix('.png')
  receipt=read(out.with_suffix('.upscale.json'),{})
  saved=snapshot.entries.get(out.relative_to(snapshot.root).as_posix(),{})
  total+=1
  if receipt.get('scale')==4 and receipt.get('source_sha256')==row['sha256'] and saved and receipt.get('output_sha256')==saved['sha256']:continue
  chapters.setdefault(rel.parent,[]).append((rel.name,row['sha256']))
 if originals is not None and total!=len(originals):raise Attention('Part scope has missing source pages')
 if not total:raise Attention('Verified source pages missing from the GPU task manifest')
 def fetch(chapter,folder):
  folder.mkdir();blobs={}
  for name,h in chapters[chapter]:
   blobs.setdefault(h,folder/name)
  entries=[('objects/'+h[:2]+'/'+h[2:],dest) for h,dest in blobs.items()]
  ok=snapshot.store.get_many(entries) if hasattr(snapshot.store,'get_many') else all(snapshot.store.get(key,dest) for key,dest in entries)
  if not ok or any(sha(dest)!=h for h,dest in blobs.items()):raise Attention('Source chapter failed its Drive checksum check')
  for name,h in chapters[chapter]:
   if folder/name!=blobs[h]:shutil.copyfile(blobs[h],folder/name)
  return folder
 deadline=options.pop('deadline',float('inf'))
 ordered=list(chapters)
 if ordered:
  with tempfile.TemporaryDirectory(prefix='manga-gpu-input-') as scratch, ThreadPoolExecutor(max_workers=1) as io:
   base=Path(scratch);future=io.submit(fetch,ordered[0],base/'0')
   for index,chapter in enumerate(ordered):
    if time.time()>=deadline-120:raise Pending('GPU time budget reached; verified pages saved',time.time()+60)
    current=future.result()
    if index+1<len(ordered):future=io.submit(fetch,ordered[index+1],base/str(index+1))
    run(current,target/chapter,state,**options)
    for name,_ in chapters[chapter]:
     output=(target/chapter/name).with_suffix('.png')
     if output.exists():snapshot.evict_path(output)
    shutil.rmtree(current)
 return total

def run(source,target,state,mode='bw',checkpoint=lambda:None,checkpoint_pages=16,checkpoint_seconds=60):
 import torch
 if not torch.cuda.is_available():raise Attention('GPU upscale requires a connected Colab GPU runtime; source images remain intact')
 repo=vendor(state,'esrgan');model=repo/'models'/MODELS[mode]
 if not model.exists():raise Attention('Pinned ESRGAN model is missing: '+MODELS[mode])
 source=Path(source).resolve();target=Path(target).resolve();pages=[p for p in source.rglob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp'}];verified=set()
 for page in pages:
  out=target/page.relative_to(source).with_suffix('.png');old=read(out.with_suffix('.upscale.json'));current=verify(page,out)
  if old and current==old:verified.add(str(page))
  elif out.exists():out.unlink()  # Invalid generated output only; source untouched.
 import importlib.util
 persisted=len(verified);last_checkpoint=time.monotonic()
 sys.path.insert(0,str(repo));spec=importlib.util.spec_from_file_location('vendor_esrgan_upscale',repo/'upscale.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);original=module.Progress
 class DurableProgress(original):
  def advance(self,*args,**kwargs):
   nonlocal persisted,last_checkpoint
   super().advance(*args,**kwargs);changed=False
   for page in pages:
    if str(page) in verified:continue
    out=target/page.relative_to(source).with_suffix('.png')
    if out.exists():
     metadata=verify(page,out)
     if not metadata:raise Attention('Upscaler output failed dimensions/hash validation')
     save(out.with_suffix('.upscale.json'),metadata);verified.add(str(page));changed=True
   if changed and (len(verified)-persisted>=checkpoint_pages or time.monotonic()-last_checkpoint>=checkpoint_seconds):
    checkpoint();persisted=len(verified);last_checkpoint=time.monotonic();print('Checkpointed upscaled pages:',persisted,'/',len(pages),flush=True)
 module.Progress=DurableProgress
 # Keep one model in GPU memory, retaining upstream recursive OOM splitting.
 # Per-page progress fires after output writes, when checkpointing is safe.
 module.Upscale(model=str(model),input=source,output=target,skip_existing=True,delete_input=False).run()
 if len(verified)!=len(pages):raise Attention('Upscale run ended with missing pages')
 if len(verified)>persisted:checkpoint()
 return len(verified)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--target',required=True);p.add_argument('--state',required=True);p.add_argument('--mode',choices=list(MODELS),default='bw');a=p.parse_args();run(a.source,a.target,a.state,a.mode)
