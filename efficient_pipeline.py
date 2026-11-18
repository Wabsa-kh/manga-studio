"""V5: native pages -> atomic evidence -> targeted cross-model check -> chapter draft/review.

No publication or rendering. Images, memory, prompts, schemas and models bind caches.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import copy
from jsonschema import Draft202012Validator
from storybench import ROOT,DEFAULT_SOURCE,inventory,call,dump,resolve_page
from evidence_v5 import (obj,arr,enum,S,NS,REFS,EXTRACT_SCHEMA,EXTRACT_PROMPT,
    validate_evidence,item_index,history_refs,prompt_memory,review_targets,archive_records,extraction_request_schema)
from story_pipeline import editorial_checks
from narration_contract import writer_style,critic_style
from series_inventory import chapter_label,chapter_sort,chapter_from_page
from narrative_continuity import chapter_handoff

VERIFY_SCHEMA=obj(observations=arr(obj(page_id=S,source_text=S,actor_or_speaker=S,observation=S)),
    issues=arr(obj(page_id=S,source_ids=REFS,problem=S,severity=enum('blocking','warning'))),
    unreadable_pages=REFS)
WRITE_SCHEMA=obj(scenes=arr(obj(situation=S,action=S,consequence=S,source_ids=REFS)),
    selection=arr(obj(source_id=S,decision=enum('narrate','merge','visual','omit','needs_review'),reason=S,covered_by=REFS)),
    segments=arr(obj(id=S,text=S,source_ids=REFS)))
CRITIC_SCHEMA=obj(issues=arr(obj(segment_id=NS,source_ids=REFS,problem=S,
    category=enum('source','chronology','coverage','style'),needs_image_recheck={'type':'boolean'})),
    omitted_essential_ids=REFS)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()



def writing_prompt():
    return writer_style()+'''
        Write ONLY this current chapter, using earlier evidence only for continuity.
        Plan scenes across page boundaries and account for every current item in selection.
        Repeated lines and redundant reactions may be merged into a coherent exchange.
        Use decision=merge and covered_by=[cited item IDs] to explain which narrated
        evidence covers that item's meaning. For other decisions covered_by is empty
        unless an omitted/visual item is redundant with explicitly cited evidence.
        Do not recite every plot-labelled item separately; preserve its unique meaning.
        Preserve plot-critical exchanges, reasons, negations, conditions and discoveries.
        A thought is not spoken dialogue; do not convert a threat into a completed event.
        Treat name_reveals as a time constraint: do not use a name in an earlier scene.
        Do not put page/credit/title metadata, source commentary or incidental gestures in
        narration. Source IDs must be exact and ordered. Each segment covers a coherent
        action/exchange. Use as many clear sentences as that exchange needs; do not pack
        events into long sentences to fit a segment. Cite current items only. Never invent a missing
        cause. Plan motivations must be source-supported. Mark an unresolved plot item
        needs_review rather than writing around it. Return the requested schema only.'''


def critique_prompt():
    return '''Review source-grounded narration and editorial coverage against the atomic
        current evidence. You do not see images and cannot establish extraction accuracy.
        Check each claim, thought versus speech, identity and name reveal order, missing
        reasons/conditions/language discoveries, invented motives, threatened versus completed
        actions, unnecessary gestures, layout commentary and repeated information. An ID
        citation is not proof a sentence is supported. Return exact IDs, never ID+explanation.
        Flag essential omissions. Do not invent a quota of problems or approve source truth.'''+critic_style()


def batches(pages,size=4):
    for chapter in sorted({p['chapter'] for p in pages},key=chapter_sort):
        current=[p for p in pages if p['chapter']==chapter]
        for start in range(0,len(current),size):
            yield current[start:start+size],current[max(0,start-1):start]


def schema_errors(schema,output):
    return [e.message for e in Draft202012Validator(schema).iter_errors(output)][:12]


def check_verification(output,selected,known):
    errors=schema_errors(VERIFY_SCHEMA,output)
    if errors:return errors
    pages={p['page_id'] for p in selected}
    for row in output['observations']+output['issues']:
        if row['page_id'] not in pages:errors.append('Verifier cites unsent page')
    for row in output['issues']:
        if not row['problem'].strip():errors.append('Empty verification issue')
        if any(i not in known or known[i]['page_id']!=row['page_id'] for i in row['source_ids']):
            errors.append('Verifier cites wrong-page/unknown evidence')
    if any(p not in pages for p in output['unreadable_pages']):errors.append('Unreadable page not sent')
    covered={o['page_id'] for o in output['observations']}|set(output['unreadable_pages'])
    if pages-covered:errors.append('Verifier omitted supplied pages')
    return list(dict.fromkeys(errors))


def chapter_context(records,chapter):
    """Chapter batches are isolated; never put a future chapter in writer context."""
    def ch(record):return chapter_from_page(record['pages'][0]['page_id'])
    current=[r for r in records if ch(r)==chapter]
    prior=[r for r in records if chapter_sort(ch(r))<chapter_sort(chapter)]
    focus={e['id'] for r in current for e in r['entities']}
    memory=prompt_memory(prior,focus_ids=sorted(focus))
    memory['chapter_handoff']=chapter_handoff(prior,current)
    return current,memory


def check_draft(output,current,prior):
    errors=schema_errors(WRITE_SCHEMA,output)
    if errors:return errors
    known=item_index(current);ordered=list(known);rank={s:i for i,s in enumerate(ordered)}
    temporal_rank=dict(rank)
    # A continued thought may finish after intervening action on the next page.
    # Anchor its continuation to the opening fragment; this preserves the complete
    # thought without falsely treating the following intervening action as a spoiler.
    for record in current:
        for thread in record['threads']:
            refs=thread['source_ids']
            if thread['status']=='resolved' and len(refs)>1 and all(i in known and known[i]['kind'] in {'thought','narration'} for i in refs) and len({known[i]['speaker'] for i in refs})==1 and known[refs[0]]['speaker'] is not None:
                anchor=min(rank[i] for i in refs)
                for i in refs:temporal_rank[i]=min(temporal_rank[i],anchor)
    selection=output['selection'];selected=[r['source_id'] for r in selection]
    if len(selected)!=len(set(selected)) or set(selected)!=set(known):errors.append('Every current item needs exactly one selection decision')
    if not output['segments'] or not output['scenes']:errors.append('Empty scene plan or narration')
    segments=output['segments'];ids=[s['id'] for s in segments]
    if len(ids)!=len(set(ids)):errors.append('Duplicate segment ID')
    cited=set();last=-1
    for segment in segments:
        refs=segment['source_ids']
        if not segment['text'].strip():errors.append('Empty narration text')
        if not refs or any(i not in known for i in refs):errors.append('Narration cites unknown/future/prior-chapter item');continue
        if refs!=sorted(set(refs),key=lambda i:rank[i]):errors.append('Source IDs must be unique and ordered')
        if min(temporal_rank[i] for i in refs)<last:errors.append('Narration moves backwards')
        last=max(temporal_rank[i] for i in refs);cited.update(refs)
        for record in current:
            for reveal in record['name_reveals']:
                if re.search(r'\b'+re.escape(reveal['name'])+r'\b',segment['text'],re.I):
                    revealed=[rank[i] for i in reveal['source_ids'] if i in rank]
                    if revealed and min(rank[i] for i in refs)<min(revealed) and not set(reveal['source_ids'])&set(refs):
                        errors.append('Name used before its evidenced introduction')
    for row in selection:
        if row['decision']=='narrate' and row['source_id'] not in cited:errors.append('Selected narration item was not cited')
        if any(i not in cited for i in row['covered_by']):errors.append('Coverage merge points to uncited evidence')
        if row['decision']=='merge' and not row['covered_by']:errors.append('Merged item needs cited coverage evidence')
        if row['source_id'] in known and known[row['source_id']]['importance']=='plot' and row['decision'] in {'omit','visual','needs_review'} and not row['covered_by']:
            errors.append('Plot-critical evidence left out or unresolved')
    for scene in output['scenes']:
        if not scene['source_ids'] or any(i not in known for i in scene['source_ids']):errors.append('Scene plan lacks current source evidence')
    errors.extend(i['problem'] for i in editorial_checks({'segments':segments}))
    return list(dict.fromkeys(errors))


def check_critique(output,draft,known):
    errors=schema_errors(CRITIC_SCHEMA,output)
    if errors:return errors
    ids={s['id'] for s in draft['segments']}
    for issue in output['issues']:
        if issue['segment_id'] is not None and issue['segment_id'] not in ids:errors.append('Unknown critic segment')
        if any(i not in known for i in issue['source_ids']):errors.append('Unknown critic evidence')
    if any(i not in known for i in output['omitted_essential_ids']):errors.append('Unknown omitted item')
    return errors


class Requests:
    def __init__(self,out,limit,retry=False,shared=None):
        self.out=Path(out)/'requests';self.out.mkdir(parents=True,exist_ok=True)
        self.limit=limit;self.retry=retry;self.started_this_run=0
        self.shared=Path(shared) if shared else None
        if self.shared:self.shared.mkdir(parents=True,exist_ok=True)

    def run(self,stage,provider,model,system,user,pages,schema,tokens,thinking):
        # Byte hash check runs even for cached stages. No resized assets are created.
        pages=[resolve_page(p) for p in pages]
        config={'version':5,'stage':stage,'provider':provider,'model':model,'system':system,
            'user':user,'pages':pages,'schema':schema,'tokens':tokens,'thinking':thinking,
            'image_policy':'original-bytes-v1'}
        if provider=='gemini':config['generation_policy']='native-temperature-1-v1'
        elif provider in {'openrouter','groq'}:config['generation_policy']='schema-transport-and-thinking-v2'
        name=digest(config);path=self.out/(name+'.json')
        shared=self.shared/(name+'.json') if self.shared else None
        if not path.exists() and shared and shared.exists():
            cached=json.loads(shared.read_text(encoding='utf-8'))
            if complete(cached):dump(path,cached)
        prior=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if prior is not None:
            if complete(prior):
                if shared:dump(shared,prior)
                return prior
            attempts=list(self.out.glob(name+'-attempt-*.json'))
            dispatched=[p for p in attempts if json.loads(p.read_text(encoding='utf-8')).get('status') not in {'quota_hold','budget_hold','run_budget_hold'}]
            if not self.retry or len(dispatched)>=2:return prior
            if prior.get('status') not in {429,500,502,503,504,'transport_error','quota_hold','budget_hold','interrupted_unknown'}:return prior
        attempts=list(self.out.glob(name+'-attempt-*.json'))
        # Started receipts persist before the network call. A crash is not replayed
        # implicitly because an unknown attempt may have reached the provider.
        if self.started_this_run>=self.limit:
            return {'status':'run_budget_hold','error':'Per-run request bound reached'}
        attempt=self.out/(name+f'-attempt-{len(attempts)+1}.json')
        receipt={'status':'interrupted_unknown','config':config,'started_utc':datetime.now(timezone.utc).isoformat()}
        if not path.exists() and attempts and not self.retry:return json.loads(attempts[-1].read_text(encoding='utf-8'))
        dump(attempt,receipt);dump(path,receipt)
        self.started_this_run+=1
        print(stage,provider,model,'images',len(pages),'thinking',thinking,flush=True)
        result=call(provider,model,system,json.dumps(user,ensure_ascii=False),pages,
                    max_tokens=tokens,thinking=thinking,response_schema=schema)
        result['config']=config;dump(attempt,result);dump(path,result)
        if shared and complete(result):dump(shared,result)
        print(stage,result.get('status'),result.get('finish'),result.get('seconds'),flush=True)
        return result


def complete(result):return result.get('status')==200 and result.get('finish') in {'STOP','stop'} and 'output' in result


def run(args):
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    pages=inventory(Path(args.source),chapters=args.chapters)
    if args.page_id:
        selected=set(args.page_id);pages=[p for p in pages if p['page_id'] in selected]
        if selected!={p['page_id'] for p in pages}:raise ValueError('Unknown selected page')
    if not pages:raise ValueError('No source pages')
    plan={'sources':pages,'batch_pages':args.batch_pages,'extractor':[args.provider,args.model],
          'verifier':[args.verifier_provider,args.verifier_model],
          'writer':[args.writer_provider,args.writer_model],'thinking':args.thinking,
          'max_output_tokens':args.max_tokens,'image_policy':'original-bytes-v1'}
    if getattr(args,'repair_evidence',False):plan['bounded_evidence_repair']=1
    imported=[]
    if args.resume_evidence:
        upstream=json.loads(Path(args.resume_evidence).read_text(encoding='utf-8'))
        imported=upstream['records']
        plan['upstream_evidence_digest']=digest(upstream)
        imported_ids=[p['page_id'] for record in imported for p in record['pages']]
        if imported_ids!=[p['page_id'] for p in pages[:len(imported_ids)]]:
            raise ValueError('Imported evidence must be an exact chronological source prefix')
        source_hashes={p['page_id']:p['sha256'] for p in upstream['source_pages']}
        known_history=[]
        for record in imported:
            metadata=[p for p in pages if p['page_id'] in {q['page_id'] for q in record['pages']}]
            if any(source_hashes.get(p['page_id'])!=p['sha256'] for p in metadata):raise ValueError('Imported source hash mismatch')
            errors=validate_evidence(record,metadata,history_refs(known_history))
            if errors:raise ValueError('Invalid imported evidence: '+str(errors))
            known_history.append(record)
    manifest=out/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8'))['plan_hash']!=digest(plan):
        raise ValueError('Run configuration changed; use a separate output directory')
    dump(manifest,{'plan':plan,'plan_hash':digest(plan),'publication_approved':False})
    remote=Requests(out,args.request_budget,args.retry_failed,args.cache_dir)
    def stop(status,**details):
        gate={'status':status,'publication_approved':False,**details}
        dump(out/'gate.json',gate);print(json.dumps(gate,indent=2),flush=True);return gate
    records=list(imported)
    processed={p['page_id'] for record in records for p in record['pages']}
    remaining=[p for p in pages if p['page_id'] not in processed]
    for primary,context in batches(remaining,args.batch_pages):
        if not context:
            position=pages.index(primary[0])
            if position and pages[position-1]['chapter']==primary[0]['chapter']:context=[pages[position-1]]
        memory=prompt_memory(records)
        if memory['cast_truncated']:return stop('needs_memory_retrieval',reason='Cast exceeds prompt bound; no silent identity forgetting')
        if memory['narrative_memory']['required_overflow']:return stop('needs_narrative_retrieval',reason='Required narrative frame/gap context exceeds bound')
        user={'primary_page_ids':[p['page_id'] for p in primary],
              'context_only_page_ids':[p['page_id'] for p in context],'prior_evidence':memory}
        r=remote.run('extract',args.provider,args.model,EXTRACT_PROMPT,user,
                     context+primary,extraction_request_schema(),args.max_tokens,args.thinking)
        dump(out/('extract-'+primary[0]['page_id']+'.json'),r)
        if not complete(r):return stop('incomplete_extraction',provider_status=r.get('status'),page_id=primary[0]['page_id'])
        errors=schema_errors(extraction_request_schema(),r['output'])+validate_evidence(r['output'],primary,history_refs(records))
        if errors and getattr(args,'repair_evidence',False):
            repair_prompt=EXTRACT_PROMPT+'''
ONE BOUNDED SOURCE CORRECTION
Re-read the supplied original images and correct the candidate against the validator
feedback. Do not invent facts merely to satisfy validation. Include every referenced
entity in entities with a source-grounded appearance; unknown actors may stay null.
Do not emit state/name entity IDs without their registry entries. regions MUST be
[left,top,width,height], not [left,top,right,bottom]: for corners .7,.1,.8,.3 the
correct region is [.7,.1,.1,.2]. A source_ids entry is an ATOMIC ITEM ID such as
ch0-p001-i01, never a bare page ID such as ch0-p001. Narrative links must anchor to
actual items supplying their meaning; do not convert page IDs to arbitrary item IDs.
Retain unknown transitions and unsupported identities as uncertain. Return the full
corrected evidence schema, not a patch, and recheck all references before returning.
'''
            candidate=remote.run('repair-extract-'+primary[0]['page_id'],args.provider,args.model,repair_prompt,
                {**user,'candidate':r['output'],'validation_errors':errors},context+primary,
                extraction_request_schema(),args.max_tokens,args.thinking)
            dump(out/('repair-extract-'+primary[0]['page_id']+'.json'),candidate)
            if not complete(candidate):return stop('incomplete_extraction_repair',provider_status=candidate.get('status'),page_id=primary[0]['page_id'])
            r=candidate;errors=schema_errors(extraction_request_schema(),r['output'])+validate_evidence(r['output'],primary,history_refs(records))
        if errors:return stop('invalid_evidence',errors=errors,page_id=primary[0]['page_id'])
        records.append(r['output'])
        archive_records(out/'evidence.sqlite',records,pages)
    dump(out/'evidence.json',{'records':records,'source_pages':pages,'source_reviewed':False})
    if args.phase=='extract':return stop('extraction_draft_complete',source_reviewed=False)
    known=item_index(records);targets=review_targets(records,args.max_review_pages)
    # Include a deterministic source-hash sentinel even when the extractor reports
    # no uncertainty. This catches some confident mistakes without repeating all pages.
    selected=list(targets['selected'])
    sentinel=min(pages,key=lambda p:p['sha256'])['page_id']
    if sentinel not in selected:
        selected.append(sentinel)
    selected_pages=[p for p in pages if p['page_id'] in selected]
    # One preceding page for each selected region preserves speaker/identity context.
    context_ids=set(selected)
    for index,page in enumerate(pages):
        if page['page_id'] in selected and index and pages[index-1]['chapter']==page['chapter']:
            context_ids.add(pages[index-1]['page_id'])
    sent=[p for p in pages if p['page_id'] in context_ids]
    targets['deferred']={pid:questions for pid,questions in targets['deferred'].items() if pid not in context_ids}
    claims={i:item for i,item in known.items() if item['page_id'] in context_ids}
    verify_prompt='''Inspect source images against these fallible extraction claims.
    First read the relevant text and identify visible actors and balloon tails yourself,
    then compare claims. You see the extraction, so this is targeted verification, NOT
    a blind independent reader. Do not agree merely because a claim is confidently stated.
    Distinguish speech/thought, speaker, names, negation, conditional thoughts, intended
    actions, changing comprehension and visual identity. Quote short source text in
    observations and explain actor features; do not output private reasoning. List factual
    discrepancies as blocking issues. Leave uncertain identity unresolved; never resolve
    by majority vote. No publication approval. Observe every supplied page, context included.
    Use exact supplied source IDs only; unreadable text must remain unreadable.'''
    verify_schema=copy.deepcopy(VERIFY_SCHEMA)
    page_enum=enum(*[p['page_id'] for p in sent])
    for field in ['observations','issues']:
        verify_schema['properties'][field]['items']['properties']['page_id']=page_enum
    verify_schema['properties']['unreadable_pages']=arr(page_enum)
    r=remote.run('targeted_verify',args.verifier_provider,args.verifier_model,verify_prompt,
        {'claims':claims,'questions':{pid:q for pid,q in targets['selected'].items() if pid in context_ids},
         'sentinel_page':sentinel,'supplied_page_ids':[p['page_id'] for p in sent]},sent,
        verify_schema,6000,'medium')
    dump(out/'verification.json',r)
    if not complete(r):return stop('incomplete_verification',provider_status=r.get('status'))
    errors=check_verification(r['output'],sent,known)
    if errors:return stop('invalid_verification',errors=errors)
    blocking=[issue for issue in r['output']['issues'] if issue['severity']=='blocking']
    if blocking or r['output']['unreadable_pages'] or targets['deferred']:
        return stop('needs_evidence_review',blocking=blocking,unreadable=r['output']['unreadable_pages'],deferred=targets['deferred'])
    if args.phase=='verify':return stop('sampled_verification_complete',limitation='Targeted sample only, not full source verification')
    for chapter in sorted({p['chapter'] for p in pages},key=chapter_sort):
        current,prior=chapter_context(records,chapter)
        if prior['chapter_handoff']['prior_narrative_memory']['required_overflow']:
            return stop('needs_narrative_retrieval',chapter=chapter,reason='Required earlier gaps exceed writer context bound')
        writer=writing_prompt()
        critic=critique_prompt()
        feedback=None;previous=None
        existing_path=out/f'narration-ch{chapter}.json'
        existing=json.loads(existing_path.read_text(encoding='utf-8')) if existing_path.exists() else None
        compatible=False
        if existing and complete(existing):
            config=existing.get('config',{});payload=config.get('user',{})
            compatible=(config.get('system')==writer and config.get('schema')==WRITE_SCHEMA and
                config.get('provider')==args.writer_provider and config.get('model')==args.writer_model and
                payload.get('current')==current and payload.get('prior')==prior)
        start_revision=1 if compatible and existing['config']['stage'].startswith('revise') else 0
        for revision in range(start_revision,args.max_revisions+1):
            payload={'current':current,'prior':prior}
            if feedback:payload.update(previous_draft=previous,review_feedback=feedback,
                instruction='Revise automatically from evidence and feedback; do not invent facts or weaken review criteria.')
            if compatible:
                r=existing;compatible=False
            else:
                r=remote.run(('write' if revision==0 else 'revise')+'-ch'+str(chapter),
                    args.writer_provider,args.writer_model,writer,payload,[],WRITE_SCHEMA,20000,'low')
            dump(out/f'narration-ch{chapter}-v{revision}.json',r);dump(out/f'narration-ch{chapter}.json',r)
            if not complete(r):return stop('incomplete_narration',chapter=chapter,provider_status=r.get('status'))
            draft=r['output'];errors=check_draft(draft,current,prior)
            if errors:
                feedback={'local_errors':errors};previous=draft
                if revision==args.max_revisions:return stop('needs_narration_revision',chapter=chapter,errors=errors)
                continue
            r=remote.run('critic-ch'+str(chapter),args.verifier_provider,args.verifier_model,critic,
                {'current_evidence':current,'prior':prior,'draft':draft},[],CRITIC_SCHEMA,6000,'medium')
            dump(out/f'critic-ch{chapter}-v{revision}.json',r);dump(out/f'critic-ch{chapter}.json',r)
            if not complete(r):return stop('incomplete_critic',chapter=chapter,provider_status=r.get('status'))
            errors=check_critique(r['output'],draft,item_index(current))
            if errors:return stop('invalid_critic',chapter=chapter,errors=errors)
            if r['output']['issues'] or r['output']['omitted_essential_ids']:
                feedback=r['output'];previous=draft
                if revision==args.max_revisions:return stop('needs_narration_revision',chapter=chapter,critique=r['output'])
            else:break
    return stop('drafts_need_source_review',limitation='Targeted review and text checks are not full factual approval')


def parser():
    p=argparse.ArgumentParser()
    p.add_argument('--source',default=DEFAULT_SOURCE);p.add_argument('--chapters',nargs='+',type=chapter_label,default=[0,1])
    p.add_argument('--page-id',nargs='+');p.add_argument('--batch-pages',type=int,choices=range(1,18),default=4)
    p.add_argument('--provider',choices=['gemini','openrouter'],default='gemini');p.add_argument('--model',default='gemini-3.8-flash')
    p.add_argument('--verifier-provider',choices=['gemini','openrouter'],default='openrouter')
    p.add_argument('--verifier-model',default='nvidia/nemotron-3.5-super-vl:free')
    p.add_argument('--writer-provider',choices=['gemini','openrouter'],default='gemini');p.add_argument('--writer-model',default='gemini-3.8-flash')
    p.add_argument('--thinking',choices=['low','medium','high'],default='high');p.add_argument('--max-tokens',type=int,default=24000)
    p.add_argument('--max-review-pages',type=int,choices=[1,2,3],default=2)
    p.add_argument('--request-budget',type=int,choices=range(1,13),default=12)
    p.add_argument('--retry-failed',action='store_true');p.add_argument('--phase',choices=['extract','verify','all'],default='all')
    p.add_argument('--output-dir',default=str(ROOT/'experiments/revision5/main'))
    p.add_argument('--cache-dir',default=str(ROOT/'cache-v5'))
    p.add_argument('--max-revisions',type=int,choices=[0,1],default=1)
    p.add_argument('--resume-evidence',help='Import a hash-matched V5 source prefix; does not approve its accuracy')
    p.add_argument('--repair-evidence',action='store_true',help='Allow one source-grounded correction per invalid extraction batch; never approves semantic truth')
    return p


if __name__=='__main__':run(parser().parse_args())
