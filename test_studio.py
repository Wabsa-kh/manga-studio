import unittest,tempfile,time,sqlite3,wave,os
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from manga_bot.core import save,read,Attention,Pending,digest
from manga_bot.storage import LocalStore,Snapshot,key
from manga_bot.ingest import manga_url,verified_images
from manga_bot.manage import add,doctor
from manga_bot.providers import Google,MODELS

class StudioTests(unittest.TestCase):
 def test_manager_uses_colab_download_and_can_continue_without_gpu_upscale(self):
  from manga_bot.manage import worker
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'github';root.mkdir();store=LocalStore(base/'drive')
   ident=add(root,'https://weebcentral.com/series/ABC','CPU manga');Snapshot(root,store).checkpoint()
   def launched(manga_id,cfg):
    self.assertEqual(cfg['_colab_stage'],'download')
    remote=Snapshot(base/'colab',store);remote.restore();library=read(remote.root/'library.json');item=library['manga'][0]
    source=Path(item['directory'])/'source/Chapter 1';source.mkdir(parents=True);Image.new('RGB',(20,30)).save(source/'001.png')
    item.update(download_complete=True,source=str(source.parent),state='ready_for_story');save(remote.root/'library.json',library);remote.checkpoint()
   cfg={'state_root':str(root),'storage':{'backend':'local'},'download':{'backend':'colab'},'upscale':{'enabled':False},'youtube':{'enabled':False},'max_run_minutes':1}
   with patch.dict(os.environ,{'MANGA_LOCAL_ARCHIVE':str(base/'drive')}),patch('manga_bot.colab_bridge.launch',side_effect=launched),patch('manga_bot.manage.download',side_effect=AssertionError('GitHub must not download')),patch('manga_bot.worker.initialize',return_value=(root/'manga'/ident/'job',{})),patch('manga_bot.worker.turn',return_value=False),patch('manga_bot.routing.Router'):
    worker(cfg)
   result=read(root/'library.json')['manga'][0];self.assertEqual(result['state'],'complete');self.assertTrue(result['download_complete'])
 def test_colab_download_checkpoints_pages_before_upscaling(self):
  from manga_bot.colab_tasks import process
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'colab';root.mkdir();book=root/'manga/abc';book.mkdir(parents=True)
   save(root/'library.json',{'manga':[{'id':'abc','directory':str(book),'url':'https://weebcentral.com/series/ABC'}]})
   snap=Snapshot(root,LocalStore(base/'drive'))
   def downloaded(state,item,cfg,checkpoint):
    source=book/'source/Chapter 1';source.mkdir(parents=True);Image.new('RGB',(20,30)).save(source/'001.png')
    item.update(source=str(book/'source'),downloaded_chapters=1,expected_chapters=1);checkpoint();return True
   with patch('manga_bot.ingest.download',side_effect=downloaded),patch('manga_bot.upscale.run',side_effect=AssertionError('CPU downloads must not start GPU work')):
    result=process(snap,'abc','download',{'download':{},'upscale':{'enabled':True}})
   self.assertTrue(result['download_complete']);self.assertEqual(result['state'],'ready_for_upscale')
   fresh=base/'github';Snapshot(fresh,LocalStore(base/'drive')).restore()
   self.assertTrue((fresh/'manga/abc/source/Chapter 1/001.png').exists())
   self.assertTrue(read(fresh/'library.json')['manga'][0]['download_complete'])
 def test_colab_partial_download_resumes_without_claiming_complete(self):
  from manga_bot.colab_tasks import process
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'colab';root.mkdir();book=root/'manga/abc';book.mkdir(parents=True)
   save(root/'library.json',{'manga':[{'id':'abc','directory':str(book)}]});snap=Snapshot(root,LocalStore(Path(d)/'drive'))
   def partial(*args):save(book/'downloads/chapter1.json',{'complete':True});raise Pending('Source temporarily unavailable',time.time()+3600)
   with patch('manga_bot.ingest.download',side_effect=partial):result=process(snap,'abc','download',{'download':{}})
   self.assertEqual(result['state'],'waiting');self.assertFalse(result.get('download_complete',False))
   restored=Path(d)/'new';Snapshot(restored,LocalStore(Path(d)/'drive')).restore()
   self.assertTrue(read(restored/'manga/abc/downloads/chapter1.json')['complete'])
 def test_colab_gpu_uses_configured_color_model_without_downloading_again(self):
  from manga_bot.colab_tasks import process
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'colab';root.mkdir();book=root/'manga/abc';book.mkdir(parents=True)
   save(root/'library.json',{'manga':[{'id':'abc','directory':str(book),'download_complete':True,'source':str(book/'source')}]})
   snap=Snapshot(root,LocalStore(Path(d)/'drive'))
   with patch('manga_bot.ingest.download',side_effect=AssertionError('Do not repeat verified download')),patch('manga_bot.upscale.run') as upscale:
    result=process(snap,'abc','upscale',{'upscale':{'color_mode':'color'}})
   self.assertEqual(upscale.call_args.kwargs['mode'],'color');self.assertTrue(result['upscale_complete'])
 def test_colab_cpu_launch_never_requests_gpu_or_ships_model_keys(self):
  from manga_bot.colab_bridge import launch
  import subprocess,json
  captured=[]
  def run(command,**kwargs):
   captured.append(command)
   if 'upload' in command and command[-1]=='/content/manga-private.json':
    data=read(command[-2]);self.assertEqual(data['stage'],'download');self.assertNotIn('providers',data['settings']);self.assertNotIn('model-secret',json.dumps(data))
   return subprocess.CompletedProcess(command,0,b'',b'')
  with patch.dict(os.environ,{'COLAB_ADC_JSON':'{}','MANGA_RCLONE_CONFIG':'fixture-drive','MANGA_STORE_REMOTE':'gdrive:fixture','MODEL_CREDENTIALS_JSON':'model-secret'}),patch('manga_bot.colab_bridge.subprocess.run',side_effect=run):
   launch('abc',{'_colab_stage':'download','download':{'backend':'colab'},'upscale':{'gpu':'T4'},'providers':{'private':'model-secret'}})
  allocation=next(c for c in captured if 'new' in c);self.assertNotIn('--gpu',allocation)
  self.assertTrue(any('stop' in c for c in captured))
 def test_drive_quota_failure_is_actionable_without_exposing_private_output(self):
  from manga_bot.storage import RcloneStore,StorageFailure
  import subprocess
  store=RcloneStore.__new__(RcloneStore);store.config=None
  private=b'quota metric Queries; rateLimitExceeded; Bearer private-token-value; private-folder-id'
  with patch('manga_bot.storage.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'',private)):
   with self.assertRaises(StorageFailure) as caught:store.command(['mkdir','gdrive:private-folder'])
  self.assertEqual(caught.exception.code,'storage_rate_limited')
  self.assertNotIn('private-token-value',str(caught.exception));self.assertNotIn('private-folder-id',str(caught.exception))
 def test_drive_storage_full_is_not_confused_with_request_quota(self):
  from manga_bot.storage import storage_failure
  self.assertEqual(storage_failure(b'storageQuotaExceeded: storage quota has been exceeded').code,'storage_full')
  self.assertEqual(storage_failure(b'invalid_grant: token revoked').code,'storage_authorization')
  self.assertEqual(storage_failure(b'unknown upstream failure').code,'storage_operation_failed')
 def test_drive_timeout_has_a_safe_retry_diagnostic(self):
  from manga_bot.storage import RcloneStore,StorageFailure
  import subprocess
  store=RcloneStore.__new__(RcloneStore);store.config=None
  with patch('manga_bot.storage.subprocess.run',side_effect=subprocess.TimeoutExpired(['private-command'],600)):
   with self.assertRaises(StorageFailure) as caught:store.command(['mkdir','gdrive:private-folder'])
  self.assertEqual(caught.exception.code,'storage_timeout')
  self.assertNotIn('private-command',str(caught.exception))
 def test_link_validation_and_deduplication(self):
  with tempfile.TemporaryDirectory() as d:
   a=add(d,'https://weebcentral.com/series/ABC/My-Comic');b=add(d,'https://www.weebcentral.com/series/ABC/Other-Title');self.assertEqual(a,b);self.assertEqual(len(read(Path(d)/'library.json')['manga']),1)
  for url in ['http://weebcentral.com/series/ABC','https://evil.test/series/ABC','https://weebcentral.com@evil.test/series/ABC','https://weebcentral.com/../../abc']:
   with self.assertRaises(ValueError):manga_url(url)
 def test_complete_checkpoint_restores_media_db_and_relocated_paths(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'runner1';root.mkdir();(root/'clip.mp4').write_bytes(b'completed fixture media');save(root/'job.json',{'audio':str(root/'audio.wav')})
   db=sqlite3.connect(root/'budget.sqlite')
   with db:db.execute('CREATE TABLE calls(n)');db.execute('INSERT INTO calls VALUES(7)')
   db.close()
   (root/'private').mkdir();(root/'private/credentials.json').write_text('never upload');(root/'picture.partial.mp4').write_bytes(b'incomplete')
   store=LocalStore(base/'drive');Snapshot(root,store).checkpoint();fresh=base/'runner2';self.assertTrue(Snapshot(fresh,store).restore());self.assertEqual((fresh/'clip.mp4').read_bytes(),b'completed fixture media');self.assertFalse((fresh/'private').exists());self.assertFalse((fresh/'picture.partial.mp4').exists());self.assertEqual(Path(read(fresh/'job.json')['audio']).resolve(),(fresh/'audio.wav').resolve())
   db=sqlite3.connect(fresh/'budget.sqlite');self.assertEqual(db.execute('SELECT n FROM calls').fetchone()[0],7);db.close()
 def test_interrupted_publish_keeps_previous_complete_generation(self):
  class Failing(LocalStore):
   fail=False
   def put(self,source,name):
    if self.fail and name=='refs/latest.json':raise OSError('Injected upload interruption')
    super().put(source,name)
  with tempfile.TemporaryDirectory() as d:
   b=Path(d);r=b/'work';r.mkdir();save(r/'receipt.json',{'generation':1});store=Failing(b/'drive');s=Snapshot(r,store);s.checkpoint();save(r/'receipt.json',{'generation':2});store.fail=True
   with self.assertRaises(OSError):s.checkpoint()
   restored=b/'restore';Snapshot(restored,store).restore();self.assertEqual(read(restored/'receipt.json')['generation'],1)
 def test_corrupt_checkpoint_blob_is_detected(self):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d);r=b/'work';r.mkdir();(r/'output.bin').write_bytes(b'valid');store=LocalStore(b/'drive');s=Snapshot(r,store);m=s.checkpoint();h=m['files'][0]['sha256'];(b/'drive/objects'/h[:2]/h[2:]).write_bytes(b'corrupt')
   with self.assertRaises(Attention):Snapshot(b/'restore',store).restore()
 def test_missing_and_corrupt_images_are_not_complete_chapters(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);Image.new('RGB',(20,30),'white').save(p/'001.png');self.assertIsNone(verified_images(p,2));(p/'002.png').write_bytes(b'bad image');self.assertIsNone(verified_images(p,2));Image.new('RGB',(20,30),'white').save(p/'002.png');self.assertEqual(len(verified_images(p,2)),2)
 def test_upscale_requires_actual_four_times_dimensions(self):
  from manga_bot.upscale import verify
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);Image.new('RGB',(20,30)).save(p/'source.png');Image.new('RGB',(40,60)).save(p/'out.png');self.assertIsNone(verify(p/'source.png',p/'out.png'));Image.new('RGB',(80,120)).save(p/'out.png');self.assertEqual(verify(p/'source.png',p/'out.png')['size'],[80,120])
 def test_storage_must_succeed_before_any_model_dispatch(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'fixture-only'}):
   api=Google(d,checkpoint=lambda:(_ for _ in ()).throw(Attention('Injected storage failure')))
   with patch('manga_bot.providers.requests.post',side_effect=AssertionError('No dispatch allowed')):
    with self.assertRaises(Attention):api.generate('reader','fixture',{},[],{})
 def test_restored_unknown_request_is_not_replayed(self):
  import requests
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GEMINI_API_KEY':'fixture-only'}):
   b=Path(d);r=b/'first';r.mkdir();store=LocalStore(b/'drive');snapshot=Snapshot(r,store);api=Google(r,r/'provider-state',checkpoint=snapshot.checkpoint)
   with patch('manga_bot.providers.requests.post',side_effect=requests.Timeout('Injected disconnect')):
    with self.assertRaises(Pending):api.generate('reader','fixture',{},[],{})
   fresh=b/'fresh';Snapshot(fresh,store).restore();other=Google(fresh,fresh/'provider-state')
   with patch('manga_bot.providers.requests.post',side_effect=AssertionError('Must not replay unknown acceptance')):
    with self.assertRaises(Pending):other.generate('reader','fixture',{},[],{})
   self.assertEqual(other.budget.summary()[0]['requests'],1)
 def test_repeated_503_gets_cooldown_instead_of_permanent_stop(self):
  with tempfile.TemporaryDirectory() as d:
   api=Google(d);config=dict(model=MODELS['reader'],system='s',payload={},pages=[],schema={},max_tokens=24576,thinking=None,adapter='bot-native-v11');save(Path(d)/'requests'/digest(config)/'result.json',dict(status=503,attempt=3,started_epoch=time.time()))
   with self.assertRaises(Pending) as result:api.generate('reader','s',{},[],{})
   self.assertIn('cooldown',result.exception.reason)
 def test_packed_speech_spans_units_and_reuses_prepared_audio(self):
  from manga_bot.part_audio import prepare
  from manga_bot.media import speech
  class Fake:
   models={'tts':'fixture'}
   calls=0
   def tts(self,text,folder):
    self.calls+=1
    with wave.open(str(folder/'voice.wav'),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\0\0'*72000)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);units=[]
   for i,text in enumerate(['An object moved.','Someone looked back.']):
    uid=f'unit-{i+1:04}';units.append({'id':uid});draft=dict(chapter=uid,text_sha256=digest(text),words=3,entities=[],beats=[dict(id=uid+'-beat-0001',text=text)]);save(root/'units'/uid/'draft.json',draft)
   def fake_timing(audio,target,beats,names):return dict(cues=[dict(beat_id=b['id'],start=i*1.5,end=(i+1)*1.5) for i,b in enumerate(beats)])
   api=Fake()
   with patch('manga_bot.part_audio.transcribe',side_effect=fake_timing):prepare(api,root,{'id':'part-001','units':units},{'tts_batch_words':6,'words_per_minute':120})
   self.assertEqual(api.calls,1)
   for u in units:
    target=root/'units'/u['id'];draft=read(target/'draft.json')
    with patch.object(api,'tts',side_effect=AssertionError('Prepared speech should not call a model')):self.assertTrue(speech(api,root,draft,target).exists())
 def test_storage_paths_cannot_escape_archive(self):
  for name in ['../escape','/absolute','a/../../escape','C:\\secret']:
   with self.assertRaises(ValueError):key(name)
 def test_unconnected_services_do_not_report_production_ready(self):
  with patch.dict(os.environ,{},clear=True):
   cfg=read('config/settings.json');self.assertFalse(doctor(cfg)['production_ready'])
 def test_modern_video_and_part_keep_30fps_and_separate_audio(self):
  from manga_bot.media import unit_video,assemble
  from manga_bot.core import sha
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);uid='unit-0001';target=root/'units'/uid;target.mkdir(parents=True);save(root/'config.json',{'title':'Synthetic fixture','render':{'engine':'subpixel_v11','width':320,'height':180,'fps':30}});pages=[];index={};beats=[]
   for i in range(2):
    path=root/f'p{i}.png';im=Image.new('RGB',(300,450),'white');im.paste((30+i*50,20,20),(30,40,250,300));im.save(path);pid=f'p{i}';ref=f's{i}';pages.append(dict(page_id=pid,path=str(path),sha256=sha(path),size=[300,450]));index[ref]=dict(id=ref,page_id=pid,kind='visual_observation',panel=[.1,.1,.8,.7],region=[.2,.2,.3,.2],order=i);beats.append(dict(id=uid+f'-beat-{i:04}',text='An object moved.',page_id=pid,source_ids=[ref],primary_source_id=ref))
   unit=dict(id=uid,chapters=['1'],pages=pages);draft=dict(chapter=uid,chapters=['1'],text_sha256='fixture',words=6,entities=[],beats=beats);save(target/'draft.json',draft);save(root/'inventory.json',{'units':[unit]});save(target/'source-ledger.json',{'index':index});audio=target/'narration.wav'
   with wave.open(str(audio),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\0\0'*48000)
   save(target/'audio-prepared.json',dict(path=str(audio),audio_sha256=sha(audio),text_sha256='fixture'))
   timing=dict(signature='fixture',words=[],cues=[dict(beat_id=b['id'],start=i,end=i+1) for i,b in enumerate(beats)])
   def fake_timing(*args):save(target/'speech-timing.json',timing);return timing
   with patch('manga_bot.media.transcribe',side_effect=fake_timing),patch('manga_bot.visual_layout.capture'),patch('manga_bot.focus_timing.make'):
    result=unit_video(object(),root,unit,draft)
   self.assertEqual(result['fps'],30);self.assertEqual(result['frames'],60);self.assertTrue((target/'editable.mlt').exists());part=assemble(root,{'id':'part-001','units':[{'id':uid,'chapters':['1']}]});self.assertEqual(part['frames'],60);self.assertEqual(part['fps'],30);self.assertTrue((root/'parts/part-001/narration.wav').exists())
 def test_verified_chapter_is_reused_without_page_requests(self):
  from manga_bot.ingest import download
  from types import SimpleNamespace
  class Fake:
   def __init__(self,*args,**kwargs):pass
   def get_chapters(self):return [{'name':'Chapter 1','url':'https://weebcentral.com/chapters/ONE'}]
   def get_chapter_images(self,*args):raise AssertionError('Completed chapter should not be fetched again')
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'book/source/Chapter 1';folder.mkdir(parents=True)
   for i in [1,2]:Image.new('RGB',(20,30),'white').save(folder/f'{i:03}.png')
   save(root/'book/downloads'/ (digest('https://weebcentral.com/chapters/ONE')+'.json'),dict(complete=True,expected_pages=2,files=verified_images(folder,2)))
   job={'url':'https://weebcentral.com/series/ABC','directory':str(root/'book')}
   with patch('manga_bot.ingest.vendor',return_value=root),patch('manga_bot.ingest.importlib.import_module',return_value=SimpleNamespace(WeebCentralScraper=Fake)):self.assertTrue(download(root,job,{'download':{}}))
   self.assertEqual(job['downloaded_chapters'],1)
 def test_partial_upstream_download_cannot_mark_a_chapter_complete(self):
  from manga_bot.ingest import download
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'book/source/Chapter 1'
   class Fake:
    def __init__(self,*args,**kwargs):pass
    def get_chapters(self):return [{'name':'Chapter 1','url':'https://weebcentral.com/chapters/ONE'}]
    def get_chapter_images(self,*args):return ['https://images.test/1.png','https://images.test/2.png']
    def download_chapter(self,*args):folder.mkdir(parents=True);Image.new('RGB',(20,30)).save(folder/'001.png');return 1,str(folder)
   with patch('manga_bot.ingest.vendor',return_value=root),patch('manga_bot.ingest.importlib.import_module',return_value=SimpleNamespace(WeebCentralScraper=Fake)):
    with self.assertRaises(Pending):download(root,{'url':'https://weebcentral.com/series/ABC','directory':str(root/'book')},{'download':{}})
   receipt=next((root/'book/downloads').glob('*.json'));self.assertFalse(read(receipt)['complete']);self.assertTrue((folder/'001.png').exists())
 def test_colab_disconnect_preserves_newer_gpu_checkpoint(self):
  from manga_bot.manage import upscale_handoff
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);host=base/'host';host.mkdir();save(host/'library.json',{'manga':[{'id':'abc'}]});store=LocalStore(base/'drive');main=Snapshot(host,store);main.checkpoint();gpu=base/'gpu';remote=Snapshot(gpu,store);remote.restore();(gpu/'upscaled').mkdir();(gpu/'upscaled/001.png').write_bytes(b'completed GPU page');save(gpu/'library.json',{'manga':[{'id':'abc','upscale_complete':True}]});remote.checkpoint()
   with patch('manga_bot.colab_bridge.launch',side_effect=TimeoutError('Connection lost after GPU progress')):library,failure=upscale_handoff(main,'abc',{})
   self.assertIsInstance(failure,TimeoutError);self.assertTrue(library['manga'][0]['upscale_complete']);self.assertEqual((host/'upscaled/001.png').read_bytes(),b'completed GPU page');main.checkpoint();fresh=base/'next';Snapshot(fresh,store).restore();self.assertTrue((fresh/'upscaled/001.png').exists())
 def test_lazy_restore_and_eviction_keep_remote_media_retrievable(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);origin=base/'origin';origin.mkdir();(origin/'book/upscaled').mkdir(parents=True);(origin/'book/source').mkdir();(origin/'book/upscaled/001.png').write_bytes(b'upscaled');(origin/'book/source/001.png').write_bytes(b'original');(origin/'video.mp4').write_bytes(b'completed video');store=LocalStore(base/'drive');Snapshot(origin,store).checkpoint();fresh=base/'runner';snapshot=Snapshot(fresh,store,lazy_upscale=True,lazy_media=True);snapshot.restore();self.assertTrue((fresh/'book/source/001.png').exists());self.assertFalse((fresh/'video.mp4').exists());self.assertFalse((fresh/'book/upscaled/001.png').exists());snapshot.checkpoint();snapshot.ensure_path(fresh/'book/upscaled/001.png');self.assertEqual((fresh/'book/upscaled/001.png').read_bytes(),b'upscaled');snapshot.evict_path(fresh/'book/upscaled/001.png');snapshot.checkpoint();restored=base/'third';Snapshot(restored,store).restore();self.assertEqual((restored/'book/upscaled/001.png').read_bytes(),b'upscaled');self.assertEqual((restored/'video.mp4').read_bytes(),b'completed video')
   with self.assertRaises(Attention):snapshot.evict_path(fresh/'book/source/001.png')
 def test_pull_downloads_one_finished_part_without_original_pages(self):
  from manga_bot.manage import pull
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);origin=(base/'origin').resolve();origin.mkdir();book=origin/'manga/abc';part=book/'job/parts/part-001';part.mkdir(parents=True);save(origin/'library.json',{'manga':[{'id':'abc','directory':str(book)}]});save(part/'complete.json',{'duration':2});(part/'video.mp4').write_bytes(b'finished movie');(part/'editable.mlt').write_text('<mlt/>');(origin/'source.png').write_bytes(b'large source fixture');store=LocalStore(base/'drive');Snapshot(origin,store).checkpoint();fresh=(base/'restore').resolve();dest=base/'delivery'
   with patch.dict(os.environ,{'MANGA_LOCAL_ARCHIVE':str(base/'drive')}):pull({'state_root':str(fresh),'storage':{'backend':'local'}},'abc','part-001',dest)
   self.assertEqual((dest/'video.mp4').read_bytes(),b'finished movie');self.assertTrue((dest/'editable.mlt').exists());self.assertFalse((fresh/'source.png').exists())

if __name__=='__main__':unittest.main()
