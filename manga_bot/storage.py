"""Immutable blobs plus a publish-last manifest for restorable worker state."""
import json,os,shutil,subprocess,tempfile,threading,time,sqlite3,uuid
from pathlib import Path,PurePosixPath
from .core import save,read,sha,digest,Attention

def key(value):
 p=PurePosixPath(value)
 if p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value or '\n' in value or '\r' in value:raise ValueError('Unsafe storage key')
 return p.as_posix()

class LocalStore:
 def __init__(self,root):self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
 def put(self,source,name):
  path=self.root/key(name);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.upload');shutil.copyfile(source,temp);os.replace(temp,path)
 def get(self,name,target):
  source=self.root/key(name)
  if not source.exists():return False
  Path(target).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);return True

class StorageFailure(Attention):
 """Only an allowlisted category may enter public worker diagnostics."""
 def __init__(self,code,private_details=''):
  self.code=code;self.private_details=private_details
  messages={
   'storage_rate_limited':'Persistent storage is rate limited; saved checkpoints remain intact. Review Drive app quota and retry later.',
   'storage_full':'Persistent storage is full; free space or connect more storage before continuing.',
   'storage_authorization':'Persistent storage authorization needs renewal or permission review.',
   'storage_timeout':'Persistent storage timed out; no generation dispatched before checkpoint acknowledgement.',
   'storage_operation_failed':'Persistent storage operation failed. Generation cannot continue until storage is acknowledged.'}
  super().__init__(messages[code])

def storage_failure(stderr):
 details=stderr.decode('utf-8',errors='replace') if isinstance(stderr,bytes) else str(stderr);text=details.lower()
 if any(s in text for s in ('storagequotaexceeded','storage quota has been exceeded','no space left')):code='storage_full'
 elif any(s in text for s in ('ratelimitexceeded','rate limit exceeded','quota metric','too many requests','429')):code='storage_rate_limited'
 elif any(s in text for s in ('invalid_client','invalid_grant','unauthorized','insufficientpermissions','insufficient authentication scopes','access denied')):code='storage_authorization'
 else:code='storage_operation_failed'
 return StorageFailure(code,details[-12000:])

class RcloneStore:
 def __init__(self,remote):
  if not remote or ':' not in remote:raise Attention('MANGA_STORE_REMOTE is not configured')
  self.remote=remote.rstrip('/');self.config=None
  if os.environ.get('MANGA_RCLONE_CONFIG'):
   handle=tempfile.NamedTemporaryFile(prefix='manga-rclone-',suffix='.conf',delete=False);handle.write(os.environ['MANGA_RCLONE_CONFIG'].encode());handle.close();self.config=Path(handle.name);self.config.chmod(0o600)
  self.command(['mkdir',self.remote])
 def command(self,args):
  cmd=['rclone',*( ['--config',str(self.config)] if self.config else []),*args,'--retries','3','--low-level-retries','3','--contimeout','30s','--timeout','2m','--tpslimit','2','--tpslimit-burst','1']
  try:r=subprocess.run(cmd,capture_output=True,timeout=600)
  except subprocess.TimeoutExpired:raise StorageFailure('storage_timeout') from None
  if r.returncode:raise storage_failure(r.stderr)
 def put(self,source,name):self.command(['copyto',str(source),self.remote+'/'+key(name)])
 def put_many(self,entries):
  with tempfile.TemporaryDirectory(prefix='manga-bulk-put-') as folder:
   root=Path(folder)
   for source,name in entries:
    target=root/key(name);target.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,target)
    except OSError:shutil.copyfile(source,target)
   self.command(['copy',str(root),self.remote,'--immutable','--checksum','--fast-list','--transfers','4','--checkers','4'])
 def get_many(self,entries):
  with tempfile.TemporaryDirectory(prefix='manga-bulk-get-') as folder:
   root=Path(folder);listing=root/'files.txt';listing.write_text(''.join(key(name)+'\n' for name,_ in entries),encoding='utf-8');staged=root/'data'
   self.command(['copy',self.remote,str(staged),'--files-from-raw',str(listing),'--fast-list','--transfers','4','--checkers','4'])
   if not all((staged/key(name)).is_file() for name,_ in entries):return False
   for name,target in entries:
    Path(target).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(staged/key(name),target)
   return True
 def get(self,name,target):
  Path(target).parent.mkdir(parents=True,exist_ok=True)
  try:self.command(['copyto',self.remote+'/'+key(name),str(target)]);return True
  except Attention:
   # Distinguish a genuinely absent initial pointer from an inaccessible store.
   r=subprocess.run(['rclone',*( ['--config',str(self.config)] if self.config else []),'lsf',self.remote,'--max-depth','1'],capture_output=True,timeout=120)
   if r.returncode==0 and name=='refs/latest.json' and b'refs/' not in r.stdout:return False
   raise
 def close(self):
  if self.config and self.config.exists():self.config.unlink()

