"""Evidence indexing, continuity proposals, grounded narration and page-first shot planning.

This is a prototype that gates publication on source review. It does not render a video.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import re
from storybench import ROOT, call, dump, validate
from narration_contract import writer_style,critic_style

# Keep the executable writer instructions and the editorial specification aligned.
STYLE = writer_style()

def load_evidence(paths):
    records=[]
    seen=set()
    for path in paths:
        d=json.loads(Path(path).read_text(encoding='utf-8'))
        if d.get('status')!=200 or d.get('finish') not in {'STOP','stop'} or 'output' not in d:
            raise ValueError('Incomplete or unsuccessful extraction: '+str(path))
        errors=validate(d['output'],d['config']['pages'],d['config'].get('memory'))
        if errors: raise ValueError('Extraction requires repair: '+str(errors))
        for page in d['output']['pages']:
            if page['page_id'] in seen: raise ValueError('Overlapping extraction outputs: '+page['page_id'])
            seen.add(page['page_id'])
        records.append(d)
    records.sort(key=lambda d:(d['config']['pages'][0]['chapter'],d['config']['pages'][0]['page_id']))
    return records

def build_index(records,path):
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE IF NOT EXISTS pages
        (page_id TEXT, extraction_hash TEXT, source_hash TEXT, chapter INTEGER,
         ordinal INTEGER, record TEXT, PRIMARY KEY(page_id,extraction_hash));
        CREATE TABLE IF NOT EXISTS facts
        (beat_id TEXT, extraction_hash TEXT, page_id TEXT, ordinal INTEGER,
         evidence_kind TEXT, confidence TEXT, fact TEXT, record TEXT,
         PRIMARY KEY(beat_id,extraction_hash));
        CREATE TABLE IF NOT EXISTS runs
        (extraction_hash TEXT PRIMARY KEY, provider TEXT, model TEXT, record TEXT);''')
    ordinal=0
    for d in records:
        h=hashlib.sha256(json.dumps(d['output'],sort_keys=True).encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?)',
                   (h,d['config']['provider'],d['config']['model'],json.dumps(d['config'])))
        meta={p['page_id']:p for p in d['config']['pages']}
        for page in d['output']['pages']:
            ordinal+=1
            p=meta[page['page_id']]
            db.execute('INSERT OR IGNORE INTO pages VALUES(?,?,?,?,?,?)',
                       (page['page_id'],h,p['sha256'],p['chapter'],ordinal,json.dumps(page)))
            for beat in page['beats']:
                db.execute('INSERT OR IGNORE INTO facts VALUES(?,?,?,?,?,?,?,?)',
                           (beat['id'],h,page['page_id'],ordinal,beat['evidence_kind'],
                            beat['confidence'],beat['fact'],json.dumps(beat)))
    db.commit();db.close()

def prefix_context(records,chapter):
    """No future chapter can enter a chapter writing task."""
    out=[]
    allowed_pages={p['page_id'] for d in records for p in d['output']['pages'] if int(p['page_id'].split('-')[0][2:])<=chapter}
    for d in records:
        pages=[p for p in d['output']['pages'] if int(p['page_id'].split('-')[0][2:])<=chapter]
        if pages:
            # Extractor records here contain exactly one chapter; defend mixed input anyway.
            allowed={p['page_id'] for p in pages}
            entities=[e for e in d['output']['entities'] if set(e.get('source_pages',[]))<=allowed_pages]
            out.append({'pages':pages,'entities':entities})
    return out

def check_script(script, records):
    if not isinstance(script,dict) or not isinstance(script.get('segments'),list):return ['Malformed narration schema']
    facts={b['id']:p for d in records for p in d['output']['pages'] for b in p['beats']}
    order={p['page_id']:i for i,p in enumerate(p for d in records for p in d['output']['pages'])}
    errors=[]
    if not script.get('segments'): errors.append('Narration has no segments')
    last=-1
    ids=set()
    for s in script.get('segments',[]):
        if not isinstance(s,dict):return ['Malformed narration segment']
        if s.get('id') in ids: errors.append('Duplicate segment ID')
        ids.add(s.get('id'))
        if not isinstance(s.get('text'),str) or not s['text'].strip(): errors.append('Empty narration')
        refs=s.get('source_beats',[])
        if not isinstance(refs,list) or not refs or any(not isinstance(x,str) or x not in facts for x in refs):
            errors.append('Missing or invalid source beats');continue
        pages=list(dict.fromkeys(facts[x]['page_id'] for x in refs))
        if s.get('source_pages')!=pages: errors.append('Page mapping disagrees with source beats')
        pos=min(order[p] for p in pages)
        if pos<last: errors.append('Narration moves backward in source order; review for spoilers or duplication')
        last=max(last,max(order[p] for p in pages))
    return list(dict.fromkeys(errors))


def check_continuity(output,records):
    if not isinstance(output,dict):return False
    keys=['identity_proposals','relationships','contradictions','recheck_pages','open_threads']
    if any(not isinstance(output.get(k),list) for k in keys):return False
    beats={b['id'] for d in records for p in d['output']['pages'] for b in p['beats']}
    entities={e['id'] for d in records for e in d['output']['entities']}
    pages={p['page_id'] for d in records for p in d['output']['pages']}
    for item in output['identity_proposals']+output['relationships']+output['contradictions']:
        if not isinstance(item,dict):return False
        refs=item.get('source_beats')
        if not isinstance(refs,list) or not refs or any(x not in beats for x in refs):return False
    for item in output['identity_proposals']:
        if not isinstance(item.get('ids'),list) or not item['ids'] or any(x not in entities for x in item['ids']):return False
    for item in output['relationships']:
        if item.get('from_id') not in entities or item.get('to_id') not in entities:return False
    return all(isinstance(x,dict) and x.get('page_id') in pages and isinstance(x.get('question'),str) for x in output['recheck_pages'])


def check_critic(output,script,records):
    if not isinstance(output,dict) or any(not isinstance(output.get(k),list) for k in ['issues','omitted_essential_beats','repeated_segments']):return False
    segments={s['id'] for s in script['segments']}
    beats={b['id'] for d in records for p in d['output']['pages'] for b in p['beats']}
    if any(x not in beats for x in output['omitted_essential_beats']):return False
    if any(x not in segments for x in output['repeated_segments']):return False
    for issue in output['issues']:
        if not isinstance(issue,dict) or issue.get('segment_id') not in segments:return False
        if not isinstance(issue.get('source_beats'),list) or any(b not in beats for b in issue['source_beats']):return False
        if not isinstance(issue.get('needs_image_recheck'),bool):return False
        if any(not isinstance(issue.get(k),str) for k in ['claim','reason']):return False
    return True


def editorial_checks(script):
    """Narrow deterministic checks, not a semantic quality score."""
    issues=[]
    for segment in script.get('segments',[]):
        if re.search(r'\b(?:the narration|narration explained|the next panel|the panel shows|title card|the narrator)\b',segment['text'],re.I):
            issues.append({'segment_id':segment['id'],'problem':'Source/layout commentary in spoken narration'})
    return issues

def plan_shots(script,records,wpm=180):
    """Whole page is the safe starting frame. No guessed face coordinates."""
    errors=check_script(script,records)
    if errors:raise ValueError(errors)
    source={p['page_id']:p for d in records for p in d['config']['pages']}
    shots=[]
    cursor=0.0
    for segment in script['segments']:
        duration=max(1.5,len(segment['text'].split())*60/wpm)
        pages=segment['source_pages']
        for pid in pages:
            dt=duration/len(pages)
            shots.append({'segment_id':segment['id'],'page_id':pid,'source_path':source[pid]['path'],
                          'start':round(cursor,3),'duration':round(dt,3),'timing':'word-count estimate, replace after TTS',
                          'frame':[0,0,1,1],'fit':'contain','motion':'hold',
                          'refinement':'Optional verified panel/focus pass; do not crop automatically.'})
            cursor+=dt
    return shots

def run(args):
    records=load_evidence(args.results)
    out=Path(args.output_dir) if args.output_dir else ROOT/'pipeline-results'
    out.mkdir(parents=True,exist_ok=True)
    def remote(name,system,user,max_tokens):
        fingerprint=hashlib.sha256(json.dumps({'provider':args.provider,'model':args.model,
            'system':system,'user':user,'max_tokens':max_tokens},sort_keys=True).encode()).hexdigest()
        cache=out/'requests'/(fingerprint+'.json')
        if cache.exists():
            result=json.loads(cache.read_text(encoding='utf-8'))
            attempts=list(cache.parent.glob(fingerprint+'-attempt-*.json'))
            if getattr(args,'retry_failed',False) and result.get('status') in {429,500,502,503,504,'transport_error','quota_hold','budget_hold'} and len(attempts)<2:
                result=call(args.provider,args.model,system,user,[],max_tokens=max_tokens)
                result['request_digest']=fingerprint
                dump(cache.parent/(fingerprint+f'-attempt-{len(attempts)+1}.json'),result)
                dump(cache,result)
        else:
            result=call(args.provider,args.model,system,user,[],max_tokens=max_tokens)
            result['request_digest']=fingerprint
            dump(cache.parent/(fingerprint+'-attempt-1.json'),result)
            dump(cache,result)
        dump(out/(name+'.json'),result)
        return result
    build_index(records,out/'evidence.sqlite')
    chapter=max(p['chapter'] for d in records for p in d['config']['pages'])
    def compact(items):
        return [{'pages':[{'page_id':p['page_id'],'beats':p['beats']} for p in d['pages']],
                 'entities':d['entities']} for d in items]
    context=compact(prefix_context(records,chapter))
    audit_system='''Audit extracted manga evidence for continuity, without outside knowledge.
    Return JSON {identity_proposals:[{ids:[string],canonical_name:string|null,
    source_beats:[string],confidence,reason}], relationships:[{from_id,to_id,relation,
    source_beats:[string],status}], contradictions:[{source_beats:[string],problem}],
    recheck_pages:[{page_id,question}], open_threads:[string]}.
    Do not merge people just because hair, gender, role or clothing match. Prefer a
    proposal requiring visual review to a confident invented identity. Do not silently
    rewrite extraction. Contradictory evidence should remain visible for source checks.
    '''
    result=remote('continuity-audit',audit_system,json.dumps(context),2400)
    dump(out/'continuity-audit.json',result)
    print('Continuity audit:',result.get('status'),result.get('finish'),result.get('parse_error'),flush=True)
    if result.get('status')!=200 or result.get('finish') not in {'stop','STOP'} or not check_continuity(result.get('output'),records):
        dump(out/'gate.json',{'status':'incomplete_continuity','publication_approved':False})
        return
    # Audit proposes corrections; unverified proposals are not injected as established facts.
    all_scripts=[]
    local_issues=[]
    for c in sorted({p['chapter'] for d in records for p in d['config']['pages']}):
        chapter_records=[d for d in records if d['config']['pages'][0]['chapter']==c]
        writer=STYLE+'''
        Produce JSON {beat_selection:[{beat_id,decision:"narrate"|"visual"|"omit",reason}],
        scene_plan:[{situation,pressure,action,reaction,exit,source_beats:[string]}],
        segments:[{id,text,source_beats:[string],source_pages:[string]}]}.
        Plan coherent scenes first; a page boundary is not a scene boundary.
        Write only the CURRENT chapter. Use PRIOR chapter evidence for continuity only,
        never as events to narrate again. A segment should use clear sentences for
        one coherent action or discovery. Cite only CURRENT source beat IDs in ascending
        page order. source_pages must exactly match the pages of source_beats, deduplicated
        in reference order. Do not add claims unsupported by cited beats. Do not invent
        introductions, endings, kinship, names, motives, powers or scene transitions.
        Unknown identity should remain unnamed. Preserve important evidence uncertainty.
        Account for EVERY current beat in beat_selection, exactly once. This is an
        editorial coverage check. A consequence, discovery or explanation belongs in
        narration; a gesture or incidental visual detail usually does not. All scene
        plan claims need evidence, including pressure and exit. Use empty strings for
        unstated motivations instead of inventing them. Do not introduce a name before
        the beat where it is learned. Keep the exact exception in a discovery.
        '''
        payload={'current_chapter':c,'prior':compact(prefix_context(records,c-1)),
                 'current':compact(prefix_context(chapter_records,c))}
        r=remote(f'narration-ch{c}',writer,json.dumps(payload),4000)
        if 'output' in r:r['reference_errors']=check_script(r['output'],chapter_records)
        dump(out/f'narration-ch{c}.json',r)
        print('Narration chapter',c,r.get('status'),r.get('reference_errors'),flush=True)
        if r.get('status')!=200 or r.get('finish') not in {'stop','STOP'} or r.get('reference_errors') or 'output' not in r:
            dump(out/'gate.json',{'status':'incomplete_narration','publication_approved':False})
            return
        plan=r['output'].get('scene_plan')
        known={b['id'] for d in chapter_records for p in d['output']['pages'] for b in p['beats']}
        selection=r['output'].get('beat_selection')
        if not isinstance(selection,list) or any(not isinstance(s,dict) or s.get('beat_id') not in known or
            s.get('decision') not in {'narrate','visual','omit'} or not isinstance(s.get('reason'),str) for s in selection) or \
            len(selection)!=len(known) or {s['beat_id'] for s in selection}!=known:
            dump(out/'gate.json',{'status':'invalid_beat_selection','publication_approved':False})
            return
        if not isinstance(plan,list) or not plan or any(not isinstance(s,dict) or
            any(not isinstance(s.get(k),str) for k in ['situation','pressure','action','reaction','exit']) or
            not isinstance(s.get('source_beats'),list) or not s['source_beats'] or
            any(b not in known for b in s['source_beats']) for s in plan):
            dump(out/'gate.json',{'status':'invalid_scene_plan','publication_approved':False})
            return
        all_scripts.extend(r['output'].get('segments',[]))
        local_issues.extend(editorial_checks(r['output']))
    script={'segments':all_scripts}
    errors=check_script(script,records)
    dump(out/'narration.json',{'script':script,'reference_errors':errors,
                            'evidence_digest':hashlib.sha256(json.dumps([d['output'] for d in records],sort_keys=True).encode()).hexdigest(),
                            'publication_status':'SOURCE REVIEW REQUIRED; reference validity is not factual verification'})
    if not errors:
        dump(out/'shots.json',{'shots':plan_shots(script,records),
                              'status':'Draft page-first plan; no audio or render yet'})
    critic='''Compare each narration claim against the cited extracted facts. Return JSON
    {issues:[{segment_id,claim,reason,source_beats:[string],needs_image_recheck:boolean}],
    omitted_essential_beats:[string],repeated_segments:[string]}.
    Flag unsupported causality, identity merges, invented motives, future spoilers,
    hypotheses stated as facts, and lost changes of place/time. Check who owns
    obligations, speakers, obscured figures, and whether actions are merely intended
    or completed. Preserve conditions and important thoughts spanning page boundaries.
    Flag vague substitutes for essential dialogue, decorative metaphors, page/view
    commentary, and invented eye-opening actions. Judge whether the listener follows
    the conflict and its consequences, not just whether isolated facts are mentioned.
    You cannot verify the
    images: state that limitation. Do not approve facts simply because the story flows.
    omitted_essential_beats and repeated_segments must contain ONLY exact IDs,
    never IDs with parenthetical explanations. Put explanations in issues instead.
    Check loss of a named language, conditions and exceptions; skipped explanations
    for conclusions; names introduced before the introduction; and incidental detail
    displacing the plot. Treat quoted thoughts rendered as speech as a grounding issue.
    '''+critic_style()
    r=remote('narration-critic',critic,json.dumps({'evidence':context,'script':script}),2400)
    dump(out/'narration-critic.json',r)
    print('Narration critique:',r.get('status'),flush=True)
    valid=r.get('status')==200 and r.get('finish') in {'stop','STOP'} and check_critic(r.get('output'),script,records)
    issues=r.get('output',{}) if valid else {}
    dump(out/'gate.json',{'status':('needs_narration_revision' if any(issues.get(k) for k in
        ['issues','omitted_essential_beats','repeated_segments']) or local_issues else 'needs_source_review') if valid else 'incomplete_critic',
        'critic_valid':valid,'local_editorial_issues':local_issues,'publication_approved':False,'manually_rewritten':False})

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--results',nargs='+',required=True)
    ap.add_argument('--provider',choices=['gemini','groq'],default='gemini')
    ap.add_argument('--model',default='gemini-4-hydrogen')
    ap.add_argument('--output-dir',help='Separate experiment directory; preserves older drafts')
    ap.add_argument('--retry-failed',action='store_true',help='Explicit bounded retry of transient failures; quota holds still apply')
    run(ap.parse_args())
