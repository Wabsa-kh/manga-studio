"""Free, resumable whole-series evaluation. Raw readings and generated prose stay intact."""
import argparse,base64,copy,hashlib,json,math,re,threading,time,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import requests
from PIL import Image
from storybench import ROOT,DEFAULT_SOURCE,inventory,credentials,redact,dump
from run import original_image
from job_store import JobStore
from nim_client import Client,RateGate
from nim_native_trial import SUPER,native
from reader_v3 import PROMPT,corner_schema,prepare_corner_candidate,corners_to_regions
from reading_order import propose_text_order
from efficient_pipeline import schema_errors
from evidence_v5 import obj,arr,S,REFS
from narration_contract import writer_style,critic_style
from narrative_continuity import CONTINUITY_WRITING_RULES
from series_inventory import chapter_sort

OUT=ROOT/'full-series-v9'
READ_PROMPT=PROMPT.replace('Regions are [left,top,width,height], normalized to the original page. Keep all','Regions use named normalized left, top, right, bottom EDGE coordinates. right > left and bottom > top. Keep all')+'''
Use speaker_description=null for metadata, narration and unattributed effects.
RPG status overlays are STORY information, not title/credit metadata. Transcribe
their names, values, skills and owners accurately, using narration kind. Keep
their ownership in the text/description. Preserve printed time changes, beliefs,
denials, conditions, questions, language comprehension and unfinished thoughts.
Do not import a character name from external knowledge or infer a family role.
'''

class GoogleReader:
    def __init__(self):
        self.folder=OUT/'google';(self.folder/'requests').mkdir(parents=True,exist_ok=True)
        self.store=JobStore(self.folder/'budget.sqlite');self.gate=RateGate(10,self.store);self.stop=threading.Event();self.lock=threading.Lock();self.hold=self.folder/'hold.json'
        if self.hold.exists():self.stop.set()
    def run(self,page):
        schema=corner_schema();panel=schema['properties']['pages']['items']['properties']['panels']['items']
        for item in [panel,panel['properties']['texts']['items']]:
            for axis in item['properties']['region']['properties'].values():axis.update(type='integer',minimum=0,maximum=1000)
        prompt=READ_PROMPT+'\nCOORDINATE OVERRIDE: use INTEGER edge coordinates 0 through 1000, never decimal fractions. 0 is top/left and 1000 is bottom/right.\n'
        cfg=dict(model='gemini-3.5-flash-lite',page_id=page['page_id'],sha256=page['sha256'],prompt=prompt,schema=schema,coordinate_scale=1000,max_tokens=12288,original_bytes=True)
        sig=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest();path=self.folder/'requests'/(page['page_id']+'-'+sig[:16]+'.json')
        if path.exists():return json.loads(path.read_text(encoding='utf-8'))
        with self.lock:
            if self.stop.is_set():return {'status':'provider_hold'}
            ident=uuid.uuid4().hex
            if not self.store.reserve(ident,20000,300,4500000):return {'status':'budget_hold'}
            receipt=dict(config=cfg,status='interrupted_unknown',reservation_id=ident);dump(path,receipt)
        self.gate.acquire()
        if self.stop.is_set():
            self.store.settle(ident,'not_dispatched',0);receipt.update(status='provider_hold');dump(path,receipt);return receipt
        key=credentials('gemini',0);mime,b64=original_image(page['path'],0)
        payload={'systemInstruction':{'parts':[{'text':prompt}]},'contents':[{'role':'user','parts':[{'text':'Read only page '+page['page_id']+'. Return extracted data, not a schema.'},{'inlineData':{'mimeType':mime,'data':b64}}]}],'generationConfig':{'temperature':.2,'maxOutputTokens':12288,'responseMimeType':'application/json','responseJsonSchema':schema}}
        start=time.monotonic();parts=[];usage={};finish=None;status=None
        try:
            with requests.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:streamGenerateContent?alt=sse',headers={'x-goog-api-key':key},json=payload,stream=True,timeout=(20,60)) as response:
                status=response.status_code
                if not response.ok:receipt['error']=redact(response.text,key)[:1800]
                else:
                    for raw in response.iter_lines(chunk_size=1):
                        if time.monotonic()-start>180:status='deadline_exceeded';break
                        if not raw.startswith(b'data:'):continue
                        event=json.loads(raw[5:].strip());usage=event.get('usageMetadata') or usage
                        if event.get('promptFeedback',{}).get('blockReason'):status='content_rejected';receipt['block_reason']=event['promptFeedback']['blockReason'];break
                        for c in event.get('candidates',[]):
                            finish=c.get('finishReason') or finish
                            if finish in {'SAFETY','PROHIBITED_CONTENT','BLOCKLIST','RECITATION'}:status='content_rejected'
                            parts.extend(p.get('text','') for p in c.get('content',{}).get('parts',[]) if not p.get('thought'))
        except (requests.RequestException,ValueError) as exc:status='transport_or_parse_error';receipt['error_type']=type(exc).__name__
        text=''.join(parts);output=None
        try:output=json.loads(text)
        except ValueError:pass
        receipt.update(status=status,finish=finish,seconds=round(time.monotonic()-start,3),usage=usage,text=text,output=output)
        if status in {401,402,403,429}:
            self.stop.set();dump(self.hold,dict(status=status,error=receipt.get('error'),automatic_key_rotation=False))
        self.store.settle(ident,status,usage.get('totalTokenCount'));dump(path,receipt)
        print('read',page['page_id'],'google',status,finish,receipt['seconds'],flush=True);return receipt

