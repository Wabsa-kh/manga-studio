"""Launch a pinned headless GPU task; Drive remains the durable handoff."""
import os,json,subprocess,tempfile,zipfile
from pathlib import Path
from .core import read,save,Attention

def launch(manga_id,settings):
 if not os.environ.get('COLAB_ADC_JSON'):raise Attention('Colab authentication is not connected: configure COLAB_ADC_JSON using user ADC with the documented Colab scopes')
 if not os.environ.get('MANGA_RCLONE_CONFIG'):raise Attention('Colab needs the Drive rclone configuration secret')
 repo=Path(__file__).resolve().parents[1];session='manga-'+manga_id;created=False
 with tempfile.TemporaryDirectory(prefix='manga-colab-private-') as d:
  temp=Path(d);adc=temp/'adc.json';adc.write_text(os.environ['COLAB_ADC_JSON'],encoding='utf-8');adc.chmod(0o600);env={**os.environ,'GOOGLE_APPLICATION_CREDENTIALS':str(adc)}
  def call(args,timeout=300):
   result=subprocess.run(['colab','--auth','adc',*args],env=env,capture_output=True,timeout=timeout)
   if result.returncode:raise Attention('Colab CLI operation failed; inspect authentication/runtime availability locally. Private command output was not logged.')
  archive=temp/'code.zip'
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
   for path in (repo/'manga_bot').glob('*.py'):z.write(path,'manga_bot/'+path.name)
   # Lightweight upscale dependencies, not the full narration/render stack.
   for name in ['series_inventory.py']:z.write(repo/name,name)
  private=temp/'connection.json';save(private,dict(remote=os.environ.get('MANGA_STORE_REMOTE'),rclone=os.environ['MANGA_RCLONE_CONFIG'],manga_id=manga_id))
  script=repo/'scripts/colab_upscale_worker.py'
  try:
   created=True;call(['new','-s',session,'--gpu',settings['upscale'].get('gpu','T4')],180)
   call(['upload','-s',session,str(archive),'/content/manga-code.zip']);call(['upload','-s',session,str(private),'/content/manga-private.json']);call(['exec','-s',session,'-f',str(script),'--timeout','0'],timeout=max(300,int((settings.get('_deadline',0)-__import__('time').time()) or 7200)))
  finally:
   if created:
    try:call(['stop','-s',session],120)
    except Exception:pass
