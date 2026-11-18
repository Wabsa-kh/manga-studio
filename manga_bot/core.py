import contextlib,hashlib,json,os,re,sqlite3,time,uuid
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from series_inventory import chapter_sort

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def read(path,default=None):return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default
def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 temp.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8');os.replace(temp,path)
def utc():return datetime.now(timezone.utc).isoformat()

def event(root,kind,**fields):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 with (root/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(utc=utc(),event=kind,**fields),ensure_ascii=False)+'\n')

class Pending(Exception):
 def __init__(self,reason,resume=None):super().__init__(reason);self.reason=reason;self.resume=resume or time.time()+60
class Attention(Exception):pass

class Singleton:
 def __init__(self,path):self.path=Path(path);self.f=None
 def __enter__(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);self.f=self.path.open('a+b');self.f.seek(0);self.f.write(b'0');self.f.flush();self.f.seek(0)
  try:
   if os.name=='nt':
    import msvcrt;msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl;fcntl.flock(self.f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:self.f.close();raise Attention('Another worker already owns this job')
  return self
 def __exit__(self,*args):
  self.f.seek(0)
  if os.name=='nt':
   import msvcrt;msvcrt.locking(self.f.fileno(),msvcrt.LK_UNLCK,1)
  else:
   import fcntl;fcntl.flock(self.f,fcntl.LOCK_UN)
  self.f.close()

def quota_day(now=None):return datetime.fromtimestamp(now or time.time(),ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d')
def next_reset(now=None):
 dt=datetime.fromtimestamp(now or time.time(),ZoneInfo('America/Los_Angeles'));return (dt.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).timestamp()+2

def units_for(pages,max_pages=40,max_bytes=50*1024*1024):
 """Keep physical chapter parts together when possible; preserve exact labels."""
 majors={}
 for p in pages:majors.setdefault(str(p['chapter']).split('.')[0],[]).append(p)
 chunks=[]
 for group in majors.values():
  current=[];size=0
  for p in group:
   n=Path(p['path']).stat().st_size
   if n>max_bytes:raise Attention('One original page exceeds the configured inline-image bound')
   if current and (len(current)>=max_pages or size+n>max_bytes):chunks.append(current);current=[];size=0
   current.append(p);size+=n
  if current:chunks.append(current)
 result=[];current=[];size=0
 for group in chunks:
  n=sum(Path(p['path']).stat().st_size for p in group)
  if current and (len(current)+len(group)>max_pages or size+n>max_bytes):result.append(current);current=[];size=0
  current+=group;size+=n
 if current:result.append(current)
 return [dict(id=f'unit-{i+1:04}',pages=g,chapters=list(dict.fromkeys(str(p['chapter']) for p in g))) for i,g in enumerate(result)]

def choose_part(units,minimum=45,maximum=60,wpm=207,at_end=False):
 """Model hints select among real chapter/unit boundaries; never rewrite a cliffhanger."""
 low=minimum*wpm;high=maximum*wpm;total=0;candidates=[]
 for i,u in enumerate(units):
  total+=u.get('duration_minutes',u['words']/wpm)*wpm
  if low<=total<=high:
   hint=u.get('boundary',{});score=hint.get('score',2);utility=score*2-abs(total/wpm-(minimum+maximum)/2)/7
   candidates.append((utility,i+1,total))
   if score>=4 and total>=((minimum+maximum)/2)*wpm:return i+1
  if total>high:
   if candidates:return max(candidates)[1]
   # A very large unit is handled at a bounded exception rather than dropped.
   return max(1,i)
 if at_end and units:return max(candidates)[1] if candidates else len(units)
 return None

class Budget:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as db:db.executescript('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,model TEXT,day TEXT,at REAL,status TEXT,tokens INTEGER);CREATE TABLE IF NOT EXISTS holds(model TEXT PRIMARY KEY,until_epoch REAL,reason TEXT,permanent INTEGER);')
 @contextlib.contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=30);db.execute('PRAGMA busy_timeout=30000')
  try:
   with db:yield db
  finally:db.close()
 def hold(self,model):
  with self.db() as db:row=db.execute('SELECT until_epoch,reason,permanent FROM holds WHERE model=?',(model,)).fetchone()
  if row and row[2]:raise Attention(row[1])
  if row and row[0]>time.time():raise Pending(row[1],row[0])
 def reserve(self,model,rpd,rpm,shared_prefix=None,shared_rpm=None,shared_daily=None):
  self.hold(model);now=time.time()
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');n=db.execute('SELECT count(*) FROM calls WHERE model=? AND day=?',(model,quota_day(now))).fetchone()[0]
   if shared_prefix:
    prefix=(len(shared_prefix),shared_prefix)
    if shared_daily is not None and db.execute('SELECT count(*) FROM calls WHERE substr(model,1,?)=? AND day=?',(*prefix,quota_day(now))).fetchone()[0]>=shared_daily:raise Pending('Shared provider daily allowance reached',next_reset(now))
    recent=db.execute('SELECT at FROM calls WHERE substr(model,1,?)=? AND at>? ORDER BY at',(*prefix,now-60)).fetchall()
    if shared_rpm is not None and len(recent)>=shared_rpm:raise Pending('Shared provider request pacing',recent[0][0]+61)
   if n>=rpd:raise Pending('Local conservative daily request allowance reached for '+model,next_reset(now))
   starts=db.execute('SELECT at FROM calls WHERE model=? AND at>? ORDER BY at',(model,now-60)).fetchall()
   if len(starts)>=rpm:raise Pending('Request pacing for '+model,starts[0][0]+61)
   ident=uuid.uuid4().hex;db.execute('INSERT INTO calls VALUES(?,?,?,?,?,NULL)',(ident,model,quota_day(now),now,'reserved'));return ident
 def settle(self,ident,status,tokens=None):
  with self.db() as db:db.execute('UPDATE calls SET status=?,tokens=? WHERE id=?',(str(status),tokens,ident))
 def set_hold(self,model,reason,until=None,permanent=False):
  with self.db() as db:db.execute('INSERT OR REPLACE INTO holds VALUES(?,?,?,?)',(model,until or 0,reason,int(permanent)))
 def summary(self):
  with self.db() as db:
   return [dict(model=r[0],day=r[1],requests=r[2],reported_tokens=r[3]) for r in db.execute('SELECT model,day,count(*),sum(tokens) FROM calls GROUP BY model,day')]
