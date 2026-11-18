"""Bounded NVIDIA Nano Omni experiments; benchmarks are not source approvals."""
import argparse,json,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from nim_client import Client
from storybench import ROOT,DEFAULT_SOURCE,inventory,dump
from evidence_v5 import EXTRACT_PROMPT,extraction_request_schema,validate_evidence,history_refs
from efficient_pipeline import schema_errors

OUT=ROOT/'experiments/nim-nano-v1'
TEXT_SCHEMA={'type':'object','properties':{'page_id':{'type':'string'},'text_blocks':{'type':'array','items':{'type':'object','properties':{'text':{'type':'string'},'kind':{'type':'string'},'speaker_description':{'type':['string','null']}},'required':['text','kind','speaker_description'],'additionalProperties':False}},'uncertainties':{'type':'array','items':{'type':'string'}}},'required':['page_id','text_blocks','uncertainties'],'additionalProperties':False}
BASE='Read manga right-to-left. Extract all readable dialogue, thoughts and narration in source reading order. Distinguish text type, preserve negations, and use balloon tails and character appearances for speakers. Unknown speakers stay null. Do not infer kinship, intentions or future outcomes. Return JSON only.'
FOCUSED=BASE+'''
Before ordering text, identify the panel groups. Read a normal manga row from RIGHT
to LEFT, then move down. Within each panel follow the intended balloon flow. Never
sort all page text globally or scan the page left-to-right. Check the small balloon
tails against the actual mouths/bodies, including off-panel speakers. The closest
drawn face is not necessarily the speaker. Recheck each attribution independently.
Rectangular narration boxes are not speech. Their first-person narrator must not be
assigned to a nearby adult just because that adult spoke before. Use null when the
narrator or speaker is not established. Preserve each meaningful text region; merge
connected balloons only if their order and speaker remain clear. Keep threats,
negation, conditions and actual source uncertainty. Punctuation is not spoken words;
unknown fictional glyphs are unreadable, not English you should invent. Do not use
character names absent from the supplied pages. Check every region once more for
missing words, type mistakes and reversed exchanges. Output only the requested JSON.
'''

def quality(client):
    pages=inventory(Path(DEFAULT_SOURCE),[0]);schema=TEXT_SCHEMA
    for budget in [1024,4096,16384]:
        client.run(f'focused-p2-r{budget}',FOCUSED,'Read this original page; return page_id, text_blocks and uncertainties.',[pages[1]],max_tokens=24576,reasoning_budget=budget,schema=schema)
        if client.stop.is_set():return
    # Held-out pages are not accompanied by expected answers or source-specific hints.
    def held(case):
        page,budget=case
        return client.run(f'heldout-p{page+1}-r{budget}',FOCUSED,'Read this original page; return page_id, text_blocks and uncertainties.',[pages[page]],max_tokens=16384,reasoning_budget=budget,schema=schema)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(held,[(2,1024),(2,4096),(6,1024),(6,4096)]))
    if client.stop.is_set():return
    multi={'type':'object','properties':{'pages':{'type':'array','items':TEXT_SCHEMA}},'required':['pages'],'additionalProperties':False}
    client.run('two-pages-p3-p4',FOCUSED,'Read both supplied pages once, in supplied order. Preserve any continued narration without inventing a cause.',pages[2:4],max_tokens=16384,reasoning_budget=4096,schema=multi)
    if client.stop.is_set():return
    # Production-schema interoperability: original source images, no reference answer.
    for budget in [1024,4096]:
        primary=pages[:4];user=json.dumps(dict(primary_page_ids=[p['page_id'] for p in primary],context_only_page_ids=[],prior_evidence={}))
        r=client.run(f'production-four-pages-r{budget}',EXTRACT_PROMPT+'\nRegions use [left,top,width,height], NOT corners. All source references must be item IDs, and every referenced actor must exist in entities.',user,primary,max_tokens=24576,reasoning_budget=budget,schema=extraction_request_schema())
        errors=schema_errors(extraction_request_schema(),r['output']) if r.get('output') is not None else ['No complete JSON output']
        if not errors:errors+=validate_evidence(r['output'],primary,history_refs([]))
        dump(OUT/f'production-four-pages-r{budget}-audit.json',dict(errors=errors,source_reviewed=False,publication_approved=False))
        if client.stop.is_set():return

def load(client):
    # 32 small starts spread over one minute: below the user-reported 40 RPM.
    # Cap in-flight calls at four. This is not an attempt to trigger/exceed a limit.
    origin=time.monotonic()
    def one(i):
        delay=origin+i*1.9-time.monotonic()
        if delay>0:time.sleep(delay)
        return client.run(f'load-{i:02}', 'Return only JSON.','Return {"ok":true}.',max_tokens=1024,reasoning_budget=128)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,range(32)))
    dump(OUT/'load-result.json',dict(results=[{k:r.get(k) for k in ['name','status','finish','seconds','first_visible_text_seconds','usage','output']} for r in rows],scope='32 scheduled starts at 1.9-second spacing, up to four in flight. No claimed 40-RPM ceiling or daily allowance.',starts=client.gate.all_starts))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['quality','load']);args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);dump(OUT/'benchmark-bound.json',dict(max_calls=60,daily_planning_units=600000,max_rpm=32,max_load_concurrency=4,original_image_bytes=True,no_key_rotation=True,no_automatic_retries=True,reported_provider_rpm=40,provider_rpm_is_not_yet_verified=True))
    client=Client(OUT);globals()[args.phase](client)
