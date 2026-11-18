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
