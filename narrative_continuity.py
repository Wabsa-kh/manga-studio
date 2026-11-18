"""Source-linked presentation frames and deferred reveals; never invent story time.

Links are extractor proposals, not verified facts. Missing legacy annotations stay
unknown. The ledger preserves the reader's order of discovery, including flashbacks.
"""
import copy,re,math
from collections import Counter

LINK_SCHEMA={
 'type':'object','additionalProperties':False,
 'properties':{
  'id':{'type':'string'},
  'kind':{'type':'string','enum':['scene_start','continuous','time_skip','flashback_start','flashback_return','parallel_cut','gap_open','gap_update','gap_resolved','uncertain']},
  'source_ids':{'type':'array','items':{'type':'string'},'minItems':1},
  'related_source_ids':{'type':'array','items':{'type':'string'}},
  'related_link_ids':{'type':'array','items':{'type':'string'}},
  'description':{'type':'string'},
  'basis':{'type':'string','enum':['printed_text','explicit_memory','visual_sequence','unknown']},
  'cue_text':{'type':'string'},
  'certainty':{'type':'string','enum':['explicit','inferred','uncertain']},
 },
 'required':['id','kind','source_ids','related_source_ids','related_link_ids','description','basis','cue_text','certainty']}

CONTINUITY_WRITING_RULES='''
NARRATIVE CONTINUITY — preserve the manga's order of disclosure:
Distinguish presentation order (what the reader learns now) from story time (when
the event occurred). A chapter boundary is not proof that time passed or that a
cliffhanger was resolved. Use the previous ending and current opening together.
Make a natural, brief handoff when grounded: for a visible awakening, "When he woke
up, he found himself in a room" is a possible structure, not a line to copy blindly.
Do not say "the next day", "after escaping", "meanwhile" or a cause unless evidenced.
If the manga cuts away from an unresolved scene, preserve that omission. Later
flashbacks may supply the missing events: narrate them where the manga reveals
them, connecting to the earlier scene only as far as the source supports. Never
move that explanation into an earlier chapter or imply the viewer already knew it.
After a flashback, return to its enclosing frame; past locations/injuries/possessions
do not automatically overwrite the character's state in the present frame.
Parallel scenes and uncertain transitions are not necessarily memories or next-day
events. Do not identify a flashback from dark borders or visual style alone.
Natural continuity usually needs a short connective clause, not a repeated recap,
chapter-number commentary, a cinematic explanation or extra invented transitions.
Ledger links are fallible source proposals. Unknown/missing links remain unknown;
an unresolved narrative gap is not a missing fact you should invent or explain.
'''

CONTINUITY_CRITIC_RULES='''
Check chapter handoffs and deferred reveals: preserve source presentation order,
not a reordered chronological reconstruction. Flag invented time skips, escapes,
causal bridges, premature cliffhanger resolutions, flashbacks treated as new present
events, and failures to return to the enclosing frame. A deliberate unanswered
scene is not an essential omission to fill. Connect a later explanation to earlier
evidence only when supported, and only at its point of disclosure. Link existence
does not certify extraction truth. Do not require an explicit transition sentence
when ordinary connected wording already makes the handoff clear.
'''

def flat_items(records):
    return [dict(i,page_id=p['page_id']) for r in records for p in r['pages'] for i in p['items']]

def validate_links(record,history=None):
    history=history or {};current={i['id']:i for i in flat_items([record])}
    ranks={i:n for n,i in enumerate(current)};prior=set(history.get('source_ids',[]));known_links=set(history.get('narrative_link_ids',[]));link_index={e['id']:e for e in history.get('narrative_links',[])};errors=[];seen=set();last=-1
    for link in record.get('narrative_links',[]):
        refs=link['source_ids'];ident=link['id']
        if ident in seen or ident in known_links:errors.append('Duplicate narrative link ID')
        seen.add(ident)
        if not refs or any(i not in current for i in refs):errors.append('Narrative anchor must cite current source');continue
        anchor=max(ranks[i] for i in refs)
        if anchor<last:errors.append('Narrative links must follow presentation order')
        last=anchor
        if not ident.startswith(current[refs[0]]['page_id']+'-n'):errors.append('Narrative link ID page mismatch')
        if any(i not in prior and (i not in current or ranks[i]>anchor) for i in link['related_source_ids']):errors.append('Narrative link cites unknown/future source')
        if any(i not in known_links for i in link['related_link_ids']):errors.append('Narrative link cites unknown/future narrative link')
        if not link['description'].strip():errors.append('Empty narrative link description')
        if link['basis'] in {'printed_text','explicit_memory'}:
            cue=' '.join(link['cue_text'].split()).casefold();texts=[' '.join(current[i]['text'].split()).casefold() for i in refs if current[i]['kind'] in {'speech','thought','narration'}]
            if not cue or not any(cue in text for text in texts):errors.append('Narrative time/memory cue is not in cited source text')
        elif link['cue_text']:errors.append('Nontext narrative basis cannot invent a printed cue')
        if link['kind']=='time_skip' and link['certainty']=='explicit' and link['basis']!='printed_text':errors.append('Explicit time skip needs printed time evidence')
        if link['kind']=='flashback_start' and link['certainty']=='explicit' and link['basis'] not in {'printed_text','explicit_memory'}:errors.append('Explicit flashback needs source time/memory evidence')
        if link['kind'] in {'gap_resolved','gap_update'} and (not link['related_link_ids'] or not link['related_source_ids']):errors.append('Gap resolution/update needs earlier gap and source links')
        if link['kind'] in {'gap_resolved','gap_update'}:
            for ref in link['related_link_ids']:
                origin=link_index.get(ref)
                if not origin or origin['kind']!='gap_open':errors.append('Resolution must link an earlier narrative gap')
                elif not set(origin['source_ids'])&set(link['related_source_ids']):errors.append('Resolution omits the linked gap source')
        if link['kind']=='flashback_return' and not any(link_index.get(ref,{}).get('kind')=='flashback_start' for ref in link['related_link_ids']):errors.append('Flashback return must identify an earlier flashback start')
        known_links.add(ident)
        link_index[ident]=link
    return list(dict.fromkeys(errors))

