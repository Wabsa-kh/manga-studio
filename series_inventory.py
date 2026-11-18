"""Stable chapter/part labels; never turn 3.1 and 3.10 into floating-point IDs."""
import re

def chapter_label(value):
    if isinstance(value,float):raise ValueError('Use exact chapter strings, not floating-point chapter labels')
    text=str(value).strip()
    if text.lower()=='all':return 'all'
    if not re.fullmatch(r'\d+(?:\.\d+)*',text):raise ValueError('Invalid chapter label: '+text)
    parts=[str(int(p)) for p in text.split('.')]
    return int(parts[0]) if len(parts)==1 else '.'.join(parts)

def chapter_sort(value):
    return tuple(int(p) for p in str(chapter_label(value)).split('.'))

def chapter_from_page(page_id):
    match=re.fullmatch(r'ch(\d+(?:\.\d+)*)-p.+',page_id)
    if not match:raise ValueError('Invalid source page ID: '+page_id)
    return chapter_label(match[1])

def natural_key(value):
    return tuple((0,int(p)) if p.isdigit() else (1,p.lower()) for p in re.split(r'(\d+)',str(value)))

def chapter_folders(source):
    folders={}
    for path in source.iterdir():
        match=re.fullmatch(r'Chapter\s+(\d+(?:\.\d+)*)',path.name,re.I)
        if path.is_dir() and match:
            label=chapter_label(match[1])
            if label in folders:raise ValueError('Ambiguous duplicate chapter label: '+str(label))
            folders[label]=path
    return dict(sorted(folders.items(),key=lambda p:chapter_sort(p[0])))
