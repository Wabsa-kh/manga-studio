"""Direct NVIDIA NIM benchmark client. Original images, bounded calls, no key cycling."""
import base64,ctypes,hashlib,json,os,re,threading,time,uuid
from collections import deque
from pathlib import Path
import requests
from job_store import JobStore

MODEL='nvidia/nemotron-3-nano-omni-30b-a3b-reasoning'
URL='https://integrate.api.nvidia.com/v1/chat/completions'
SECRET=Path.home()/'.codex/private/nvidia-nim-key.dpapi'

def _dpapi(data,decrypt=False):
    if os.name!='nt':raise RuntimeError('Use NVIDIA_API_KEY on non-Windows workers')
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data);src=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));dst=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(src),None,None,None,None,0,ctypes.byref(dst)):raise ctypes.WinError()
    try:return ctypes.string_at(dst.data,dst.size)
    finally:ctypes.windll.kernel32.LocalFree(dst.data)

def save_private_key(value):
    SECRET.parent.mkdir(parents=True,exist_ok=True);SECRET.write_bytes(_dpapi(value.encode()))

def credential():
    if os.environ.get('NVIDIA_API_KEY'):return os.environ['NVIDIA_API_KEY']
    return _dpapi(SECRET.read_bytes(),True).decode()

def clean(text,key):return re.sub(r'nvapi-[A-Za-z0-9_-]+','[REDACTED]',str(text).replace(key,'[REDACTED]'))

def post_with_poll(payload,key,stream):
    start=time.monotonic();response=requests.post(URL,headers={'Authorization':'Bearer '+key,'Accept':'text/event-stream' if stream else 'application/json'},json=payload,stream=stream,timeout=(30,180));polls=0
    if response.status_code!=202:return response,polls
    ident=response.headers.get('NVCF-REQID') or response.headers.get('X-Request-Id')
    if not ident:
        data=response.json();ident=data.get('requestId') or data.get('request_id')
    if not ident or not re.fullmatch(r'[0-9a-fA-F-]{36}',ident):return response,polls
    while response.status_code==202 and time.monotonic()-start<180:
        response.close();time.sleep(1)
        response=requests.get('https://integrate.api.nvidia.com/v1/status/'+ident,headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=(30,30));polls+=1
    return response,polls

class RateGate:
    def __init__(self,rpm=32,database=None):
        if not 1<=rpm<=40:raise ValueError('Benchmark RPM bound must be 1..40')
        self.rpm=rpm;self.starts=deque();self.lock=threading.Lock();self.all_starts=[]
        self.database=database
        if database:
            with database.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS nim_starts (at REAL NOT NULL)')
    def acquire(self):
        while True:
            with self.lock:
                now=time.monotonic()
                if self.database:
                    with self.database.connect() as db:
                        db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM nim_starts WHERE at<=? OR at>?',(now-60,now+60))
                        count,earliest=db.execute('SELECT count(*),min(at) FROM nim_starts').fetchone()
                        if count<self.rpm:db.execute('INSERT INTO nim_starts VALUES(?)',(now,));self.all_starts.append(now);return now
                        delay=max(.02,earliest+60.05-now)
                    time.sleep(min(1,delay));continue
                while self.starts and self.starts[0]<=now-60:self.starts.popleft()
                if len(self.starts)<self.rpm:self.starts.append(now);self.all_starts.append(now);return now
                delay=max(.02,self.starts[0]+60.05-now)
            time.sleep(min(1,delay))

