"""Source-linked automatic chapter scripts, one bounded review/revision, continuity."""
import argparse,hashlib,json,re,time
from pathlib import Path
from storybench import inventory,DEFAULT_SOURCE,dump
from series_inventory import chapter_sort
from series_video_v9 import OUT,candidate_from_output
from nim_client import Client
from nim_native_trial import SUPER,native
from evidence_v5 import obj,arr,S,REFS
from narration_contract import writer_style,critic_style
from efficient_pipeline import schema_errors

WRITE_PROMPT=writer_style()+'''
WHOLE-SERIES WRITER — PROFILE 4
Retell the current source as a flowing casual recap, mostly in INDIRECT speech.
Use simple subject-verb sentences and past tense. Do not recite a list of quotes.
The audience sees the art: let incidental expressions, posture and static imagery
stay visual. Keep meaningful actions, dialogue, thoughts, decisions, discoveries,
limits and changes of knowledge. Do not merely say people talked.
The source ledger separates exact written text from fallible visual observations.
Do not inherit dramatic adjectives, guessed emotions or source-layout language.
Never say narrator, depicted, off-panel, close-up, source, panel, caption or chapter.
Do not invent an escape, motive, family relation, death, attack or explanation.
A threat is not a completed event. A character's theory is not a confirmed rule.
Preserve source presentation order, including a cliffhanger followed by a cutaway
and only later a flashback. Briefly mark the return from a memory to its enclosing
scene. The previous ending helps the handoff; do not repeat a chapter recap.
Preserve numerical costs, levels or restrictions when consequential. Do not read
every incidental inventory value. Keep status owners and abilities distinct.
Names become available at their source reveal or in established prior memory.
Aim for roughly 35–65 spoken words per story page, but completeness and natural
flow take priority: no padding to meet a minimum. Silent/metadata pages may need
little or no speech. Most segments should be 1–3 natural sentences, not fragments.
Every segment must cite the exact current source IDs that support it. page_id is
the page the viewer should see during that line, not an arbitrary nearby page.
Prefer one focus page per segment; complete a continued thought naturally once.
If a fact is uncertain, avoid strengthening it. Do not explain missing evidence.
Return one coverage entry for every current page (narrated/visual/metadata), useful
memory updates, and an ending handoff. Labels and review notes are NOT spoken.
'''

def load_chapter(pages):
    result=[];missing=[]
    for p in pages:
        path=OUT/'pages'/(p['page_id']+'.json')
        d=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if d.get('status')!='read_complete' and d.get('provider_status')==200:
            candidates=list((OUT/'google/requests').glob(p['page_id']+'-*.json'))
            if candidates:
                raw=json.loads(candidates[-1].read_text(encoding='utf-8'));candidate,errors,warnings=candidate_from_output(raw.get('output'),p)
                if candidate:d.update(status='read_complete',reading=candidate,errors=[],warnings=warnings);dump(path,d)
        if d.get('status')!='read_complete':missing.append(p['page_id']);continue
        result.append(d)
    return result,missing

def ledger(readings):
    pages=[];index={};order=0
    for r in readings:
        page=r['reading']['pages'][0];items=[]
        for pi,panel in enumerate(page['panels']):
            for b in panel['texts']:
                ref=dict(id=b['id'],page_id=page['page_id'],kind=b['kind'],text=b['text'],speaker=b['speaker_description'],region=b['region'],panel=panel['region'],order=order);order+=1;items.append(ref);index[ref['id']]=ref
            for ei,event in enumerate(panel['visible_events']):
                ref=dict(id=panel['id']+f'-event-{ei+1:03}',page_id=page['page_id'],kind='visual_observation',text=event,speaker=None,region=panel['region'],panel=panel['region'],order=order);order+=1;items.append(ref);index[ref['id']]=ref
        pages.append(dict(page_id=page['page_id'],items=items,uncertainties=page['uncertainties']))
    return pages,index

def write_schema(page_ids,ids):
    refs={'type':'array','items':{'type':'string','enum':ids},'minItems':1}
    return obj(segments=arr(obj(page_id={'type':'string','enum':page_ids},text=S,source_ids=refs)),coverage=arr(obj(page_id={'type':'string','enum':page_ids},decision={'type':'string','enum':['narrated','visual','metadata']},reason=S)),memory_updates=arr(obj(entity=S,fact=S,source_ids=refs)),handoff=obj(ending_state=S,open_questions=arr(S),active_frame=S))

def check_script(output,pages,index):
    errors=[];known=set(index);page_rank={p['page_id']:i for i,p in enumerate(pages)};last=-1
    if [c['page_id'] for c in output['coverage']]!=list(page_rank):errors.append('Coverage must list each page once in order')
    if not output['segments']:errors.append('Empty narration')
    for i,s in enumerate(output['segments']):
        if not s['text'].strip() or not s['source_ids'] or any(x not in known for x in s['source_ids']):errors.append(f'Segment {i}: invalid text/reference');continue
        if s['page_id'] not in {index[x]['page_id'] for x in s['source_ids']}:errors.append(f'Segment {i}: focus page lacks cited source')
        rank=page_rank[s['page_id']]
        if rank<last:errors.append(f'Segment {i}: backwards page disclosure order')
        last=max(last,rank)
        if re.search(r'\b(?:the narrator|depicted|off.panel|close.up|the next panel|the source|captioned)\b',s['text'],re.I):errors.append(f'Segment {i}: source commentary in narration')
    return errors

