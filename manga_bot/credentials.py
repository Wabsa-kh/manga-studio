"""Private credentials and durable rotation; quota identity is separate from key identity."""
import json,os,re,time,threading,uuid
from .core import Budget,Pending,Attention,next_reset,digest

LOCK=threading.RLock()
class QuotaWait(Pending):pass
class CredentialRejected(Pending):pass
class ServiceWait(Pending):pass
class ContentRejected(Attention):pass

def load_credentials():
 raw=os.environ.get('MODEL_CREDENTIALS_JSON')
 if raw:
  try:rows=json.loads(raw)['credentials']
  except (ValueError,KeyError,TypeError):raise Attention('MODEL_CREDENTIALS_JSON must contain a credentials array')
 else:
  rows=[dict(id=provider+'-primary',provider=provider,api_key=os.environ[name]) for provider,name in [('google','GEMINI_API_KEY'),('nim','NVIDIA_API_KEY'),('openrouter','OPENROUTER_API_KEY')] if os.environ.get(name)]
 if not isinstance(rows,list):raise Attention('Credentials must be a list')
 output=[];seen=set();keys=set()
 for row in rows:
  if not isinstance(row,dict):raise Attention('Invalid credential record')
  if not row.get('enabled',True):continue
  ident=row.get('id','');provider=row.get('provider');key=row.get('api_key','')
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in seen or provider not in ('google','nim','openrouter') or not isinstance(key,str) or len(key)<8:raise Attention('Invalid or duplicate credential ID/provider/key')
  seen.add(ident)
  if key in keys:continue
  keys.add(key)
  # Unmapped Google keys share a conservative bucket. OpenRouter limits are
  # global; declaring new key/account labels must never invent extra capacity.
  project=row.get('project_id','') if provider=='google' else ''
  if project and not re.fullmatch(r'[A-Za-z0-9_-]{3,80}',project):raise Attention('Invalid Google project identifier')
  declared=row.get('quota_group','') if provider=='google' and row.get('scope_evidence')=='owner_reported_separate_account' else ''
  if declared and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',declared):raise Attention('Invalid credential quota label')
  group=project or declared or ('global' if provider=='openrouter' else 'unmapped')
  output.append(dict(id=ident,provider=provider,api_key=key,quota_group=group,project_id=project,scope_mapping='configured_project' if project else ('owner_reported_separate_account' if declared else 'shared_unmapped')))
 # An unknown key might belong to a known project. Do not count those as
 # independent pools until every enabled Google key has a consistent mapping.
 if any(r['provider']=='google' and r['quota_group']=='unmapped' for r in output):
  for r in output:
   if r['provider']=='google':r.update(quota_group='unmapped',scope_mapping='shared_until_all_projects_mapped')
 return output