class Client:
    def __init__(self,out,max_calls=60,planning_budget=600000,rpm=32):
        self.out=Path(out);(self.out/'requests').mkdir(parents=True,exist_ok=True)
        self.store=JobStore(self.out/'budget.sqlite');self.max_calls=max_calls;self.planning_budget=planning_budget
        self.gate=RateGate(rpm,self.store);self.stop=threading.Event();self.lock=threading.Lock();self.hold=self.out/'provider-hold.json'
        if self.hold.exists():self.stop.set()
    def run(self,name,system,user,pages=(),max_tokens=4096,reasoning_budget=512,stream=True,schema=None,model=None,temperature=.6,top_p=.95,options=None,wall_limit=360):
        from run import original_image
        from storybench import resolve_page
        if not 1<=max_tokens<=65536 or reasoning_budget is not None and not 0<=reasoning_budget<max_tokens:raise ValueError('Invalid output/reasoning bounds')
        model=model or MODEL
        if model=='nvidia/nemotron-3-ultra-550b-a55b' and pages:raise ValueError('Ultra is text-only; use it as a writer/reviewer')
        if not 30<=wall_limit<=900:raise ValueError('Wall limit must be 30..900 seconds')
        options=options or {}
        if set(options)-{'reasoning_effort','chat_template_kwargs','response_format','seed'}:raise ValueError('Unsupported request option')
        pages=[resolve_page(p) for p in pages]
        config=dict(adapter_policy='nim-stream-usage-v2',model=model,system=system,user=user,pages=[{k:p[k] for k in ['page_id','sha256']} for p in pages],max_tokens=max_tokens,reasoning_budget=reasoning_budget,stream=stream,schema=schema,temperature=temperature,top_p=top_p)
        if options:config['options']=options
        digest=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest();path=self.out/'requests'/f'{name}-{digest[:16]}.json'
        if path.exists():return json.loads(path.read_text(encoding='utf-8'))
        with self.lock:
            if self.stop.is_set():return dict(status='benchmark_hold',name=name)
            ident=uuid.uuid4().hex;reserved=max_tokens+(len(system)+len(user))//2+6000*len(pages)
            if not self.store.reserve(ident,reserved,self.max_calls,self.planning_budget):return dict(status='budget_hold',name=name)
            receipt=dict(name=name,config=config,status='interrupted_unknown',reservation_id=ident)
            path.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        self.gate.acquire()
        if self.hold.exists():self.stop.set()
        if self.stop.is_set():
            receipt.update(status='not_dispatched_after_provider_hold');self.store.settle(ident,receipt['status'],0);path.write_text(json.dumps(receipt,indent=2));return receipt
        receipt['dispatch_monotonic']=time.monotonic();receipt['dispatch_epoch']=time.time()
        key=credential();content=[dict(type='text',text=user)]
        for page in pages:
            mime,b64=original_image(page['path'],0)
            content.extend([dict(type='text',text='Page ID: '+page['page_id']),dict(type='image_url',image_url=dict(url=f'data:{mime};base64,{b64}'))])
        if schema:system+='\nRequired JSON output schema:\n'+json.dumps(schema)
        payload=dict(model=model,messages=[dict(role='system',content=system),dict(role='user',content=content if pages else user)],max_tokens=max_tokens,stream=stream,temperature=temperature,top_p=top_p,**options)
        if reasoning_budget is not None:payload['reasoning_budget']=reasoning_budget
        if stream:payload['stream_options']={'include_usage':True}
        start=time.monotonic();first_delta=None;first_visible=None;last_delta=None;last_visible=None;parts=[];reasoning_chars=0;usage=None;finish=None;chunks=0;headers={};status=None;completed=False
        progress=self.out/'requests'/f'{name}-{digest[:16]}.progress.json';last_progress=0
        try:
            response,polls=post_with_poll(payload,key,stream);receipt['status_polls']=polls
            with response:
                headers={k:v for k,v in response.headers.items() if any(s in k.lower() for s in ['ratelimit','rate-limit','retry-after','request-id','inference','processing'])};status=response.status_code;header_time=time.monotonic()-start
                if not response.ok:
                    receipt.update(body=clean(response.text[:2000],key))
                    if status in {401,402,403,422,429}:
                        self.stop.set();self.hold.write_text(json.dumps(dict(status=status,headers=headers,reason=receipt['body'],requires_review=True)),encoding='utf-8')
                elif response.status_code==202:receipt['pending_request_id']=headers.get('X-Request-Id') or response.headers.get('NVCF-REQID')
                elif stream and not polls:
                    for raw in response.iter_lines(chunk_size=1):
                        elapsed_now=time.monotonic()-start
                        if elapsed_now>wall_limit:
                            status='deadline_exceeded';receipt['error_type']='TotalWallDeadline';completed=False;break
                        if elapsed_now-last_progress>=5:
                            progress.write_text(json.dumps(dict(name=name,status='streaming',seconds=elapsed_now,first_generated_delta_seconds=first_delta,first_visible_text_seconds=first_visible,reasoning_characters=reasoning_chars,visible_characters=sum(map(len,parts)))),encoding='utf-8');last_progress=elapsed_now
                        if not raw or not raw.startswith(b'data:'):continue
                        data=raw[5:].strip()
                        if data==b'[DONE]':completed=True;break
                        event=json.loads(data);chunks+=1
                        if event.get('usage'):usage=event['usage']
                        if event.get('error'):status='stream_error';receipt['error']=clean(str(event['error'])[:1000],key);break
                        for choice in event.get('choices',[]):
                            delta=choice.get('delta',{});text=delta.get('content') or '';reason=delta.get('reasoning_content') or delta.get('reasoning') or ''
                            if text or reason:
                                now=time.monotonic()-start;first_delta=now if first_delta is None else first_delta;last_delta=now
                            if text:
                                first_visible=now if first_visible is None else first_visible;last_visible=now;parts.append(text)
                            reasoning_chars+=len(reason)
                            if choice.get('finish_reason'):finish=choice['finish_reason'];completed=True
                else:
                    event=response.json();usage=event.get('usage');choice=event['choices'][0];finish=choice.get('finish_reason');message=choice['message'];parts=[message.get('content') or ''];reasoning_chars=len(message.get('reasoning_content') or message.get('reasoning') or '');completed=True
                receipt['response_headers_seconds']=round(header_time,4)
        except (requests.RequestException,ValueError,KeyError,IndexError,TypeError) as exc:
            status='transport_or_stream_error';receipt['error_type']=type(exc).__name__
        elapsed=time.monotonic()-start;text=''.join(parts)
        # Retain final content and measurements, never the model's private reasoning.
        text=re.sub(r'<think>.*?</think>','',text,flags=re.S).strip();parsed=None
        if text.startswith('<think>'):reasoning_chars+=len(text);text='';receipt['unfinished_reasoning_only']=True
        if text:
            try:parsed=json.loads(re.sub(r'\s*```$','',re.sub(r'^```(?:json)?\s*','',text)))
            except ValueError:pass
        tokens=(usage or {}).get('completion_tokens');total=(usage or {}).get('total_tokens')
        span=last_delta-first_delta if last_delta is not None and first_delta is not None else None
        receipt.update(status=status,completed=completed,finish=finish,seconds=round(elapsed,4),first_generated_delta_seconds=first_delta,first_visible_text_seconds=first_visible,last_generated_delta_seconds=last_delta,last_visible_text_seconds=last_visible,usage=usage,headers=headers,stream_chunks=chunks,reasoning_characters=reasoning_chars,text=clean(text,key),output=parsed,
            completion_tokens_per_wall_second=tokens/elapsed if tokens and elapsed>0 else None,completion_tokens_per_generation_span=tokens/span if tokens and span and span>.01 else None,
            speed_caveat='Generation-span proxy includes reported reasoning tokens; exact server decode time is unavailable. Wall rate includes queue/prefill/transfer.')
        self.store.settle(ident,status,total);path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        if progress.exists():progress.unlink()
        print(json.dumps(dict(name=name,status=status,finish=finish,seconds=round(elapsed,2),first_visible=first_visible,tokens=total,parsed=parsed is not None)),flush=True)
        return receipt
