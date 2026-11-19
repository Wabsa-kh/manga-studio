"""Pinned upstream downloader, with strict per-chapter completion receipts."""
import importlib,subprocess,sys,re,time
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlparse,urlunparse
from PIL import Image
from .core import read,save,digest,sha,Attention,Pending

VENDORS={'downloader':('https://github.com/Yui007/weebcentral_downloader.git','0ff164d0d7f46a3668639b7dbdf972147a50735e'),'esrgan':('https://github.com/Spladenly/ESRGAN.git','f70ea9bbe5287dc60422901d2f0ffe02e5a0431b')}

def manga_url(value):
 p=urlparse(value.strip())
 if p.scheme!='https' or p.hostname not in ['weebcentral.com','www.weebcentral.com'] or p.username or p.password or p.port or not re.fullmatch(r'/series/[A-Za-z0-9]+(?:/[A-Za-z0-9_-]+)?/?',p.path):raise ValueError('Use a full https://weebcentral.com/series/... manga URL')
 return urlunparse(('https','weebcentral.com','/series/'+p.path.split('/')[2],'','',''))

def vendor(root,name):
 url,commit=VENDORS[name];folder=Path(root)/'vendors'/name
 if not (folder/'.git').exists():
  folder.mkdir(parents=True,exist_ok=True)
  for args in [['init',str(folder)],['-C',str(folder),'fetch','--depth','1',url,commit],['-C',str(folder),'checkout','--detach','FETCH_HEAD']]:subprocess.run(['git',*args],check=True,capture_output=True)
 actual=subprocess.check_output(['git','-C',str(folder),'rev-parse','HEAD'],text=True).strip()
 if actual!=commit:raise Attention('Upstream dependency revision changed unexpectedly')
 return folder

def verified_images(folder,expected):
 paths=sorted([p for p in Path(folder).glob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}])
 if len(paths)!=expected:return None
 if {p.stem for p in paths}!={f'{i:03}' for i in range(1,expected+1)}:return None
 result=[]
 for p in paths:
  try:
   with Image.open(p) as im:im.load()
  except (OSError,ValueError):return None
  result.append(dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size))
 return result

def download(root,job,settings,checkpoint=lambda:None):
 root=Path(root);folder=vendor(root,'downloader');sys.path.insert(0,str(folder));module=importlib.import_module('weebcentral_scraper');config=settings['download'];source=Path(job['directory'])/'source';source.mkdir(parents=True,exist_ok=True)
 # Verification and the pinned downloader both ask for the same page list.
 class SeriesScraper(module.WeebCentralScraper):
  @lru_cache(maxsize=1)
  def get_chapter_images(self,url):return super().get_chapter_images(url)
 scraper=SeriesScraper(job['url'],output_dir=str(source),delay=config.get('delay_seconds',1.5),max_threads=config.get('threads',2));chapters=scraper.get_chapters()
 if not chapters:raise Pending('No chapters returned; download remains incomplete',time.time()+3600)
 job.update(expected_chapters=len(chapters),source=str(source.resolve()));checkpoint()
 completed=0;limit=config.get('chapter_limit_per_run',0) or len(chapters)
 for chapter in chapters:
  if time.time()>settings.get('_deadline',float('inf'))-120:raise Pending('Download time budget reached; chapter receipts preserved',time.time()+60)
  safe=re.sub(r'[\\/*?:"<>|]','_',chapter['name']);dest=source/safe
  if not dest.resolve().is_relative_to(source.resolve()):raise Attention('Downloader produced unsafe chapter path')
  receipt=Path(job['directory'])/'downloads'/(digest(chapter['url'])+'.json');old=read(receipt)
  if old and old.get('complete'):
   files=old['files'];expected=old['expected_pages'];saved=settings.get('_saved_files',{})
   if expected>0 and len(files)==expected and all(
    Path(f['path']).stem==f'{n:03}' and Path(f['path']).name==f['path'] and Path(f['path']).suffix.lower() in {'.png','.webp','.jpg','.jpeg'} and
    saved.get((dest/f['path']).relative_to(root).as_posix(),{}).get('sha256')==f['sha256'] for n,f in enumerate(files,1)):
    completed+=1;continue
   current=verified_images(dest,old['expected_pages'])
   if current==old['files']:completed+=1;continue
  urls=scraper.get_chapter_images(chapter['url'])
  if not urls:raise Pending('Missing page list for '+chapter['name'],time.time()+3600)
  for page in dest.glob('*'):
   if page.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}:
    try:
     with Image.open(page) as im:im.load()
    except (OSError,ValueError):page.rename(page.with_name(page.name+'.corrupt'))
  count,directory=scraper.download_chapter(chapter);files=verified_images(dest,len(urls));result=dict(chapter=chapter['name'],url=chapter['url'],expected_pages=len(urls),files=files or [],complete=files is not None);save(receipt,result)
  job['downloaded_chapters']=completed+int(result['complete']);checkpoint()
  if not result['complete']:raise Pending('Partial chapter saved; will retry '+chapter['name'],time.time()+600)
  if any(p.suffix.lower()=='.gif' for p in dest.glob('*')):raise Attention('A GIF page requires an explicit conversion adapter before source inventory')
  completed+=1;limit-=1
  if limit<=0:break
 job['downloaded_chapters']=completed
 # Count every verified receipt, including already-downloaded later chapters.
 receipts=[read(p) for p in (Path(job['directory'])/'downloads').glob('*.json')];job['downloaded_chapters']=sum(r.get('complete',False) for r in receipts)
 job['source']=str(source.resolve())
 return job['downloaded_chapters']==len(chapters)