class Pool:
 def __init__(self,budget,limits=None):
  self.budget=budget;self.rows=load_credentials();self.limits={'nim':{'rpm':24,'daily_requests':500},'openrouter':{'rpm':20,'daily_requests':50}}
  for provider,settings in (limits or {}).items():
   if provider not in self.limits:raise Attention('Unknown shared quota provider')
   for field in ('rpm','daily_requests'):
    value=settings.get(field,self.limits[provider][field])
    if type(value) is not int or value<=0:raise Attention('Shared quota limits must be positive integers')
    self.limits[provider][field]=value
  with self.budget.db() as db:db.executescript('CREATE TABLE IF NOT EXISTS credential_selections(id TEXT PRIMARY KEY,credential TEXT,at REAL);CREATE TABLE IF NOT EXISTS credential_holds(credential TEXT PRIMARY KEY,reason TEXT);CREATE TABLE IF NOT EXISTS credential_scopes(credential TEXT PRIMARY KEY,project TEXT,evidence TEXT);CREATE TABLE IF NOT EXISTS credential_reservations(reservation TEXT PRIMARY KEY,credential TEXT);')
 def candidates(self,provider):
  with self.budget.db() as db:
   blocked={r[0] for r in db.execute('SELECT credential FROM credential_holds')};last=dict(db.execute('SELECT credential,max(at) FROM credential_selections GROUP BY credential'))
  return sorted([r for r in self.rows if r['provider']==provider and r['id']+':'+digest(r['api_key'])[:16] not in blocked],key=lambda r:(last.get(r['id'],0),r['id']))
 def selected(self,row):
  with self.budget.db() as db:db.execute('INSERT INTO credential_selections VALUES(?,?,?)',(uuid.uuid4().hex,row['id'],time.time()))
 def reject(self,row):
  with self.budget.db() as db:db.execute('INSERT OR REPLACE INTO credential_holds VALUES(?,?)',(row['id']+':'+digest(row['api_key'])[:16],'Credential rejected with HTTP 401; replace or review'))
 def identity(self,row):return row['id']+':'+digest(row['api_key'])[:16]
 def group(self,row):
  with self.budget.db() as db:known=dict(db.execute('SELECT credential,project FROM credential_scopes'))
  if row['provider']=='google' and any(r['provider']=='google' and r['quota_group']=='unmapped' and not r.get('project_id') and self.identity(r) not in known for r in self.rows):return 'unmapped'
  return known.get(self.identity(row),row.get('project_id') or row['quota_group'])
 def scope(self,row,model):return row['provider']+'|'+self.group(row)+'|'+model
 def observe(self,row,body):
  if row['provider']!='google':return
  try:
   data=json.loads(body);details=data.get('error',{}).get('details',[])
   project=next((re.fullmatch(r'projects/(\d+)',detail.get('metadata',{}).get('consumer','')) for detail in details if detail.get('@type','').endswith('ErrorInfo') and re.fullmatch(r'projects/(\d+)',detail.get('metadata',{}).get('consumer',''))),None)
  except (ValueError,AttributeError,TypeError):return
  if not project:return
  number=project[1];old=self.group(row);before='google|'+old+'|'
  with LOCK,self.budget.db() as db:
   db.execute('INSERT OR REPLACE INTO credential_scopes VALUES(?,?,?)',(self.identity(row),number,'Google ErrorInfo consumer'))
  # Move only reservations attributed to each credential, preserving totals
  # when observed project identities merge previously separate account labels.
  with LOCK,self.budget.db() as db:
   for candidate in [r for r in self.rows if r['provider']=='google']:
    after='google|'+self.group(candidate)+'|'
    for ident,model in db.execute('SELECT calls.id,calls.model FROM calls JOIN credential_reservations ON calls.id=credential_reservations.reservation WHERE credential_reservations.credential=?',(self.identity(candidate),)).fetchall():
     suffix=model.split('|',2)[-1];db.execute('UPDATE calls SET model=? WHERE id=?',(after+suffix,ident))
   after='google|'+self.group(row)+'|'
   if before!=after:
    for model,until,reason,permanent in db.execute('SELECT model,until_epoch,reason,permanent FROM holds WHERE substr(model,1,?)=?',(len(before),before)).fetchall():
     new=after+model[len(before):];db.execute('INSERT INTO holds VALUES(?,?,?,?) ON CONFLICT(model) DO UPDATE SET until_epoch=max(until_epoch,excluded.until_epoch),permanent=max(permanent,excluded.permanent)',(new,until,reason,permanent))
 def reserve(self,row,model,rpd,rpm):
  scope=self.scope(row,model);provider=row['provider']
  # Conservatively migrate pre-pool usage into the first scope that consumes it.
  with LOCK,self.budget.db() as db:
   db.execute('UPDATE calls SET model=? WHERE model=?',(scope,model))
   old=db.execute('SELECT until_epoch,reason,permanent FROM holds WHERE model=?',(model,)).fetchone()
   if old:db.execute('INSERT OR IGNORE INTO holds VALUES(?,?,?,?)',(scope,*old));db.execute('DELETE FROM holds WHERE model=?',(model,))
  try:
   self.budget.hold('service|'+provider+'|'+model)
   limits=self.limits.get(provider,{})
   ident=self.budget.reserve(scope,rpd,rpm,shared_prefix=provider+'|' if provider!='google' else None,shared_rpm=limits.get('rpm'),shared_daily=limits.get('daily_requests'))
   with self.budget.db() as db:db.execute('INSERT INTO credential_reservations VALUES(?,?)',(ident,self.identity(row)))
   return ident
  except Pending as exc:raise QuotaWait(exc.reason,exc.resume)

def retry_epoch(headers,default=60):
 from email.utils import parsedate_to_datetime
 for key,value in headers.items():
  if key.lower()=='retry-after':
   try:return time.time()+max(1,float(value))
   except ValueError:
    try:return max(time.time()+1,parsedate_to_datetime(value).timestamp())
    except (ValueError,TypeError):pass
  if key.lower() in ('x-ratelimit-reset','x-ratelimit-reset-requests'):
   try:
    stamp=float(value);stamp=stamp/1000 if stamp>1e12 else stamp
    if stamp>time.time():return stamp
   except ValueError:pass
 return time.time()+default

def http_error(pool,row,model,status,body,headers):
 provider=row['provider'];pool.observe(row,body);scope=pool.scope(row,model)
 if status==401:pool.reject(row);raise CredentialRejected('Credential rejected and quarantined',time.time()+3600)
 if status==429:
  daily=any(x in body.lower() for x in ('per_day','perday','per day','daily'))
  until=retry_epoch(headers,default=max(60,next_reset()-time.time()) if daily else 60)
  pool.budget.set_hold(scope,'Observed provider quota cooldown',until)
  # OpenRouter documents global caps; do not retry its free pool using another key.
  if provider=='openrouter':pool.budget.set_hold('service|'+provider+'|'+model,'OpenRouter shared limit',until)
  raise QuotaWait('Provider quota cooldown for '+provider,until)
 if status in (408,404,500,502,503,504):
  until=retry_epoch(headers,60);pool.budget.set_hold('service|'+provider+'|'+model,'Known service/model unavailability',until);raise ServiceWait('Service unavailable: '+provider,until)
 if status in (402,403):raise Attention('Provider payment/access rejected; review required, no key cycling')
 raise Attention('Provider rejected request: HTTP '+str(status))
