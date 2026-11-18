"""Only connection booleans go into public Actions output."""
import contextlib,json,os,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from manga_bot.manage import settings,doctor,worker

cfg=settings('config/settings.json');checks=doctor(cfg);summary=os.environ.get('GITHUB_STEP_SUMMARY')
def output():
 Path('worker-report.json').write_text(json.dumps(checks,indent=2))
 if summary:
  with open(summary,'a',encoding='utf-8') as f:f.write('## Worker connection check\n\n'+''.join(f'- {k}: {v}\n' for k,v in checks.items()))
if os.environ.get('DRY_RUN','').lower()=='true' or not (checks['production_ready'] or checks['publishing_ready']):
 checks['state']='waiting_for_connections';output();print('Connection check completed; no production calls made.')
else:
 cfg['_publish_only']=not checks['production_ready']
 # Keep even unexpected upstream console output out of public runner logs.
 import tempfile
 with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as log:
  try:
   with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):worker(cfg,os.environ.get('MANGA_URL') or None,os.environ.get('MANGA_RETRY_ID') or None)
   checks['state']='run_finished';output();print('Run finished. Detailed reports and receipts are in private Drive storage.')
  except Exception:
   checks['state']='stopped';output();print('Worker stopped. Check private saved job receipts and connections.');sys.exit(1)
