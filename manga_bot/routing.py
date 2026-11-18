"""Stage routing, credential rotation and fixed-host OpenAI-compatible adapters."""
import base64,json,mimetypes,os,re,time
from decimal import Decimal
from pathlib import Path
import requests
from .core import Budget,Pending,Attention,save,read,digest,sha,utc
from .credentials import Pool,QuotaWait,CredentialRejected,ServiceWait,ContentRejected,http_error,LOCK
from .providers import Google,MODELS
from storybench import redact
from efficient_pipeline import schema_errors

HOSTS={'nim':'https://integrate.api.nvidia.com/v1','openrouter':'https://openrouter.ai/api/v1'}

def schema_projection(value,schema,path='$',dropped=None):
 """Drop only schema-forbidden fields; preserve all permitted values verbatim."""
 dropped=[] if dropped is None else dropped
 if isinstance(value,dict):
  properties=schema.get('properties',{});result={}
  for key,item in value.items():
   if schema.get('additionalProperties') is False and key not in properties:dropped.append(path+'.'+key);continue
   child=properties.get(key,schema.get('additionalProperties',{}));child=child if isinstance(child,dict) else {}
   result[key]=schema_projection(item,child,path+'.'+key,dropped)
  return result
 if isinstance(value,list):return [schema_projection(item,schema.get('items',{}),path+'['+str(i)+']',dropped) for i,item in enumerate(value)]
 return value

class ScopedGoogle(Google):
 def __init__(self,root,shared,options,checkpoint,pool,row):
  super().__init__(root,shared,options,checkpoint,key_getter=lambda:row['api_key']);self.pool=pool;self.row=row
  self.strict_unknown=True
  self.audit={'provider':'google','credential_id':row['id'],'quota_group':pool.group(row),'scope_mapping':row['scope_mapping']}
 def before(self,model):return self.pool.reserve(self.row,model,*self.limits[model])
 def error(self,model,status,body,headers):http_error(self.pool,self.row,model,status,body,headers)

