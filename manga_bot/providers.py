"""Single-key free-model adapter with durable receipts and observed reset waits."""
import base64,json,mimetypes,time,wave,os,threading
from pathlib import Path
import requests
from .core import Budget,Pending,Attention,save,read,digest,event,sha,utc,next_reset
from storybench import credentials,redact,ROOT
from quota_control import hold_reason,learn_limit

MODELS={'reader':'gemini-3.5-flash-lite','writer':'gemini-4-hydrogen','tts':'gemini-3.8-flash-tts'}

class Google:
 def credential_retry(self,old):
  audit=getattr(self,'audit',{})
  return bool(old and audit and old.get('credential_id')!=audit.get('credential_id') and old.get('status') in (401,429) and (old.get('status')==401 or old.get('quota_group')!=audit.get('quota_group')))
 def __init__(self,root,shared=None,options=None,checkpoint=None,key_getter=None):
  self.root=Path(root);self.shared=Path(shared or self.root/'provider-state');self.shared.mkdir(parents=True,exist_ok=True);self.budget=Budget(self.shared/'budget.sqlite');self.quota_lock=threading.Lock()
  self.limits={MODELS['reader']:(440,8),MODELS['writer']:(18,3),MODELS['tts']:(9,2)}
  self.models={**MODELS};self.checkpoint=checkpoint or (lambda:None)
  self.key_getter=key_getter or (lambda:credentials('gemini',0))
  for stage,route in (options or {}).items():
   if route.get('provider','google')!='google':raise Attention('Configured provider requires its own validated adapter: '+route['provider'])
   self.models[stage]=route.get('model',MODELS[stage]);self.limits[self.models[stage]]=(route.get('daily_requests',self.limits[MODELS[stage]][0]),route.get('rpm',self.limits[MODELS[stage]][1]))
 def before(self,model):
  # Read legacy observations from this workstation, but never sum key quotas.
  old=hold_reason(ROOT/'quota-state.json','gemini',model)
  if old:
   if old.get('retryable') is False:raise Attention('Existing provider/model hold: '+str(old.get('reason')))
   raise Pending('Observed existing provider quota hold',old['blocked_until_epoch'])
  return self.budget.reserve(model,*self.limits[model])
 def error(self,model,status,body,headers):
  if status==429:
   if any(marker in body.lower() for marker in ['per_day','perday','per day','daily']):
    until=next_reset();self.budget.set_hold(model,'Observed daily quota exhausted for '+model,until);raise Pending('Daily provider quota reset required for '+model,until)
   with self.quota_lock:state=learn_limit(self.shared/'quota-observations.json','gemini',model,dict(status=status,body=body,headers=headers))
   until=state.get('blocked_until_epoch')
   if until:self.budget.set_hold(model,'Observed provider quota reset for '+model,until);raise Pending('Provider quota reset required for '+model,until)
   self.budget.set_hold(model,'429 without a documented retry time',permanent=True);raise Attention('Provider quota response needs an entitlement/reset inspection')
  if status in {401,402,403}:
   self.budget.set_hold(model,'Provider authentication/access rejected; no alternate key or paid fallback',permanent=True);raise Attention('Provider authentication/access rejected')
  raise Pending('Temporary provider failure '+str(status),time.time()+60)
 def generate(self,stage,system,payload,pages,schema,max_tokens=24576,thinking=None):
  model=self.models[stage];config=dict(model=model,system=system,payload=payload,pages=[dict(page_id=p['page_id'],sha256=p['sha256']) for p in pages],schema=schema,max_tokens=max_tokens,thinking=thinking,adapter='bot-native-v11')
  signature=digest(config);folder=self.root/'requests'/signature;folder.mkdir(parents=True,exist_ok=True);receipt=folder/'result.json';old=read(receipt)
  if old and (old.get('complete') or old.get('known_incomplete')):return old
  attempt=0 if (old or {}).get('status')==429 or self.credential_retry(old) else (old or {}).get('attempt',0)
  if old:
   if old.get('fatal'):raise Attention(old['reason'])
   if old.get('status')=='started_unknown':
    # Persisted conservative reservation remains counted. A stalled upload is
    # not blindly replayed on restart; one bounded recovery is explicit policy.
    until=old['started_epoch']+3600
    if time.time()<until:raise Pending('Unknown accepted request cooling down; reservation retained',until)
    if getattr(self,'strict_unknown',False):raise Attention('Unknown accepted request needs review before replay')
    if attempt>=2:raise Attention('Repeated unknown provider request; no further replay')
   if old.get('retry_epoch',0)>time.time() and not self.credential_retry(old):raise Pending(old.get('reason','Retry cooldown'),old['retry_epoch'])
   if attempt>=3:
    if old.get('status') in {408,500,502,503,504}:
     retry=old.get('started_epoch',time.time())+3600
     if time.time()<retry:raise Pending('Service unavailable after bounded attempts; hourly cooldown',retry)
     attempt=0
    else:raise Attention('Bounded provider attempts exhausted')
  ident=self.before(model);key=self.key_getter();parts=[dict(text=json.dumps(payload,ensure_ascii=False))]
  for p in pages:
   if sha(p['path'])!=p['sha256']:raise Attention('Source changed after inventory: '+p['page_id'])
   raw=Path(p['path']).read_bytes();parts.extend([dict(text='Original page '+p['page_id']),dict(inlineData=dict(mimeType=mimetypes.guess_type(p['path'])[0] or 'image/png',data=base64.b64encode(raw).decode()))])
  generation=dict(temperature=.25 if stage=='reader' else 1.0,maxOutputTokens=max_tokens,responseMimeType='application/json',responseJsonSchema=schema)
  if thinking:generation['thinkingConfig']=dict(thinkingLevel=thinking.upper())
  body=dict(systemInstruction=dict(parts=[dict(text=system)]),contents=[dict(role='user',parts=parts)],generationConfig=generation)
  if old:save(folder/f'attempt-{attempt}.json',old)
  result=dict(config=config,status='started_unknown',attempt=attempt+1,reservation_id=ident,started_epoch=time.time(),started_utc=utc(),complete=False);result.update(getattr(self,'audit',{}));save(receipt,result);event(self.root,'provider_started',stage=stage,model=model,pages=len(pages),receipt=str(receipt.relative_to(self.root)))
  self.checkpoint()
  start=time.monotonic();text=[];finish=None;usage={}
  try:
   # The live endpoint repeatedly closed SSE streams without a terminal event,
   # even for one page. A whole JSON HTTP response gives a verifiable completion.
   with requests.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',headers={'x-goog-api-key':key},json=body,timeout=(40,1200)) as response:
    result['status']=response.status_code
    if not response.ok:
     message=redact(response.text,key);result.update(body=message,headers={k:v for k,v in response.headers.items() if k.lower()=='retry-after'},retry_epoch=time.time()+60,reason='HTTP '+str(response.status_code));save(receipt,result);self.budget.settle(ident,response.status_code);self.error(model,response.status_code,message,result['headers'])
    for row in [response.json()]:
     if time.monotonic()-start>1200:raise requests.Timeout('Bounded generation deadline')
     usage=row.get('usageMetadata') or usage
     if row.get('promptFeedback',{}).get('blockReason'):result.update(fatal=True,reason='Content screening rejected these images; no image rerouting');raise Attention(result['reason'])
     for candidate in row.get('candidates',[]):
      finish=candidate.get('finishReason') or finish
      if finish in {'SAFETY','PROHIBITED_CONTENT','BLOCKLIST','RECITATION'}:result.update(fatal=True,reason='Content screening rejected these images; no image rerouting');raise Attention(result['reason'])
      for part in candidate.get('content',{}).get('parts',[]):
       if not part.get('thought') and part.get('text'):text.append(part['text'])
     save(folder/'progress.json',dict(seconds=round(time.monotonic()-start),visible_characters=sum(map(len,text)),finish=finish,usage=usage))
   result.update(finish=finish,usage=usage,text=''.join(text),seconds=round(time.monotonic()-start,2))
   try:result['output']=json.loads(result['text'])
   except ValueError:result['output']=None
   result['complete']=finish=='STOP' and result['output'] is not None
   # A completed but malformed/truncated result is returned to the stage's
   # bounded split/repair logic, never presented as a complete script.
   if not result['complete']:result['known_incomplete']=True
   self.budget.settle(ident,200,usage.get('totalTokenCount'));save(receipt,result);self.checkpoint();event(self.root,'provider_finished',stage=stage,model=model,status=200,finish=finish,seconds=result['seconds'],reported_tokens=usage.get('totalTokenCount'));return result
  except (Pending,Attention):
   save(receipt,result);self.checkpoint();raise
  except (requests.RequestException,ValueError) as exc:
   result.update(status='started_unknown',reason=type(exc).__name__,retry_epoch=time.time()+3600,seconds=round(time.monotonic()-start,2));save(receipt,result);self.budget.settle(ident,'unknown');raise Pending('Unknown transport outcome; retained reservation and bounded delayed recovery',result['retry_epoch'])
 def tts(self,text,folder):
  model=self.models['tts'];config=dict(model=model,voice='Charon',text=text,style='Clear, natural third-person storytelling. Neutral English, simple conversational delivery, no theatrical exaggeration.');folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);audio=folder/'voice.wav';receipt=folder/'result.json';old=read(receipt);signature=digest(config)
  if hasattr(self,'assets'):self.assets.ensure_path(audio,missing_ok=not bool(old and old.get('complete')))
  if old and old.get('complete') and old.get('signature')==signature and audio.exists() and sha(audio)==old['audio_sha256']:return old
  if old and old.get('retry_epoch',0)>time.time() and not self.credential_retry(old):raise Pending('Speech request cooldown',old['retry_epoch'])
  if old and old.get('fatal'):raise Attention(old.get('reason','Speech job rejected'))
  if old and old.get('status')=='started_unknown' and getattr(self,'strict_unknown',False):raise Attention('Unknown speech acceptance needs review before replay')
  attempt=0 if (old or {}).get('status')==429 or self.credential_retry(old) else (old or {}).get('attempt',0)
  if old and old.get('status')=='started_unknown' and attempt>=2:raise Attention('Repeated unknown speech outcome; recovery exhausted')
  if attempt>=3:
   if old.get('status') in {408,500,502,503,504}:
    retry=old.get('started_epoch',time.time())+3600
    if time.time()<retry:raise Pending('Speech service hourly cooldown',retry)
    attempt=0
   else:raise Attention('Speech retry allowance exhausted')
  ident=self.before(model);key=self.key_getter();result=dict(signature=signature,config=config,status='started_unknown',started_epoch=time.time(),started_utc=utc(),attempt=attempt+1,reservation_id=ident,complete=False);result.update(getattr(self,'audit',{}));save(receipt,result);self.checkpoint()
  payload=dict(model=model,input=[dict(type='user_input',content=[dict(type='text',text=text,annotations=[dict(type='speech_metadata',style=config['style'])])])],response_format=dict(type='audio'),generation_config=dict(speech_config=[dict(voice='Charon')]))
  start=time.monotonic()
  try:
   response=requests.post('https://generativelanguage.googleapis.com/v1beta/interactions',headers={'x-goog-api-key':key},json=payload,timeout=(40,420));result['status']=response.status_code
   if not response.ok:
    message=redact(response.text,key);result.update(body=message,retry_epoch=time.time()+60);save(receipt,result);self.budget.settle(ident,response.status_code);self.error(model,response.status_code,message,dict(response.headers))
   data=response.json();blocks=[c for s in data.get('steps',[]) if s.get('type')=='model_output' for c in s.get('content',[]) if c.get('type')=='audio']
   if not blocks:result.update(fatal=True,reason='Speech service returned no audio');save(receipt,result);raise Attention(result['reason'])
   raw=base64.b64decode(blocks[-1]['data'])
   if raw[:4]!=b'RIFF':
    result.update(fatal=True,reason='Unexpected speech container');save(receipt,result);raise Attention(result['reason'])
   temp=audio.with_suffix('.wav.tmp');temp.write_bytes(raw);os.replace(temp,audio)
   with wave.open(str(audio)) as w:duration=w.getnframes()/w.getframerate()
   usage=data.get('usage') or {};result.update(complete=True,duration=duration,audio_sha256=sha(audio),usage=usage,seconds=round(time.monotonic()-start,2));save(receipt,result);self.budget.settle(ident,200,usage.get('total_tokens'));self.checkpoint();event(self.root,'speech_complete',words=len(text.split()),seconds=result['seconds'],duration=duration,model=model);return result
  except (Pending,Attention):raise
  except (requests.RequestException,ValueError) as exc:
   result.update(status='started_unknown',reason=type(exc).__name__,retry_epoch=time.time()+3600);save(receipt,result);self.budget.settle(ident,'unknown');raise Pending('Unknown speech outcome; retained reservation and bounded delayed recovery',result['retry_epoch'])