def ledger(records,cutoff_source_id=None):
    """Return only knowledge available at a presentation cutoff, never future reveals."""
    items=flat_items(records);rank={i['id']:n for n,i in enumerate(items)}
    if cutoff_source_id is not None and cutoff_source_id not in rank:raise ValueError('Unknown narrative cutoff')
    cutoff=rank[cutoff_source_id] if cutoff_source_id else len(items)-1
    visible={i['id']:i for i in items if rank[i['id']]<=cutoff};events=[];unannotated=[]
    for record in records:
        if not any(i['id'] in visible for i in flat_items([record])):continue
        if 'narrative_links' not in record:unannotated.extend(p['page_id'] for p in record['pages'] if any(i['id'] in visible for i in p['items']))
        for link in record.get('narrative_links',[]):
            if link['source_ids'] and all(i in visible for i in link['source_ids']):
                event=copy.deepcopy(link);event['reveal_rank']=max(rank[i] for i in link['source_ids']);events.append(event)
    events.sort(key=lambda e:e['reveal_rank'])
    gaps={};modes={};frame='unannotated';mode='unknown';stack=[];warnings=[];event_index=0
    for item in items[:cutoff+1]:
        n=rank[item['id']]
        while event_index<len(events) and events[event_index]['reveal_rank']<=n:
            e=events[event_index];event_index+=1;kind=e['kind'];explicit=e['certainty']=='explicit'
            if kind in {'scene_start','time_skip','parallel_cut'}:
                frame=e['id']
                if stack:mode='flashback' if mode=='flashback' and explicit else 'possible_flashback'
                else:mode='parallel' if kind=='parallel_cut' else 'current_frame' if explicit else 'uncertain_frame'
            elif kind=='flashback_start':
                stack.append((frame,mode,e['id']));frame=e['id'];mode='flashback' if explicit else 'possible_flashback'
            elif kind=='flashback_return':
                if stack and explicit and stack[-1][2] in e['related_link_ids']:frame,mode,_=stack.pop()
                else:frame=e['id'];mode='uncertain_frame';warnings.append(dict(link_id=e['id'],reason='Unverified or unmatched return to enclosing scene'))
            elif kind=='uncertain':frame=e['id'];mode='uncertain_frame'
            elif kind=='gap_open':gaps[e['id']]={**e,'status':'open','resolved_at':None,'developments':[]}
            elif kind in {'gap_resolved','gap_update'}:
                for target in e['related_link_ids']:
                    if target not in gaps:warnings.append(dict(link_id=e['id'],reason='Resolution does not reference an available open gap'));continue
                    if kind=='gap_update':gaps[target]['developments'].append(dict(link_id=e['id'],source_ids=e['source_ids'],description=e['description'],certainty=e['certainty']))
                    elif explicit and e['basis']!='unknown':gaps[target].update(status='resolved',resolved_at=e['id'],resolution_source_ids=e['source_ids'])
                    else:warnings.append(dict(link_id=e['id'],reason='Proposed resolution remains unverified; gap retained'))
            modes[item['id']]=dict(frame_id=frame,mode=mode)
        modes[item['id']]=dict(frame_id=frame,mode=mode)
    return dict(events=events,gaps=list(gaps.values()),source_frames=modes,unannotated_pages=unannotated,warnings=warnings,
        active_frame=dict(frame_id=frame,mode=mode),
        enclosing_frames=[dict(frame_id=f,mode=m,flashback_start_id=s) for f,m,s in stack],
        policy='Presentation order and reader knowledge are authoritative. Story-time relationships remain source-linked proposals.')