def eligible(path):
 forbidden={'private','auth','secrets','__pycache__','.git','local-model-cache','vendors'}
 return not any(p.lower() in forbidden for p in path.parts) and not any(x in path.name.lower() for x in ['.tmp','.partial','.lock','.sqlite','credentials','token','keys.txt','.env'])

class Snapshot:
 def __init__(self,root,store,lazy_upscale=False,lazy_media=False,lazy_source=False):self.original_root=str(Path(root).absolute());self.root=Path(root).resolve();self.store=store;self.lock=threading.Lock();self.known=set();self.last=None;self.file_cache={};self.entries={};self.retained=set();self.lazy_upscale=lazy_upscale;self.lazy_media=lazy_media;self.lazy_source=lazy_source
 def lazy(self,path):
  path=Path(path)
  return (self.lazy_source or self.lazy_upscale and 'upscaled' in path.parts) and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} or self.lazy_media and path.suffix.lower() in {'.mp4','.wav','.flac','.ogg'}
 def ensure_path(self,path,missing_ok=False):
  path=Path(path).resolve()
  if not path.is_relative_to(self.root):raise Attention('Asset is outside the managed state folder')
  rel=path.relative_to(self.root).as_posix();row=self.entries.get(rel)
  if not row:
   if path.exists() or missing_ok:return path.exists()
   raise Attention('Asset has no durable checkpoint receipt: '+rel)
  if path.exists() and sha(path)==row['sha256']:return True
  with tempfile.TemporaryDirectory(prefix='manga-hydrate-') as temp:
   staged=Path(temp)/'asset';h=row['sha256']
   if not self.store.get('objects/'+h[:2]+'/'+h[2:],staged) or sha(staged)!=h:raise Attention('Saved asset is missing/corrupt: '+rel)
   path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(staged,path)
  return True
 def evict_path(self,path):
  path=Path(path).resolve()
  if not path.is_relative_to(self.root):raise Attention('Refusing to evict an external asset')
  rel=path.relative_to(self.root).as_posix();row=self.entries.get(rel)
  if not self.lazy(rel) or not row or row['sha256'] not in self.known:raise Attention('Refusing to evict an asset without an acknowledged durable copy')
  if path.exists():
   if sha(path)!=row['sha256']:raise Attention('Local asset changed since durable checkpoint')
   path.unlink()
  self.retained.add(rel)
 def checkpoint(self):
  with self.lock:
   self.root.mkdir(parents=True,exist_ok=True)
   # SQLite backup is transactionally consistent, unlike copying an open DB.
   for db in list(self.root.rglob('*.sqlite')):
    if not eligible(db.with_suffix('.dbsnapshot').relative_to(self.root)):continue
    snap=db.with_suffix('.dbsnapshot');source=sqlite3.connect(db,timeout=30);dest=sqlite3.connect(snap)
    try:source.backup(dest)
    finally:dest.close();source.close()
   files={name:self.entries[name] for name in self.retained if name in self.entries}
   with tempfile.TemporaryDirectory(prefix='manga-checkpoint-') as temp:
    uploads={}
    for source in sorted(self.root.rglob('*')):
     rel=source.relative_to(self.root)
     if not source.is_file() or not eligible(rel):continue
     # Freeze the bytes before hashing/uploading; concurrent reader receipts
     # are atomic JSON writes but may advance while a checkpoint is uploading.
     stat=source.stat();stamp=(stat.st_size,stat.st_mtime_ns);cached=self.file_cache.get(rel.as_posix())
     if cached and cached[0]==stamp and cached[1] in self.known:h=cached[1]
     else:
      frozen=Path(temp)/uuid.uuid4().hex;shutil.copyfile(source,frozen);h=sha(frozen);name='objects/'+h[:2]+'/'+h[2:]
      if h not in self.known and h not in uploads:uploads[h]=(frozen,name)
      self.file_cache[rel.as_posix()]=(stamp,h)
     files[rel.as_posix()]=dict(path=rel.as_posix(),sha256=h,size=stat.st_size)
    if uploads:
     if hasattr(self.store,'put_many'):self.store.put_many(list(uploads.values()))
     else:
      for frozen,name in uploads.values():self.store.put(frozen,name)
     self.known.update(uploads)
    manifest=dict(version=1,created=time.time(),root_hint=str(self.root),root_aliases=list({str(self.root),self.original_root}),files=list(files.values()));mp=Path(temp)/'manifest.json';save(mp,manifest);h=sha(mp);self.store.put(mp,'manifests/'+h+'.json');pointer=Path(temp)/'pointer.json';save(pointer,{'manifest_sha256':h})
    if self.last:
     previous=Path(temp)/'previous.json';save(previous,self.last);self.store.put(previous,'refs/previous.json')
    self.store.put(pointer,'refs/latest.json');self.last=read(pointer);self.entries=files;return manifest
 def restore(self):
  self.root.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='manga-restore-') as temp:
   pointer=Path(temp)/'pointer.json'
   if not self.store.get('refs/latest.json',pointer):return False
   info=read(pointer);h=info['manifest_sha256'];mp=Path(temp)/'manifest.json';self.store.get('manifests/'+h+'.json',mp)
   if sha(mp)!=h:raise Attention('Checkpoint manifest checksum mismatch')
   manifest=read(mp);self.entries={row['path']:row for row in manifest['files']};self.retained=set()
   downloads=[]
   for row in manifest['files']:
    rel=key(row['path']);target=(self.root/rel).resolve()
    if not target.is_relative_to(self.root) or not eligible(Path(rel)):raise Attention('Unsafe checkpoint path')
    if self.lazy(rel):
     self.retained.add(rel);self.known.add(row['sha256'])
     if target.exists() and sha(target)!=row['sha256']:target.unlink()
     continue
    if target.exists() and sha(target)==row['sha256']:self.known.add(row['sha256']);continue
    staged=Path(temp)/row['sha256'];blob='objects/'+row['sha256'][:2]+'/'+row['sha256'][2:];downloads.append((row,target,staged,blob))
   if downloads:
    entries=list({blob:(blob,staged) for _,_,staged,blob in downloads}.values())
    if hasattr(self.store,'get_many'):
     if not self.store.get_many(entries):raise Attention('Checkpoint bulk restore has missing blobs')
    else:
     for blob,staged in entries:
      if not self.store.get(blob,staged):raise Attention('Checkpoint blob missing: '+blob)
   for row,target,staged,_ in downloads:
    if sha(staged)!=row['sha256']:raise Attention('Checkpoint blob corrupt: '+row['path'])
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(staged,target);self.known.add(row['sha256'])
   # Only restore DB snapshots when a local DB is absent. A live local worker
   # must never have its current transactions overwritten by older state.
   for snap in self.root.rglob('*.dbsnapshot'):
    db=snap.with_suffix('.sqlite')
    if not db.exists():shutil.copyfile(snap,db)
   for oldroot in manifest.get('root_aliases',[manifest.get('root_hint')]):rebase(self.root,oldroot)
   self.last=info;return True

def rebase(root,old):
 root=Path(root).resolve()
 if not old or old==str(root):return
 def convert(value):
  if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
  if isinstance(value,list):return [convert(v) for v in value]
  if isinstance(value,str) and (value.startswith(old+'/') or value.startswith(old+'\\')):return str(root)+value[len(old):].replace('\\','/')
  return value
 for path in root.rglob('*.json'):
  if eligible(path.relative_to(root)):
   before=read(path);after=convert(before)
   if before!=after:save(path,after)
