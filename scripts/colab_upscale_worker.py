"""Executed inside a Colab GPU VM by the official Colab CLI."""
import json,os,subprocess,sys,zipfile,time
from pathlib import Path

def main():
 root=Path('/content/manga-worker');root.mkdir(exist_ok=True)
 with zipfile.ZipFile('/content/manga-code.zip') as z:z.extractall(root)
 sys.path.insert(0,str(root));connection=json.loads(Path('/content/manga-private.json').read_text());os.environ['MANGA_RCLONE_CONFIG']=connection['rclone'];os.environ['MANGA_STORE_REMOTE']=connection['remote']
 # Google Colab provides torch and a GPU runtime. Upstream auto-splits large
 # pages on OOM. Never request a paid upgrade or delete original inputs.
 subprocess.run([sys.executable,'-m','pip','install','-q','requests','Pillow','numpy','typer','rich','opencv-python-headless','tzdata'],check=True)
 subprocess.run(['apt-get','update','-qq'],check=True);subprocess.run(['apt-get','install','-y','-qq','rclone'],check=True)
 from manga_bot.storage import Snapshot,RcloneStore
 from manga_bot.core import read,save
 from manga_bot.upscale import run
 state=root/'state';store=RcloneStore(connection['remote']);snapshot=Snapshot(state,store,lazy_media=True)
 try:
  if not snapshot.restore():raise RuntimeError('No persisted manga task found')
  library=read(state/'library.json');item=next(m for m in library['manga'] if m['id']==connection['manga_id']);target=Path(item['directory'])/'upscaled';item['state']='upscaling';save(state/'library.json',library);snapshot.checkpoint();run(item['source'],target,state,checkpoint=snapshot.checkpoint)
  item.update(upscale_complete=True,upscaled_source=str(target),state='ready_for_story',reason='Verified 4x upscale complete');save(state/'library.json',library);snapshot.checkpoint();print('Upscale completion checkpoint published',flush=True)
 finally:store.close()

if __name__=='__main__':main()