def continuity_memory(records,focus_ids=None,required_link_ids=None,limit=12,query_text=''):
    data=ledger(records);required=set(required_link_ids or []);focus=set(focus_ids or []);index={i['id']:i for i in flat_items(records)}
    gaps=[g for g in data['gaps'] if g['status']=='open' or g['id'] in required]
    def owners(g):return {entity for ref in g['source_ids'] for entity in index.get(ref,{}).get('actors',[])}
    stop={'the','and','was','were','with','that','this','from','into','what','when','then','they','their','there','them','him','his','her','she','had','have','has','did','does','after','before','scene','happened','source','only'}
    def tokens(text):return {t for t in re.findall(r'[a-z]{3,}',text.lower()) if t not in stop}
    query=tokens(query_text)
    documents={g['id']:tokens(g['description']+' '+' '.join(index.get(ref,{}).get('text','')+' '+index.get(ref,{}).get('meaning','') for ref in g['source_ids'])) for g in gaps}
    frequencies=Counter(word for doc in documents.values() for word in doc)
    count=len(gaps)  # list.sort temporarily empties its list while evaluating keys.
    def relevance(g):return sum(math.log(1+count/(1+frequencies[word])) for word in query&documents[g['id']])
    gaps.sort(key=lambda g:(g['id'] in required,relevance(g),bool(owners(g)&focus),g['reveal_rank']),reverse=True)
    referenced=[e for e in data['events'] if e['id'] in required and e['kind']!='gap_open']
    return dict(open_or_referenced_gaps=gaps[:limit],recent_transitions=data['events'][-8:],
        referenced_transitions=referenced[:limit],
        omitted_gap_count=max(0,len(gaps)-limit),required_overflow=sum(g['id'] in required for g in gaps)>limit or len(referenced)>limit or len(data['enclosing_frames'])>8,
        active_frame=data['active_frame'],enclosing_frames=data['enclosing_frames'][-8:],
        unannotated_page_count=len(data['unannotated_pages']),source_frames=data['source_frames'],
        warnings=data['warnings'][-12:],total_warning_count=len(data['warnings']),policy=data['policy'])

def chapter_handoff(prior,current):
    previous=flat_items(prior);opening=flat_items(current);required={i for r in current for e in r.get('narrative_links',[]) for i in e['related_link_ids']}
    focus={e['id'] for r in current for e in r['entities']}
    query=' '.join(i['text']+' '+i['meaning'] for i in opening)
    memory=continuity_memory(prior,focus,required,query_text=query)
    # Frame index is used separately for observation annotation, not copied wholesale
    # into bounded writer context.
    memory.pop('source_frames')
    first=next((i['id'] for i in opening if i['kind']!='metadata'),None)
    links=[e for r in current for e in r.get('narrative_links',[])]
    boundary=next((e for e in links if first in e['source_ids'] and e['kind'] in {'scene_start','continuous','time_skip','flashback_start','flashback_return','parallel_cut','uncertain'}),None)
    return dict(previous_ending=[i for i in previous if i['kind']!='metadata'][-6:],
        current_opening=[i for i in opening if i['kind']!='metadata'][:6],
        prior_narrative_memory=memory,current_links=links,
        opening_relation={k:boundary[k] for k in ['id','kind','certainty','source_ids']} if boundary else dict(kind='unknown_without_source_annotation'),
        policy='Bridge known scenes naturally. Preserve unanswered gaps and reveal later explanations where the source does. Never infer a time skip from a chapter boundary.')

def framed_observation(entry,frames):
    result=copy.deepcopy(entry);values=[frames[i] for i in entry['source_ids'] if i in frames]
    unique={(v['frame_id'],v['mode']) for v in values}
    result['narrative_frames']=[dict(frame_id=f,mode=m) for f,m in sorted(unique)]
    result['current_frame_update_allowed']=bool(values) and all(v['mode']=='current_frame' for v in values)
    return result

if __name__=='__main__':
    import argparse,json
    from pathlib import Path
    from series_inventory import chapter_label,chapter_sort,chapter_from_page
    parser=argparse.ArgumentParser(description='Offline chapter handoff and narrative-frame report; no model calls')
    parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--chapter',type=chapter_label,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=json.loads(args.evidence.read_text(encoding='utf-8'));records=source['records']
    prior=[r for r in records if chapter_sort(chapter_from_page(r['pages'][0]['page_id']))<chapter_sort(args.chapter)]
    current=[r for r in records if chapter_from_page(r['pages'][0]['page_id'])==args.chapter]
    if not current:raise ValueError('No evidence for requested chapter')
    report=dict(chapter=args.chapter,handoff=chapter_handoff(prior,current),known_at_chapter_end=ledger(prior+current),
        publication_approved=False,source_reviewed=False,network_used=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(chapter=args.chapter,output=str(args.output),network_used=False,unannotated_pages=len(report['known_at_chapter_end']['unannotated_pages']))))