def candidate_from_output(output,page,coordinate_scale=1):
    if coordinate_scale!=1:
        if coordinate_scale!=1000:raise ValueError('Unsupported declared coordinate scale')
        output=copy.deepcopy(output)
        for source_page in output.get('pages',[]):
            for panel in source_page['panels']:
                for item in [panel]+panel['texts']:item['region']={k:v/coordinate_scale for k,v in item['region'].items()}
    candidate,errors,warnings=prepare_corner_candidate(output,[page])
    if candidate:return candidate,errors,warnings
    # Preserve source text when only coordinate/placeholder repairs are needed.
    # Rectangles become camera proposals, not factual approval.
    if schema_errors(corner_schema(),output):return None,errors,warnings
    fixed=copy.deepcopy(output)
    for p in fixed['pages']:
        for panel in p['panels']:
            parent=panel['region']
            for item in [panel]+panel['texts']:
                b=item['region']
                if b['right']<=b['left'] or b['bottom']<=b['top']:
                    x=max(0,min(.98,b['left']));y=max(0,min(.98,b['top']))
                    item['region']={'left':x,'top':y,'right':min(1,max(x+.02,b['right'])),'bottom':min(1,max(y+.02,b['bottom']))}
                    warnings.append(dict(action='Degenerate geometry replaced by small camera proposal; source text unchanged',page_id=p['page_id']))
    converted,e=corners_to_regions(fixed)
    if converted is None:return None,errors,warnings
    for p in converted['pages']:
        for panel in p['panels']:
            for block in panel['texts']:
                if block['attribution_basis'] in {'unknown','not_applicable'}:block['speaker_description']=None
            for item in [panel]+panel['texts']:
                x,y,w,h=item['region']
                if w<=0 or h<=0 or x+w>1.001 or y+h>1.001:
                    item['region']=[max(0,min(.99,x)),max(0,min(.99,y)),max(.01,min(1-max(0,min(.99,x)),w)),max(.01,min(1-max(0,min(.99,y)),h))]
                    warnings.append(dict(action='Clamped invalid camera proposal; requires visual review',page_id=p['page_id']))
        try:p['panels'],moves=(lambda pair:(pair[0]['panels'],pair[1]))(propose_text_order(p))
        except ValueError:return None,errors,warnings
        warnings.extend(moves)
        for pi,panel in enumerate(p['panels'],1):
            panel['id']=f"{p['page_id']}-panel-{pi:03}"
            for bi,b in enumerate(panel['texts'],1):b['id']=panel['id']+f'-text-{bi:03}'
    return converted,[],warnings

def extract(workers=2):
    pages=inventory(Path(DEFAULT_SOURCE),['all']);OUT.mkdir(exist_ok=True);folder=OUT/'pages';folder.mkdir(exist_ok=True)
    dump(OUT/'inventory.json',pages);google=GoogleReader();nim=Client(OUT/'nim',max_calls=420,planning_budget=8000000,rpm=24)
    lock=threading.Lock();states={};done=0
    def one(page):
        nonlocal done
        pid=page['page_id'];path=folder/(pid+'.json')
        if path.exists():
            old=json.loads(path.read_text(encoding='utf-8'))
            if old.get('source_sha256')==page['sha256'] and old.get('status')=='read_complete':return old
        if str(page['chapter'])=='1':return dict(page_id=pid,status='local_read_required',reason='Earlier NVIDIA screening rejection; no new cloud image upload for this chapter.')
        result=google.run(page);provider='gemini-3.5-flash-lite'
        # Independent free provider, never another key/account. Do not reroute a
        # content/access rejection, or an unknown accepted upload.
        if result.get('status') in {429,503,502,'provider_hold','budget_hold'} and result.get('status') not in {401,402,403,'content_rejected'}:
            result=nim.run('source-'+pid,READ_PROMPT,'Extract only page '+pid+'. Return pages data.',[page],max_tokens=12288,reasoning_budget=2048,model=SUPER,temperature=.6,options=native(corner_schema()),wall_limit=180);provider=SUPER
        good=result.get('status')==200 and str(result.get('finish')).lower()=='stop'
        candidate,errors,warnings=candidate_from_output(result.get('output'),page,result.get('config',{}).get('coordinate_scale',1)) if good else (None,['Provider did not finish a reading'],[])
        row=dict(page_id=pid,source_sha256=page['sha256'],status='read_complete' if candidate else 'needs_reading',provider=provider,reading=candidate,errors=errors,warnings=warnings,source_reviewed=False,publication_approved=False,provider_status=result.get('status'))
        dump(path,row)
        with lock:
            done+=1;states[pid]=row['status'];dump(OUT/'extract-live.json',dict(processed_this_run=done,total_pages=len(pages),states=states));print('source',done,'/',len(pages),pid,row['status'],flush=True)
        return row
    with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,pages))
    status()

def status():
    pages=inventory(Path(DEFAULT_SOURCE),['all']);rows=[]
    for p in pages:
        path=OUT/'pages'/(p['page_id']+'.json');d=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        rows.append(dict(page_id=p['page_id'],chapter=p['chapter'],status=d.get('status','pending')))
    result=dict(total_pages=len(pages),read_complete=sum(r['status']=='read_complete' for r in rows),needs_reading=[r['page_id'] for r in rows if r['status']!='read_complete'],chapters=len({str(p['chapter']) for p in pages}),publication_approved=False)
    dump(OUT/'progress.json',result);print(json.dumps(result),flush=True);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['extract','status']);p.add_argument('--workers',type=int,default=2,choices=[1,2,3,4]);a=p.parse_args()
    if a.phase=='extract':extract(a.workers)
    else:status()
