"""Fetch signed Ubuntu package dependencies concurrently, then let apt verify/install."""
import os,shlex,shutil,subprocess,tempfile
from pathlib import Path
from urllib.parse import urlparse

OPTIONS=['-o','Acquire::Retries=2','-o','Acquire::http::Timeout=30','-o','Acquire::https::Timeout=30']

def download_list(output):
 lines=[]
 for line in output.splitlines():
  if not line.startswith("'"):continue
  fields=shlex.split(line)
  if len(fields)<3:raise ValueError('Incomplete apt download entry')
  url,name,size=fields[:3]
  if urlparse(url).scheme not in ('http','https') or Path(name).name!=name or '/' in name or '\\' in name or name in ('.','..') or not size.isdigit():raise ValueError('Invalid apt download entry')
  parsed=urlparse(url)
  if parsed.hostname=='archive.ubuntu.com' or (parsed.hostname or '').endswith('.archive.ubuntu.com'):
   url=parsed._replace(scheme='https',netloc='archive.ubuntu.com').geturl()
  lines.extend([url,' out='+name,' dir=/var/cache/apt/archives'])
 return '\n'.join(lines)+'\n' if lines else ''

def install(packages):
 if not packages or any(p not in ('ffmpeg','rclone') for p in packages):raise ValueError('Only the worker media packages are supported')
 apt=['sudo','apt-get',*OPTIONS];env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'}
 subprocess.run([*apt,'update','-qq'],check=True,env=env)
 if shutil.which('aria2c'):
  result=subprocess.run([*apt,'--print-uris','--yes','--no-install-recommends','install',*packages],capture_output=True,text=True,check=True,env=env)
  listing=download_list(result.stdout)
  if listing:
   with tempfile.TemporaryDirectory(prefix='manga-media-install-') as directory:
    manifest=Path(directory)/'packages.txt';manifest.write_text(listing,encoding='utf-8')
    try:
     subprocess.run(['sudo','aria2c','--input-file='+str(manifest),'--max-concurrent-downloads=8','--max-connection-per-server=4','--split=4','--file-allocation=none','--auto-file-renaming=false','--allow-overwrite=true','--max-tries=3','--retry-wait=2','--connect-timeout=20','--timeout=30','--summary-interval=30','--console-log-level=warn'],check=True,timeout=480)
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
     # Apt can reuse complete files and recover a partial/missing download.
     pass
 # Apt checks package hashes against its signed index before installation.
 subprocess.run([*apt,'install','--yes','--no-install-recommends',*packages],check=True,env=env)

if __name__=='__main__':
 import sys
 install(sys.argv[1:])
