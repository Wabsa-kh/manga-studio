"""Select bounded, time-scoped continuity; keep the complete evidence archive intact."""
def retrieve_cast(records,focus_ids=None,limit=48):
    entities={e['id']:e for r in records for e in r['entities']}
    focus=list(dict.fromkeys(focus_ids or []))
    required=[i for i in focus if i in entities]
    recent=[]
    for r in records[-2:]:
        for page in r['pages']:
            for item in page['items']:
                recent.extend(item.get('actors',[]))
                if item.get('speaker'):recent.append(item['speaker'])
    priority=list(dict.fromkeys(required+list(reversed(recent))+list(reversed(entities))))
    selected=[entities[i] for i in priority if i in entities][:limit]
    return selected,dict(total_entities=len(entities),selected_entities=len(selected),
        omitted_from_prompt=max(0,len(entities)-len(selected)),required_overflow=len(required)>limit,
        method='Current source cast, then recent speakers/actors; full archive is retained. Unseen identity remains unresolved.')

def related_observations(records,kind,entity_ids,limit):
    relevant=[]
    for r in records:
        for entry in r[kind]:
            owners={entry[k] for k in ['entity_id','subject','object'] if entry.get(k)}
            if not owners or owners&entity_ids:relevant.append(entry)
    return relevant[-limit:]
