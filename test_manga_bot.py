"""Regression checks for persistence, budgets and unattended decision boundaries."""
import tempfile,unittest,time,json
from pathlib import Path
from unittest.mock import patch
from manga_bot.core import Budget,Pending,Attention,units_for,choose_part,quota_day,next_reset,save,read,digest
from manga_bot.stages import read_batch,reader_schema
from manga_bot.providers import Google,MODELS
from manga_bot.media import listing,shotcut

class BotTests(unittest.TestCase):
 def test_chapter_parts_remain_in_order_and_are_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   pages=[]
   for i,c in enumerate(['1','1','2.1','2.2','3','4']):
    p=Path(d)/str(i);p.write_bytes(b'x');pages.append(dict(chapter=c,path=str(p),page_id=str(i)))
   units=units_for(pages,4);self.assertEqual([p['page_id'] for u in units for p in u['pages']],[str(i) for i in range(6)]);self.assertEqual(units[0]['chapters'],['1','2.1','2.2']);self.assertTrue(all(len(u['pages'])<=4 for u in units))
 def test_part_boundaries_use_measured_audio(self):
  units=[dict(words=1000,duration_minutes=10,boundary={'score':2}) for _ in range(7)]
  self.assertEqual(choose_part(units),5);self.assertIsNone(choose_part(units[:4]));self.assertEqual(choose_part(units[:2],at_end=True),2)
 def test_good_break_after_midpoint(self):
  units=[dict(words=2070,boundary={'score':2}) for _ in range(6)];units[-1]['boundary']['score']=5;self.assertEqual(choose_part(units),6)
 def test_daily_and_minute_budget_survive_restart(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'budget.sqlite';b=Budget(path);b.reserve('model',2,1)
   with self.assertRaises(Pending):Budget(path).reserve('model',2,1)
   b.reserve('model',2,100)
   with self.assertRaises(Pending):Budget(path).reserve('model',2,100)
   self.assertEqual(b.summary()[0]['requests'],2)
 def test_reset_is_pacific_midnight(self):
  stamp=1795000000;self.assertGreater(next_reset(stamp),stamp);self.assertLessEqual(next_reset(stamp)-stamp,25*3600);self.assertNotEqual(quota_day(stamp),quota_day(next_reset(stamp)))
 def test_unknown_reservation_is_not_replayed_early(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);api=Google(root);config=dict(model=MODELS['reader'],system='s',payload={},pages=[],schema={},max_tokens=24576,thinking=None,adapter='bot-native-v11');receipt=root/'requests'/digest(config)/'result.json';save(receipt,dict(status='started_unknown',started_epoch=time.time(),attempt=1))
   with patch.object(api,'before',side_effect=AssertionError('Must not dispatch')):
    with self.assertRaises(Pending):api.generate('reader','s',{},[],{})
 def test_truncated_response_is_handled_locally_without_replay(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);api=Google(root);config=dict(model=MODELS['reader'],system='s',payload={},pages=[],schema={},max_tokens=24576,thinking=None,adapter='bot-native-v11');save(root/'requests'/digest(config)/'result.json',dict(known_incomplete=True,finish='MAX_TOKENS'))
   with patch.object(api,'before',side_effect=AssertionError('Must not dispatch')):self.assertEqual(api.generate('reader','s',{},[],{})['finish'],'MAX_TOKENS')
 def test_permanent_access_hold_never_changes_keys(self):
  with tempfile.TemporaryDirectory() as d:
   b=Budget(Path(d)/'b.sqlite');b.set_hold('m','Access denied',permanent=True)
   with self.assertRaises(Attention):b.reserve('m',100,100)
 def test_metadata_classification_is_content_driven(self):
  s=reader_schema()['properties']['pages']['items'];self.assertIn('mixed',s['properties']['page_kind']['enum']);self.assertIn('story_content_present',s['required'])
 def test_daily_429_waits_instead_of_spending_retries(self):
  with tempfile.TemporaryDirectory() as d:
   api=Google(d)
   with self.assertRaises(Pending) as result:api.error(MODELS['writer'],429,'quota GenerateRequestsPerDay exceeded',{})
   self.assertGreater(result.exception.resume,time.time()+60)
 def test_concat_paths_escape_apostrophes(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'list.txt';listing(path,[Path(d)/"it's.mp4"]);self.assertIn("it'\\''s.mp4",path.read_text())
 def test_atomic_json_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.json';save(p,{'name':'日本'});self.assertEqual(read(p),{'name':'日本'});self.assertEqual(len(list(Path(d).glob('*.tmp'))),0)
 def test_incomplete_batches_split_and_resume_without_new_calls(self):
  class Fake:
   def __init__(self):self.calls=[]
   def generate(self,stage,system,payload,pages,*args):
    self.calls.append(len(pages))
    if len(pages)>2:return {'complete':False}
    return dict(complete=True,config={},output={'pages':[dict(page_id=p['page_id'],page_kind='story',story_content_present=True,panels=[dict(region=dict(left=0,top=0,right=1000,bottom=1000),description='Fixture',texts=[],visible_events=['An object moved.'])],uncertainties=[]) for p in pages]})
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);api=Fake();pages=[dict(page_id=f'ch1-p{i}',sha256='fixture') for i in range(4)];read_batch(api,root,pages);self.assertEqual(api.calls,[4,2,2]);read_batch(api,root,pages);self.assertEqual(api.calls,[4,2,2]);self.assertEqual(len(list((root/'pages').glob('*.json'))),4)
 def test_unknown_reference_and_backwards_page_are_rejected(self):
  from series_writing_v9 import check_script
  pages=[{'page_id':'p1'},{'page_id':'p2'}];index={'s1':{'page_id':'p1'},'s2':{'page_id':'p2'}}
  output=dict(coverage=[dict(page_id=p['page_id']) for p in pages],segments=[dict(page_id='p2',text='An event happened.',source_ids=['s2']),dict(page_id='p1',text='Another event happened.',source_ids=['s1'])]);self.assertTrue(any('backwards' in e for e in check_script(output,pages,index)));output['segments']=[dict(page_id='p1',text='An event happened.',source_ids=['invented'])];self.assertTrue(check_script(output,pages,index))
 def test_real_render_and_part_assembly_with_synthetic_sources(self):
  import wave
  from PIL import Image,ImageDraw
  from manga_bot.core import sha
  from manga_bot.media import unit_video,assemble
  import series_av_v9 as av
  class FakeSpeech:
   def tts(self,text,folder):
    folder.mkdir(parents=True,exist_ok=True)
    if not (folder/'voice.wav').exists():
     with wave.open(str(folder/'voice.wav'),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\x00\x00'*48000)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);uid='unit-0001';target=root/'units'/uid;target.mkdir(parents=True);save(root/'config.json',{'title':'Synthetic fixture'});pages=[];index={};beats=[]
   for i in range(2):
    pid=f'p{i}';path=root/(pid+'.png');im=Image.new('RGB',(800,1200),'white');ImageDraw.Draw(im).rectangle((80,80,720,600),fill=(30+i*70,30,30),outline='black');im.save(path);pages.append(dict(page_id=pid,path=str(path),sha256=sha(path),size=[800,1200]));ref=f's{i}';index[ref]=dict(id=ref,page_id=pid,kind='visual_observation',region=[.2,.2,.4,.2],panel=[.1,.05,.8,.5],order=i);beats.append(dict(id=f'b{i}',text='An object moved.',page_id=pid,source_ids=[ref],primary_source_id=ref))
   save(target/'source-ledger.json',{'index':index});draft=dict(chapter=uid,chapters=['1'],entities=[],beats=beats,text='An object moved. An object moved.',text_sha256='fixture',words=6);unit=dict(id=uid,pages=pages,chapters=['1'])
   def timing(audio,*args):
    duration=av.duration(audio);return dict(cues=[dict(beat_id='b0',start=0,end=duration/2),dict(beat_id='b1',start=duration/2,end=duration)],alignment_ratio=1)
   with patch('manga_bot.media.transcribe',side_effect=timing):result=unit_video(FakeSpeech(),root,unit,draft)
   self.assertTrue(result['technical_qa']);self.assertTrue(av.qa_current(target,read(target/'camera-plan.json')));part={'id':'part-001','units':[dict(id=uid,chapters=['1'])]};r=assemble(root,part);self.assertTrue(Path(r['path']).exists());self.assertTrue((root/'parts/part-001/editable.mlt').exists());self.assertTrue((root/'parts/part-001/contact-sheet.jpg').exists());self.assertLess(abs(r['duration']-av.duration(target/'narration-timeline.wav')),1/24)
 def test_compact_writer_ids_roundtrip_to_camera_evidence(self):
  from manga_bot.stages import write_unit
  owner=self
  class FakeWriter:
   def generate(self,stage,system,payload,pages,schema,*args):
    item=payload['current_pages'][0]['items'][0];owner.assertNotIn('region',item);owner.assertEqual(item['text'],'An object moved.');owner.assertEqual(item['id'],'e0001')
    return dict(complete=True,config={'model':'fixture'},output=dict(segments=[dict(page_id='p1',text='An object moved.',source_ids=[item['id']])],coverage=[dict(page_id='p1',decision='narrated',reason='Event')],entities=[],handoff=dict(ending_state='Object moved',open_questions=[],active_frame='Present'),boundary=dict(score=3,reason='Fixture'),uncertainties=[]))
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);save(root/'pages/p1.json',dict(page_kind='story',story_content_present=True,reading={'pages':[dict(page_id='p1',uncertainties=[],panels=[dict(id='p1-panel-001',region=[0,0,1,1],texts=[],visible_events=['An object moved.'])])]}));draft=write_unit(FakeWriter(),root,dict(id='unit-0001',chapters=['1'],pages=[{'page_id':'p1'}]),[]);self.assertEqual(draft['beats'][0]['primary_source_id'],'p1-panel-001-event-001');self.assertEqual(draft['source_aliases']['e0001'],'p1-panel-001-event-001')

if __name__=='__main__':unittest.main()
