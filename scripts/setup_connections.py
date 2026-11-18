"""Owner-only Google consent and stdin-based GitHub secret installation."""
import argparse,json,os,subprocess,sys,configparser
from pathlib import Path
REPO='Wabsa-kh/manga-studio'
FILES={'GEMINI_API_KEY':'gemini-key.txt','MANGA_RCLONE_CONFIG':'rclone.conf','COLAB_ADC_JSON':'colab-adc.json','YOUTUBE_TOKEN_JSON':'youtube-token.json','YOUTUBE_CHANNEL_ID':'youtube-channel-id.txt'}

def install(folder):
 for name,filename in FILES.items():
  path=folder/filename
  if not path.exists():print(name+': missing');continue
  value=path.read_text(encoding='utf-8-sig').strip()
  if not value or 'REPLACE_ME' in value:print(name+': placeholder; skipped');continue
  if filename.endswith('.json'):
   data=json.loads(value)
   if not data.get('refresh_token') or data.get('type')!='authorized_user':raise ValueError(name+': authorized user refresh credentials required')
  if name=='MANGA_RCLONE_CONFIG':
   parser=configparser.ConfigParser(interpolation=None);parser.read_string(value)
   if not parser.has_section('gdrive') or parser.get('gdrive','type',fallback='')!='drive' or not parser.get('gdrive','token',fallback=''):raise ValueError('rclone.conf needs an authorized gdrive remote')
  subprocess.run(['gh','secret','set',name,'--repo',REPO],input=value.encode(),check=True,capture_output=True)
  print(name+': installed')
 subprocess.run(['gh','variable','set','MANGA_STORE_REMOTE','--repo',REPO,'--body','gdrive:manga-studio'],check=True,capture_output=True)

def youtube(folder):
 from google_auth_oauthlib.flow import InstalledAppFlow
 from google.auth.transport.requests import AuthorizedSession
 path=folder/'google-client.json'
 if not path.exists():raise ValueError('Download a Desktop app OAuth client as google-client.json into your private setup folder first')
 scopes=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly']
 credentials=InstalledAppFlow.from_client_secrets_file(str(path),scopes=scopes).run_local_server(port=0,access_type='offline',prompt='consent')
 if not credentials.refresh_token:raise ValueError('Google did not return an offline refresh credential')
 with AuthorizedSession(credentials) as api:
  result=api.get('https://www.googleapis.com/youtube/v3/channels',params={'part':'id,snippet','mine':'true'},timeout=60);result.raise_for_status();items=result.json().get('items',[])
 if len(items)!=1:raise ValueError('Select the Google/Brand account with exactly the intended YouTube channel and authorize again')
 print('Connected channel: '+items[0]['snippet']['title'])
 if input('Type YES to use this channel for private uploads: ').strip()!='YES':raise SystemExit('No credentials saved')
 data=json.loads(credentials.to_json());data['type']='authorized_user'
 (folder/'youtube-token.json').write_text(json.dumps(data,indent=2));(folder/'youtube-token.json').chmod(0o600)
 (folder/'youtube-channel-id.txt').write_text(items[0]['id']);print('Private YouTube credential files saved. Run install next.')

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['youtube','install','status']);p.add_argument('--folder',required=True);a=p.parse_args();folder=Path(a.folder).resolve();folder.mkdir(parents=True,exist_ok=True)
 if a.command=='youtube':youtube(folder)
 elif a.command=='install':install(folder)
 else:
  for name,filename in FILES.items():print(name+(': file present' if (folder/filename).exists() else ': missing'))
if __name__=='__main__':main()
