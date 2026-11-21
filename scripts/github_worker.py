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
cfg['_phase']=os.environ.get('MANGA_PHASE','all')
if cfg['_phase'] not in ('all','download','prepare'):raise ValueError('Unknown worker phase')
if cfg['_read_only'] or cfg['_phase']=='prepare':
 ready=checks['storage_ready'] and checks['gemini_key_configured']
elif cfg['_phase']=='download':
 ready=checks['storage_ready'] and checks['colab_cli'] and checks['colab_credentials_configured']
else:
 ready=checks['production_ready'] or checks['publishing_ready']
if os.environ.get('COLAB_PROFILE','primary')!='primary' and not checks['colab_credentials_configured'] and cfg['_phase']!='prepare':
 ready=False
 checks['requested_colab_profile_connected']=False
checks['phase']='read' if cfg['_read_only'] else cfg['_phase']
if os.environ.get('DRY_RUN','').lower()=='true' or not ready:
 checks['state']='waiting_for_connections';output();print('Connection check completed; no production calls made.')
else:
 cfg['_publish_only']=not checks['production_ready']
 # Keep even unexpected upstream console output out of public runner logs.
 import tempfile
 with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as log:
  cfg['_console_log']=log
  cfg['_public_progress']=lambda message: print(message,file=sys.__stdout__,flush=True)
  try:
   with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):worker(cfg,os.environ.get('MANGA_URL') or None,os.environ.get('MANGA_RETRY_ID') or None)
   checks['state']='run_finished';output();print('Run finished. Detailed reports and receipts are in private Drive storage.')
  except Exception as exc:
   from manga_bot.storage import StorageFailure
   checks['state']='stopped'
   if isinstance(exc,StorageFailure):checks['failure_kind']=exc.code
   output();print('Worker stopped. '+(str(exc) if isinstance(exc,StorageFailure) else 'Check private saved job receipts and connections.'));sys.exit(1)
