"""Export code and run manifests through an explicit credential-free allowlist."""
import argparse,ast,re,zipfile
from pathlib import Path
from .core import save,sha,read,utc

def export(repo,job,target):
 repo=Path(repo);job=Path(job);target=Path(target);target.mkdir(parents=True,exist_ok=True)
 # Copy only local Python dependencies, not experimental result folders,
 # credential files, environment files, private DPAPI files or site packages.
 files=set(repo.joinpath('manga_bot').glob('*.py'));files.add(repo/'test_manga_bot.py');todo=list(files)
 while todo:
  path=todo.pop();tree=ast.parse(path.read_text(encoding='utf-8-sig'))
  for node in ast.walk(tree):
   modules=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) and node.level==0 else []
   for module in modules:
    p=repo/(module.split('.')[0]+'.py')
    if p.exists() and p not in files:files.add(p);todo.append(p)
 files.update([repo/'manga_bot/requirements.txt',repo/'manga_bot/Dockerfile',repo/'manga_bot/README.md',repo/'narration_style.txt',repo/'reference/style-calibration.json'])
 pattern=re.compile(r'(?:AIza[A-Za-z0-9_-]{25,}|(?:nvapi-|sk-)[A-Za-z0-9_-]{25,})')
 for p in files:
  if pattern.search(p.read_text(encoding='utf-8-sig')):raise RuntimeError('Potential embedded credential in '+p.name+'; export stopped')
 manifest=dict(created_utc=utc(),source_directory=read(job/'config.json')['source'],source_pages=len(read(job/'inventory.json')['pages']),original_images_included=False,source_note='Original images stay in the user-provided source directory. Inventory records exact sizes, IDs and SHA256 hashes.',files=[dict(path=str(p.relative_to(repo)),sha256=sha(p)) for p in sorted(files)])
 save(target/'package-manifest.json',manifest);archive=target/'manga-bot-v10.zip'
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(files):z.write(p,p.relative_to(repo).as_posix())
  for name in ['config.json','inventory.json','code-version.json','status.json','REPORT.md','TRIAL_NOTES.md']:
   if (job/name).exists():z.write(job/name,'run-snapshot/'+name)
  z.write(target/'package-manifest.json','package-manifest.json')
 return archive

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--target',required=True);a=p.parse_args();print(export(Path(__file__).resolve().parents[1],a.job,a.target))
