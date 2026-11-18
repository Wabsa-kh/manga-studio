"""Scan tracked text only; report filenames, never secret values."""
import re,subprocess
from pathlib import Path
pattern=re.compile(r'(?:AIza[A-Za-z0-9_-]{25,}|(?:nvapi-|sk-)[A-Za-z0-9_-]{25,}|gh[pousr]_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)')
bad=[]
for name in subprocess.check_output(['git','ls-files','-z']).decode().split('\0'):
 if not name:continue
 path=Path(name)
 if path.is_file() and path.suffix in {'.py','.md','.json','.yml','.yaml','.txt','.toml'}:
  if pattern.search(path.read_text(encoding='utf-8-sig')):bad.append(name)
if bad:raise SystemExit('Potential secrets found in: '+', '.join(bad))
print('Tracked source secret scan passed')
