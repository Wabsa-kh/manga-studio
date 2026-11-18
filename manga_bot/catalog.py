"""Owner-managed queue settings, independent of durable production receipts."""
from pathlib import Path
from .core import read,save,Attention
from .ingest import manga_url

def sync(root,cfg):
 path=cfg.get('manga_list_file')
 if not path:return
 data=read(Path(path))
 if not isinstance(data,dict) or not isinstance(data.get('manga'),list):raise Attention('Manga list must contain a manga array')
 rows=[];seen=set()
 # Validate the whole list before changing durable state.
 for position,entry in enumerate(data['manga']):
  if not isinstance(entry,dict):raise Attention('Each manga entry must be an object')
  try:url=manga_url(entry['url'])
  except (ValueError,KeyError,AttributeError):raise Attention('Each manga needs a valid WeebCentral series URL')
  if url in seen:raise Attention('The manga list contains the same series twice')
  seen.add(url);options={'url':url,'list_order':position,'enabled':entry.get('enabled',True),'priority':entry.get('priority',100)}
  if type(options['enabled']) is not bool or type(options['priority']) is not int:raise Attention('Use a boolean enabled value and an integer priority')
  if 'title' in entry:
   if not isinstance(entry['title'],str) or not entry['title'].strip():raise Attention('Manga title must be nonempty text')
   options['title']=entry['title'].strip()
  if 'part_minutes' in entry:
   bounds=entry['part_minutes']
   if not isinstance(bounds,list) or len(bounds)!=2 or any(type(n) not in (int,float) for n in bounds) or not 1<=bounds[0]<=bounds[1]<=240:raise Attention('part_minutes must be [minimum, maximum] between 1 and 240')
   options['part_minutes']=bounds
  rows.append(options)
 from .manage import add
 root=Path(root)
 for row in rows:add(root,row['url'],row.get('title'))
 library=read(root/'library.json',{'version':1,'manga':[]});lookup={row['url']:row for row in rows}
 for item in library['manga']:
  row=lookup.get(item['url'])
  if row:
   item.update(row,managed_by_list=True)
   if 'part_minutes' not in row:item.pop('part_minutes',None)
  elif item.get('managed_by_list'):item['enabled']=False
 save(root/'library.json',library)

def ordered(library):
 return sorted(library['manga'],key=lambda item:(item.get('priority',100),item.get('list_order',100000)))