REVIEW_SCHEMA=obj(issues=arr(obj(segment_index={'type':'integer','minimum':0},severity={'type':'string','enum':['blocking','warning']},category={'type':'string','enum':['source','order','coverage','style']},problem=S,source_ids=REFS)),missing_essential_source_ids=REFS)
REVIEW_PROMPT=critic_style()+'''
Review the script against the supplied source ledger and previous handoff. Detect
unsupported claims, wrong attributed speech, missing consequential dialogue,
changed ability/status ownership, premature name/knowledge reveals, incorrect
flashback disclosure order and literary/source commentary. Sparse visual material
need not be narrated. Do not demand an invented connection or a spoken disclaimer.
Only report specific problems with cited source evidence. Do not rewrite the script.
'''

def write_all(wait=False):
    source=inventory(Path(DEFAULT_SOURCE),['all']);labels=sorted({p['chapter'] for p in source},key=chapter_sort)
    folder=OUT/'chapters';folder.mkdir(exist_ok=True);client=Client(OUT/'nim',max_calls=420,planning_budget=8000000,rpm=24);memory=[];previous=None
    for label in labels:
        target=folder/('chapter-'+str(label));target.mkdir(exist_ok=True);complete=target/'draft.json'
        if complete.exists():
            saved=json.loads(complete.read_text(encoding='utf-8'));memory.extend(saved['script']['memory_updates']);previous=saved['script']['handoff'];continue
        pages=[p for p in source if p['chapter']==label]
        while True:
            readings,missing=load_chapter(pages)
            if not missing:break
            dump(target/'waiting.json',dict(status='waiting_for_source',missing=missing))
            if not wait:print('Waiting for source',label,missing,flush=True);return
            time.sleep(10)
        data,index=ledger(readings);ids=list(index);schema=write_schema([p['page_id'] for p in pages],ids)
        # Source text is complete for this chapter; only previous-chapter memory
        # is supplied. Future readings never enter the writing request.
        payload=dict(current_pages=data,previous_handoff=previous,prior_memory=memory[-120:],reading_uncertainty='Visual descriptions and attribution are fallible; do not invent certainty.')
        dump(target/'source-ledger.json',dict(pages=data,index=index));r=client.run('write-chapter-'+str(label),WRITE_PROMPT,json.dumps(payload),max_tokens=16384,reasoning_budget=3072,model=SUPER,temperature=1,options=native(schema),wall_limit=360)
        if r.get('status')!=200 or str(r.get('finish')).lower()!='stop':dump(target/'gate.json',dict(status='writer_incomplete',provider_status=r.get('status')));return
        script=r.get('output');errors=schema_errors(schema,script)
        if not errors:errors=check_script(script,data,index)
        review=client.run('critic-chapter-'+str(label),REVIEW_PROMPT,json.dumps(dict(source=payload,script=script)),max_tokens=8192,reasoning_budget=2048,model=SUPER,temperature=.6,options=native(REVIEW_SCHEMA),wall_limit=360)
        audit=review.get('output') if review.get('status')==200 and str(review.get('finish')).lower()=='stop' else None
        critical=[i for i in (audit or {}).get('issues',[]) if i['severity']=='blocking'];missing_ids=(audit or {}).get('missing_essential_source_ids',[])
        if errors or critical or missing_ids:
            fix=client.run('revise-chapter-'+str(label),WRITE_PROMPT+'\nRevise the complete draft using the supplied specific review. Do not introduce facts to satisfy a review if the source does not support them.',json.dumps(dict(**payload,previous_draft=script,validation_errors=errors,review=audit)),max_tokens=16384,reasoning_budget=3072,model=SUPER,temperature=1,options=native(schema),wall_limit=360)
            if fix.get('status')==200 and str(fix.get('finish')).lower()=='stop':
                script=fix['output'];errors=schema_errors(schema,script)
                if not errors:errors=check_script(script,data,index)
        if errors:dump(target/'gate.json',dict(status='needs_script_repair',errors=errors,review=audit));print('Script validation needs repair',label,errors,flush=True);return
        beats=[dict(id=f'ch{label}-beat-{i+1:03}',text=s['text'],page_id=s['page_id'],source_ids=s['source_ids'],primary_source_id=next(x for x in s['source_ids'] if index[x]['page_id']==s['page_id'])) for i,s in enumerate(script['segments'])]
        text='\n\n'.join(b['text'] for b in beats);digest=hashlib.sha256(text.encode()).hexdigest()
        draft=dict(chapter=label,script=script,beats=beats,words=len(text.split()),text_sha256=digest,manual_prose_edits=False,source_reviewed=False,evaluation_preview_authorized=True,publication_approved=False,issues=[],review=audit,review_scope='One automatic source/style review, at most one automatic revision. Not full independent factual approval.')
        dump(complete,draft);(target/'narration.txt').write_text(text,encoding='utf-8');dump(target/'gate.json',dict(status='evaluation_draft_ready',publication_approved=False,words=draft['words']))
        memory.extend(script['memory_updates']);previous=script['handoff'];dump(OUT/'continuity-memory.json',dict(memory=memory,latest_chapter=label,handoff=previous))
        print('SCRIPT',label,draft['words'],'words',len(beats),'beats',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--wait-for-source',action='store_true');a=p.parse_args();write_all(a.wait_for_source)
