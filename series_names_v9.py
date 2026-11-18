"""Audited translation aliases; preserve raw model prose and expose delivery changes."""
import copy,hashlib,re

ALIASES=[
 {'pattern':r'\bHage\s+Poccho\b','replacement':'Hugg Pocho','evidence':['ch1-p008','ch3.1-p004'],'basis':'Same bald warrior, level 10, HP 96, MP 16, force 46, agility 12, resistance 51; printed translation changed.'},
 {'pattern':r'\bHage\s+Pocho\b','replacement':'Hugg Pocho','evidence':['ch1-p008','ch3.1-p004'],'basis':'Same source-linked warrior alias.'},
 {'pattern':r'\bHugg\s+Poccho\b','replacement':'Hugg Pocho','evidence':['ch1-p008','ch3.1-p004'],'basis':'Surname translation variant.'},
 {'pattern':r'\bHage\b','replacement':'Hugg','evidence':['ch1-p008','ch3.1-p004'],'basis':'First-name translation variant of the same warrior.'},
]
def delivery_draft(draft):
    result=copy.deepcopy(draft);changes=[]
    for beat in result['beats']:
        for rule in ALIASES:
            text,n=re.subn(rule['pattern'],rule['replacement'],beat['text'])
            if n:changes.append(dict(beat_id=beat['id'],pattern=rule['pattern'],replacement=rule['replacement'],count=n,evidence=rule['evidence']));beat['text']=text
    for segment,beat in zip(result['script']['segments'],result['beats']):segment['text']=beat['text']
    text='\n\n'.join(b['text'] for b in result['beats']);result['original_text_sha256']=draft['text_sha256'];result['text_sha256']=hashlib.sha256(text.encode()).hexdigest();result['words']=len(text.split());result['automatic_name_normalizations']=changes
    return result