class Chat:
 def __init__(self,root,shared,checkpoint,pool,row,route):self.root=Path(root);self.shared=Path(shared);self.checkpoint=checkpoint;self.pool=pool;self.row=row;self.route=route
 def free_check(self):
  if self.row['provider']!='openrouter':return
  model=self.route['model']
  if not (model.endswith(':free') or model=='openrouter/free'):raise Attention('Only explicit free OpenRouter routes are allowed')
  # Router/free is explicitly the free-only selector. Named models must also
  # have zero token pricing in the current public catalog.
  if model=='openrouter/free':return
  path=self.shared/'model-catalog/openrouter.json';cache=read(path,{})
  if cache.get('checked_epoch',0)<time.time()-3600:
   try:
    response=requests.get(HOSTS['openrouter']+'/models',timeout=(20,45));response.raise_for_status();cache={'checked_epoch':time.time(),'data':response.json()['data']};save(path,cache)
   except (requests.RequestException,ValueError,KeyError):raise Pending('Free-model catalog unavailable; no unverified paid dispatch',time.time()+300)
  info=next((m for m in cache['data'] if m['id']==model),None)
  if not info or any(Decimal(str(info.get('pricing',{}).get(k,'-1')))!=0 for k in ('prompt','completion')):raise Attention('OpenRouter route is not confirmed free in its catalog')
 def generate(self,stage,system,payload,pages,schema,max_tokens,thinking=None):
  row=self.row;route=self.route;provider=row['provider'];model=route['model']
  config=dict(provider=provider,model=model,system=system,payload=payload,pages=[dict(page_id=p['page_id'],sha256=p['sha256']) for p in pages],schema=schema,max_tokens=min(max_tokens,route.get('max_tokens',24576)),thinking=thinking,images=route.get('images',True),adapter='chat-v1')
  folder=self.root/'requests'/digest(config);receipt=folder/'result.json';old=read(receipt,{})
  if old.get('complete') or old.get('known_incomplete'):
   dropped=[];old['output']=schema_projection(old.get('output'),schema,dropped=dropped)
   if dropped:old['schema_fields_omitted']=dropped;save(receipt,old)
   return old
  if old.get('fatal'):raise ContentRejected(old['reason'])
  if old.get('status')=='started_unknown':
   if old.get('retry_epoch',0)<=time.time():raise Attention('Unknown chat acceptance needs owner review; no cross-key/provider replay')
   raise Pending('Unknown chat acceptance cooling down; no cross-key/provider replay',old['retry_epoch'])
  if old.get('retry_epoch',0)>time.time() and old.get('credential_id')==row['id']:raise Pending('Saved chat cooldown',old['retry_epoch'])
  self.free_check()
  content=[{'type':'text','text':json.dumps(payload,ensure_ascii=False)+'\nReturn a JSON instance matching this schema. Never return the schema itself:\n'+json.dumps(schema)}]
  if route.get('images',True):
   for page in pages:
    if sha(page['path'])!=page['sha256']:raise Attention('Original page checksum changed')
    raw=Path(page['path']).read_bytes();mime=mimetypes.guess_type(page['path'])[0] or 'image/png'
    content.extend([{'type':'text','text':'Original page '+page['page_id']},{'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(raw).decode()}}])
  else:system+='\nImages are not included in this route. Use only the supplied extracted evidence and preserve its uncertainties; do not invent visual details.'
  body={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':content}],'max_tokens':config['max_tokens'],'temperature':route.get('temperature',.25 if stage=='reader' else .8),'stream':False}
  if provider=='nim' and route.get('reasoning_budget') is not None:body['reasoning_budget']=route['reasoning_budget']
  if provider=='nim' and 'enable_thinking' in route:body['chat_template_kwargs']={'enable_thinking':bool(route['enable_thinking'])}
  if 'top_p' in route:body['top_p']=route['top_p']
  if provider=='openrouter':
   body.update(response_format={'type':'json_object'},provider={'allow_fallbacks':False})
   if route.get('reasoning_effort'):body['reasoning']={'effort':route['reasoning_effort']}
  ident=self.pool.reserve(row,model,route.get('daily_requests',100),route.get('rpm',8))
  result=dict(config=config,status='started_unknown',started_epoch=time.time(),started_utc=utc(),reservation_id=ident,complete=False,provider=provider,credential_id=row['id'],quota_group=row['quota_group'])
  save(receipt,result);self.checkpoint();start=time.monotonic()
  try:
   response=requests.post(HOSTS[provider]+'/chat/completions',headers={'Authorization':'Bearer '+row['api_key'],'Accept':'application/json'},json=body,timeout=(30,route.get('timeout_seconds',180)))
   if provider=='nim' and response.status_code==202:
    request_id=response.headers.get('NVCF-REQID') or response.headers.get('X-Request-Id')
    if not request_id:
     data=response.json();request_id=data.get('requestId') or data.get('request_id')
    if not request_id or not re.fullmatch('[0-9a-fA-F-]{36}',request_id):raise requests.Timeout('Unresolved NIM acceptance')
    result['nim_request_id']=request_id;save(receipt,result);self.checkpoint()
    while response.status_code==202 and time.monotonic()-start<route.get('timeout_seconds',180):
     response.close();time.sleep(1);response=requests.get(HOSTS[provider]+'/status/'+request_id,headers={'Authorization':'Bearer '+row['api_key'],'Accept':'application/json'},timeout=(20,30))
    if response.status_code!=200:raise requests.Timeout('NIM accepted request has no confirmed completion')
   result['status']=response.status_code
   if not response.ok:
    message=redact(response.text,row['api_key']);result.update(reason='HTTP '+str(response.status_code),body=message[:8000],headers={k:v for k,v in response.headers.items() if k.lower()=='retry-after' or k.lower().startswith('x-ratelimit')},retry_epoch=time.time()+60);save(receipt,result);self.pool.budget.settle(ident,response.status_code);http_error(self.pool,row,model,response.status_code,message,dict(response.headers))
   data=response.json()
   if data.get('error'):raise Attention('Provider returned an error envelope; review required')
   choice=data.get('choices',[{}])[0];finish=choice.get('finish_reason');text=choice.get('message',{}).get('content') or ''
   if finish in ('content_filter','safety'):
    result.update(fatal=True,reason='Content screening rejected this logical request');raise ContentRejected(result['reason'])
   if isinstance(text,list):text=''.join(p.get('text','') for p in text if isinstance(p,dict))
   visible=text.strip()
   if visible.startswith('```'):visible=re.sub(r'^```(?:json)?\s*|\s*```$','',visible)
   try:output=json.loads(visible)
   except ValueError:output=None
   dropped=[];output=schema_projection(output,schema,dropped=dropped);complete=finish=='stop' and output is not None
   usage=data.get('usage',{});result.update(text=text,output=output,finish=finish,complete=complete,known_incomplete=not complete,usage=usage,schema_fields_omitted=dropped,seconds=round(time.monotonic()-start,2))
   self.pool.budget.settle(ident,200,usage.get('total_tokens'));save(receipt,result);self.checkpoint();return result
  except (Pending,Attention):save(receipt,result);self.checkpoint();raise
  except (requests.RequestException,ValueError,IndexError,KeyError):
   result.update(status='started_unknown',reason='Unknown transport/response outcome',retry_epoch=time.time()+3600);save(receipt,result);self.pool.budget.settle(ident,'unknown');self.checkpoint();raise Pending('Unknown chat outcome; no alternate-key/provider replay',result['retry_epoch'])

class Router:
 def __init__(self,root,shared=None,options=None,checkpoint=None,quota_limits=None):
  if set(options or {})-set(MODELS):raise Attention('Unknown model stage; use reader, writer or tts')
  self.root=Path(root);self.shared=Path(shared or self.root/'provider-state');self.budget=Budget(self.shared/'budget.sqlite');self.pool=Pool(self.budget,quota_limits);self.checkpoint=checkpoint or (lambda:None);self.routes={stage:{'provider':'google','model':model,**(options or {}).get(stage,{})} for stage,model in MODELS.items()};self.models={stage:route['model'] for stage,route in self.routes.items()}
 def plan(self,stage,pages):
  primary=self.routes.get(stage,{'provider':'google','model':MODELS[stage]});routes=[primary,*primary.get('fallbacks',[])]
  for route in routes:
   if not route.get('enabled',True):continue
   provider=route.get('provider','google')
   if not isinstance(route.get('model'),str):raise Attention('Each provider route needs a model ID')
   if provider not in ('google','nim','openrouter'):raise Attention('Unsupported provider route')
   if stage=='tts' and provider!='google':raise Attention('Speech currently requires a validated native Google TTS route')
   if route.get('images',True) and len(pages)>route.get('max_images',1000 if provider=='google' else 8):continue
   if stage=='reader' and not route.get('images',True):raise Attention('Reader routes must include original images')
   yield route
 def client(self,row,route):
  if row['provider']=='google':
   options={stage:{'provider':'google','model':route['model'],'daily_requests':route.get('daily_requests',100),'rpm':route.get('rpm',8)} for stage in MODELS}
   client=ScopedGoogle(self.root,self.shared,options,self.checkpoint,self.pool,row)
  else:client=Chat(self.root,self.shared,self.checkpoint,self.pool,row,route)
  if hasattr(self,'assets'):client.assets=self.assets
  return client
 def run(self,stage,system=None,payload=None,pages=None,schema=None,max_tokens=24576,thinking=None,text=None,folder=None):
  pages=pages or [];waits=[];incomplete=None;blocked=set();logical=digest(dict(stage=stage,system=system,payload=payload,pages=[(p['page_id'],p['sha256']) for p in pages],schema=schema,text=text));gate=self.root/'routing'/(logical+'.json');prior=read(gate,{})
  if prior.get('content_rejected'):raise ContentRejected('Saved content rejection requires owner review')
  if prior.get('unknown_accepted'):
   if prior.get('retry_epoch',0)>time.time():raise Pending('Saved unknown request acceptance is cooling down',prior['retry_epoch'])
   raise Attention('Unknown accepted request requires review before any key/provider replay')
  for route in self.plan(stage,pages):
   provider=route.get('provider','google');model=route['model']
   tried=set()
   while True:
    with LOCK:
     candidates=[r for r in self.pool.candidates(provider) if r['id'] not in tried and (provider,self.pool.group(r),model) not in blocked]
     if not candidates:break
     row=candidates[0];tried.add(row['id']);self.pool.selected(row)
    group=(provider,self.pool.group(row),model)
    client=self.client(row,route)
    try:
     result=client.tts(text,folder) if stage=='tts' else client.generate(stage,system,payload,pages,schema,max_tokens,thinking)
     if stage!='tts' and (not result.get('complete') or schema_errors(schema,result.get('output'))):incomplete=result;blocked.add(group);break
     self.models[stage]=model;save(gate,dict(stage=stage,provider=provider,model=model,credential_id=result.get('credential_id','cached-legacy-unattributed'),quota_group=result.get('quota_group','legacy-unattributed'),completed=True));return result
    except CredentialRejected as exc:waits.append(exc);continue
    except QuotaWait as exc:waits.append(exc);blocked.add(group);continue
    except ServiceWait as exc:waits.append(exc);break
    except ContentRejected:
     save(gate,{'content_rejected':True});self.checkpoint();raise
    except Attention as exc:
     if 'Content screening' in str(exc):save(gate,{'content_rejected':True});self.checkpoint()
     raise
    except Pending as exc:
     if 'unknown' in exc.reason.lower():save(gate,dict(unknown_accepted=True,retry_epoch=exc.resume,provider=provider,model=model,credential_id=row['id']));self.checkpoint()
     raise
  if incomplete:return incomplete
  if waits:raise min(waits,key=lambda e:e.resume)
  raise Attention('No configured usable credential/route for '+stage)
 def generate(self,stage,system,payload,pages,schema,max_tokens=24576,thinking=None):return self.run(stage,system,payload,pages,schema,max_tokens,thinking)
 def tts(self,text,folder):return self.run('tts',text=text,folder=folder)
