"""Resumable YouTube publishing; receipts stay in private persistent storage."""
import json,os,time,re
from pathlib import Path
from urllib.parse import urlparse
from .core import read,save,sha,utc,Attention,Pending

def queue(root):
 root=Path(root);config=read(root/'config.json');entries=[]
 for path in sorted((root/'parts').glob('*/complete.json')):
  part=read(path);scope=read(path.parent/'scope.json');chapters=[str(c) for u in scope['units'] for c in u['chapters']]
  title=f"{config['title']} — Part {int(path.parent.name.split('-')[-1])}"
  if chapters:title+=f" | Chapters {chapters[0]}–{chapters[-1]}"
  receipt=read(path.parent/'youtube-upload.json',{})
  entries.append(dict(part=path.parent.name,path=part['path'],sha256=part['sha256'],title=title[:100],description=f"Manga recap: {config['title']}. Chapters "+', '.join(chapters)+'.',privacy=config.get('youtube',{}).get('privacy','private'),state=receipt.get('state','queued')))
 save(root/'upload-queue.json',{'automatic_upload_enabled':config.get('youtube',{}).get('enabled',False),'videos':entries});return entries

def session():
 from google.oauth2.credentials import Credentials
 from google.auth.transport.requests import AuthorizedSession
 return AuthorizedSession(Credentials.from_authorized_user_info(json.loads(os.environ['YOUTUBE_TOKEN_JSON'])))

def response_ok(response):
 if response.status_code in (200,201,308):return
 if response.status_code in (429,500,502,503,504):raise Pending('YouTube temporarily unavailable',time.time()+3600)
 if response.status_code==403 and any(s in response.text for s in ('quotaExceeded','uploadLimitExceeded','dailyLimitExceeded')):raise Pending('YouTube quota exhausted',time.time()+86400)
 raise Attention('YouTube authorization or upload rejected; HTTP '+str(response.status_code))

def upload(video,receipt_path,expected_channel,checkpoint,client,deadline=float('inf'),chunk_bytes=64*1024*1024):
 """Probe before resending. Never restart an expired session automatically."""
 receipt_path=Path(receipt_path);record=read(receipt_path,{})
 if record.get('state')=='uploaded':return record
 if video['privacy'] not in ('private','unlisted','public'):raise Attention('Invalid YouTube privacy setting')
 if not expected_channel:raise Attention('Expected YouTube channel is required')
 check=client.get('https://www.googleapis.com/youtube/v3/channels',params={'part':'id','mine':'true'},timeout=60);response_ok(check)
 if expected_channel not in [c['id'] for c in check.json().get('items',[])]:raise Attention('YouTube account does not match the configured channel')
 path=Path(video['path']);total=path.stat().st_size
 if sha(path)!=video['sha256']:raise Attention('Completed video checksum changed')
 binding={'sha256':video['sha256'],'channel':expected_channel,'privacy':video['privacy']}
 if record.get('sha256') and any(record.get(k)!=v for k,v in binding.items()):raise Attention('Upload identity changed; review the saved receipt')
 def persist(**fields):record.update(**fields);save(receipt_path,record);checkpoint()
 if record.get('state') in ('initiating_unknown','needs_review'):raise Attention('Upload outcome needs review before retrying')
 if not record.get('session'):
  persist(**binding,state='initiating_unknown',offset=0)
  result=client.post('https://www.googleapis.com/upload/youtube/v3/videos',params={'uploadType':'resumable','part':'snippet,status'},json={'snippet':{'title':video['title'],'description':video['description'],'categoryId':'22'},'status':{'privacyStatus':video['privacy'],'selfDeclaredMadeForKids':False}},headers={'X-Upload-Content-Length':str(total),'X-Upload-Content-Type':'video/mp4'},timeout=90,allow_redirects=False)
  if result.status_code not in (200,201):persist(state='queued')
  response_ok(result)
  location=result.headers.get('Location','');parsed=urlparse(location)
  if parsed.scheme!='https' or parsed.hostname!='www.googleapis.com' or not parsed.path.startswith('/upload/'):raise Attention('Invalid resumable upload location')
  persist(session=location,state='uploading')
 location=record['session'];parsed=urlparse(location)
 if parsed.scheme!='https' or parsed.hostname!='www.googleapis.com' or not parsed.path.startswith('/upload/'):raise Attention('Invalid saved upload location')
 result=client.put(location,data=b'',headers={'Content-Length':'0','Content-Range':f'bytes */{total}'},timeout=90,allow_redirects=False)
 def accept(result):
  if result.status_code in (404,410):
   persist(state='needs_review');raise Attention('YouTube session expired; review before starting another upload')
  response_ok(result)
  if result.status_code in (200,201):
   data=result.json()
   if not data.get('id'):raise Attention('YouTube completion response has no video ID')
   persist(state='uploaded',video_id=data['id'],completed_utc=utc(),offset=total,session=None);return True
  match=re.fullmatch(r'bytes=0-(\d+)',result.headers.get('Range',''))
  offset=int(match[1])+1 if match else 0
  if not 0<=offset<total:raise Attention('Invalid YouTube upload offset')
  persist(offset=offset);return False
 if accept(result):return record
 if chunk_bytes<=0 or chunk_bytes%(256*1024):raise ValueError('Upload chunks must be multiples of 256 KiB')
 with path.open('rb') as source:
  while record['offset']<total:
   if time.time()>deadline:raise Pending('Upload saved for the next worker run',time.time()+60)
   start=record['offset'];source.seek(start);data=source.read(chunk_bytes)
   persist(final_may_have_been_sent=start+len(data)==total)
   result=client.put(location,data=data,headers={'Content-Length':str(len(data)),'Content-Type':'video/mp4','Content-Range':f'bytes {start}-{start+len(data)-1}/{total}'},timeout=180,allow_redirects=False)
   if accept(result):return record
   if record['offset']<=start:raise Pending('YouTube upload made no progress',time.time()+300)

def publish(root,cfg,snapshot):
 options=cfg.get('youtube',{});entries=queue(root)
 if not options.get('enabled') or not os.environ.get('YOUTUBE_TOKEN_JSON') or not os.environ.get('YOUTUBE_CHANNEL_ID'):return
 for video in entries:
  if video['state']=='uploaded':continue
  if cfg.get('_uploads',0)>=options.get('max_uploads_per_run',1):break
  receipt=Path(root)/'parts'/video['part']/'youtube-upload.json';prior=read(receipt,{})
  if prior.get('resume_epoch',0)>time.time() or prior.get('state') in ('needs_review','initiating_unknown'):continue
  try:
   snapshot.ensure_path(Path(video['path']))
   with session() as client:upload(video,receipt,os.environ['YOUTUBE_CHANNEL_ID'],snapshot.checkpoint,client,cfg.get('_deadline',float('inf')))
   cfg['_uploads']=cfg.get('_uploads',0)+1
  except Pending as exc:
   prior=read(receipt,{});prior.update(reason=exc.reason,resume_epoch=exc.resume);save(receipt,prior);snapshot.checkpoint();break
  except Exception as exc:
   prior=read(receipt,{});prior.update(reason=str(exc) if isinstance(exc,Attention) else type(exc).__name__,resume_epoch=time.time()+3600);save(receipt,prior);snapshot.checkpoint();break
 queue(root)
