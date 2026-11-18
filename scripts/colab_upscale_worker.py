"""Download in Colab CPU or upscale in Colab GPU via the official CLI."""
import json,os,subprocess,sys,zipfile,time,logging
from pathlib import Path

def main():
 root=Path('/content/manga-worker');root.mkdir(exist_ok=True)
 with zipfile.ZipFile('/content/manga-code.zip') as z:z.extractall(root)
 sys.path.insert(0,str(root));connection=json.loads(Path('/content/manga-private.json').read_text());os.environ['MANGA_RCLONE_CONFIG']=connection['rclone'];os.environ['MANGA_STORE_REMOTE']=connection['remote']
 # Google Colab provides torch and a GPU runtime. Upstream auto-splits large
 # pages on OOM. Never request a paid upgrade or delete original inputs.
 stage=connection.get('stage','upscale')
 packages=['requests','Pillow','numpy','tzdata']+(['beautifulsoup4','tqdm','fpdf2','ebooklib'] if stage=='download' else ['typer','rich','opencv-python-headless'])
 subprocess.run([sys.executable,'-m','pip','install','-q',*packages],check=True)
 subprocess.run(['apt-get','update','-qq'],check=True);subprocess.run(['apt-get','install','-y','-qq','rclone'],check=True)
 from manga_bot.storage import Snapshot,RcloneStore
 from manga_bot.colab_tasks import process
 state=root/'state';store=RcloneStore(connection['remote']);snapshot=Snapshot(state,store,lazy_media=True)
 try:
  if not snapshot.restore():raise RuntimeError('No persisted manga task found')
  logs=state/'diagnostics';logs.mkdir(parents=True,exist_ok=True)
  logging.basicConfig(filename=str(logs/('colab-'+connection['manga_id']+'-'+stage+'.log')),level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',force=True)
  cfg=connection.get('settings',{});cfg.setdefault('download',{});cfg.setdefault('upscale',{})
  cfg.setdefault('_deadline',time.time()+cfg.get('max_run_minutes',240)*60)
  process(snapshot,connection['manga_id'],stage,cfg);print('Colab task checkpoint published',flush=True)
 finally:store.close()

if __name__=='__main__':main()
