"""Launch CPU download or GPU upscale tasks; Drive is the durable handoff."""
import os,json,subprocess,tempfile,time,zipfile
from pathlib import Path
from .core import read,save,Attention,Pending

def launch(manga_id,settings):
 if not os.environ.get('COLAB_ADC_JSON'):raise Attention('Colab authentication is not connected: configure COLAB_ADC_JSON using user ADC with the documented Colab scopes')
 if not os.environ.get('MANGA_RCLONE_CONFIG'):raise Attention('Colab needs the Drive rclone configuration secret')
 repo=Path(__file__).resolve().parents[1];stage=settings.get('_colab_stage','upscale')
 if stage not in ('download','upscale'):raise Attention('Unknown Colab task stage')
 session='manga-'+stage+'-'+manga_id;created=False
 with tempfile.TemporaryDirectory(prefix='manga-colab-private-') as d:
  temp=Path(d);adc=temp/'adc.json';adc.write_text(os.environ['COLAB_ADC_JSON'],encoding='utf-8');adc.chmod(0o600);env={**os.environ,'GOOGLE_APPLICATION_CREDENTIALS':str(adc)}
  def call(args,timeout=300):
   try:result=subprocess.run(['colab','--auth','adc',*args],env=env,capture_output=True,timeout=timeout)
   except subprocess.TimeoutExpired:
    if settings.get('state_root'):save(Path(settings['state_root'])/'diagnostics'/('colab-'+manga_id+'-'+args[0]+'.json'),dict(operation=args[0],stage=stage,state='timeout'))
    raise Pending('Colab '+stage+' timed out; retry from the saved checkpoint',time.time()+900) from None
   if result.returncode:
    output=(result.stdout+b'\n'+result.stderr).decode('utf-8',errors='replace')[-12000:]
    if settings.get('state_root'):
     save(Path(settings['state_root'])/'diagnostics'/('colab-'+manga_id+'-'+args[0]+'.json'),dict(operation=args[0],stage=stage,exit_code=result.returncode,private_output=output))
    temporary=('429','503','resource_exhausted','too many requests','temporarily unavailable','connection reset','connection was lost','no available gpu','temporary usage or capacity limit','timed out')
    if any(marker in output.lower() for marker in temporary):
     raise Pending('Colab '+stage+' temporarily unavailable; retry from the saved checkpoint',time.time()+900)
    raise Attention('Colab '+stage+' operation failed; inspect the private Drive diagnostics for runtime/authentication details')
  archive=temp/'code.zip'
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
   for path in (repo/'manga_bot').glob('*.py'):z.write(path,'manga_bot/'+path.name)
   # Lightweight upscale dependencies, not the full narration/render stack.
   for name in ['series_inventory.py']:z.write(repo/name,name)
  task_settings={k:settings[k] for k in ('download','upscale','max_run_minutes','_deadline') if k in settings}
  private=temp/'connection.json';save(private,dict(remote=os.environ.get('MANGA_STORE_REMOTE'),rclone=os.environ['MANGA_RCLONE_CONFIG'],manga_id=manga_id,stage=stage,settings=task_settings))
  script=repo/'scripts/colab_upscale_worker.py'
  try:
   created=True;call(['new','-s',session,*(['--gpu',settings['upscale'].get('gpu','T4')] if stage=='upscale' else [])],180)
   call(['upload','-s',session,str(archive),'/content/manga-code.zip']);call(['upload','-s',session,str(private),'/content/manga-private.json']);call(['exec','-s',session,'-f',str(script),'--timeout','0'],timeout=max(300,int((settings.get('_deadline',0)-__import__('time').time()) or 7200)))
  finally:
   if created:
    try:call(['stop','-s',session],120)
    except Exception:pass
