"""Validate owner-editable settings and queue without API requests or private secrets."""
import json,sys,tempfile,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from manga_bot.catalog import sync
from manga_bot.routing import Router

def check(path='config/settings.json'):
 cfg=json.loads(Path(path).read_text(encoding='utf-8-sig'))
 low,high=cfg['part_minutes']
 if any(type(n) not in (int,float) for n in (low,high)) or not 1<=low<=high<=240:raise ValueError('Global part_minutes must be an ordered range between 1 and 240')
 if not 1<=cfg.get('max_run_minutes',240)<=300:raise ValueError('max_run_minutes must fit inside the cloud job timeout')
 if cfg['youtube'].get('privacy') not in ('private','unlisted','public'):raise ValueError('Invalid upload privacy')
 with tempfile.TemporaryDirectory(prefix='manga-config-check-') as folder:
  # This command does not need credentials; the production workflow invokes it
  # before its secret-bearing step.
  old=os.environ.pop('MODEL_CREDENTIALS_JSON',None)
  try:api=Router(Path(folder)/'job',options=cfg.get('providers'),quota_limits=cfg.get('quota_limits'))
  finally:
   if old is not None:os.environ['MODEL_CREDENTIALS_JSON']=old
  for stage in ('reader','writer','tts'):
   for route in api.plan(stage,[]):
    if route.get('provider')=='openrouter' and not (route['model'].endswith(':free') or route['model']=='openrouter/free'):raise ValueError('Only free OpenRouter routes are allowed')
    for field in ('rpm','daily_requests','max_tokens','timeout_seconds'):
     if field in route and (type(route[field]) is not int or route[field]<=0):raise ValueError('Route '+field+' must be a positive integer')
  sync(Path(folder)/'state',cfg)
 print('Settings and manga list validation passed; no API requests made.')
if __name__=='__main__':check(sys.argv[1] if len(sys.argv)>1 else 'config/settings.json')
