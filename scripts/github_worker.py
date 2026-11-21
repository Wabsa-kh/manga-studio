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
cfg['_read_only']=os.environ.get('MANGA_READ_ONLY')=='1'
ready=(checks['storage_ready'] and checks['gemini_key_configured']) if cfg['_read_only'] else (checks['production_ready'] or checks['publishing_ready'])
if os.environ.get('DRY_RUN','').lower()=='true' or not ready:
 checks['state']='waiting_for_connections';output();print('Connection check completed; no production calls made.')
else:
 cfg['_publish_only']=not checks['production_ready']
 # Keep even unexpected upstream console output out of public runner logs.
 import tempfile
 with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as log:
  cfg['_console_log']=log
  try:
   with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):worker(cfg,os.environ.get('MANGA_URL') or None,os.environ.get('MANGA_RETRY_ID') or None)
   checks['state']='run_finished';output();print('Run finished. Detailed reports and receipts are in private Drive storage.')
  except Exception as exc:
   from manga_bot.storage import StorageFailure
   checks['state']='stopped'
   if isinstance(exc,StorageFailure):checks['failure_kind']=exc.code
   output();print('Worker stopped. '+(str(exc) if isinstance(exc,StorageFailure) else 'Check private saved job receipts and connections.'));sys.exit(1)
