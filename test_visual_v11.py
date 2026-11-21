import unittest,tempfile,math
from pathlib import Path
from PIL import Image
import numpy as np
from manga_bot.camera_v11 import plan,sample,policy,ease
from manga_bot.render_v11 import matrix,paper_color,Frames
from manga_bot.core import sha

class VisualTests(unittest.TestCase):
 def fixture(self):
  pages={'p1':dict(size=[900,1300],path='fixture',sha256='fixture')};index={}
  for i,(y,kind) in enumerate([(.1,'speech'),(.5,'speech'),(.8,'speech')]):index[f's{i}']=dict(id=f's{i}',page_id='p1',kind=kind,panel=[.05,y,.9,.18],region=[.7,y,.2,.1],order=i)
  beats=[dict(id='b1',page_id='p1',source_ids=list(index))];timing=[dict(beat_id='b1',start=0,end=12)];return pages,index,beats,timing
 def test_subpixel_translation_is_preserved(self):
  p=dict(z=2.6,x=0.,y=0.);a=matrix((900,1300),p,1280,720);b=matrix((900,1300),{**p,'x':.1},1280,720);self.assertAlmostEqual(b[0,2]-a[0,2],.1*1280/1920,places=10)
 def test_motion_is_continuous_at_transfer_boundaries(self):
  pages,index,beats,timing=self.fixture();data=plan(beats,timing,index,pages,{});s=data['shots'][0];cfg=data['config']
  for m in s['moves']:
   for t in [m['at'],m['at']+m['duration']]:
    a=sample(s,t-1e-6,cfg);b=sample(s,t+1e-6,cfg);self.assertLess(max(abs(a[k]-b[k]) for k in a),.001)
 def test_holds_dominate_travel(self):
  pages,index,beats,timing=self.fixture();s=plan(beats,timing,index,pages,{})['shots'][0];travel=sum(m['duration'] for m in s['moves']);self.assertLess(travel/s['duration'],.2);self.assertTrue(all(m['duration']<=.62 for m in s['moves']))
 def test_character_geometry_replaces_balloon_center(self):
  pages,index,beats,timing=self.fixture();anchor=dict(subject_box=[.1,.52,.2,.15],panel_box=index['s1']['panel'],confidence=.95,kind='character',source_ids=['s1']);layouts={'p1':dict(anchors=[anchor])};beats[0]['source_ids']=['s1'];s=plan(beats,timing,index,pages,layouts)['shots'][0];self.assertEqual(s['targets'][0]['basis'],'vision_subject');self.assertEqual(s['targets'][0]['subject_box'],anchor['subject_box'])
 def test_spoken_phrase_cue_controls_transfer_time(self):
  pages,index,beats,timing=self.fixture();a=dict(subject_box=[.1,.1,.2,.15],panel_box=index['s0']['panel'],kind='character',source_ids=['s0']);b=dict(subject_box=[.1,.8,.2,.15],panel_box=index['s2']['panel'],kind='action',source_ids=['s2']);focus={'b1':[dict(anchor=a,at=0,phrase='First event'),dict(anchor=b,at=8,phrase='Later event')]};s=plan(beats,timing,index,pages,{},focus_cues=focus)['shots'][0];self.assertAlmostEqual(s['moves'][0]['at'],8-.62*.75);self.assertTrue(all(t['basis']=='spoken_phrase_subject' for t in s['targets']))
 def test_short_beat_widens_to_include_unmentioned_panel_and_subject(self):
  pages,index,beats,timing=self.fixture()
  beats[0]['source_ids']=['s1'];timing[0]['end']=3
  anchor=dict(subject_box=[.08,.51,.26,.17],panel_box=index['s1']['panel'],confidence=.95,kind='character',source_ids=['s1'])
  extra=[.05,.09,.9,.22]
  data=plan(beats,timing,index,pages,{'p1':dict(anchors=[anchor])},page_panels={'p1':[extra,index['s1']['panel']]})
  target=data['shots'][0]['targets'][0]
  self.assertEqual(target['basis'],'panel_coverage')
  projection=matrix(pages['p1']['size'],target['pose'],1920,1080)
  for x,y,w,h in (extra,anchor['subject_box']):
   for px,py in ((x,y),(x+w,y+h)):
    vx,vy,_=projection@np.array([px*900,py*1300,1])
    self.assertTrue(0<vx<1920 and 0<vy<1080)
 def test_paper_color_ignores_border_ink(self):
  im=Image.new('RGB',(100,100),(248,247,244));im.putpixel((0,0),(0,0,0));self.assertEqual(list(paper_color(im)),[248,247,244])
 def test_projective_frame_is_deterministic_and_seekable(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'page.png';im=Image.new('RGB',(400,600),'white');im.paste((20,20,20),(80,100,300,400));im.save(path);cfg=policy({'width':320,'height':180});shot=dict(page_id='p1',source_path=str(path),source_sha256=sha(path),start=0,end=2,duration=2,initial=dict(z=2.5,x=0,y=0),moves=[],targets=[],transition='dissolve');f=Frames({'config':cfg,'shots':[shot]});a=f.frame(.7);f.frame(1.2);b=f.frame(.7);self.assertTrue(np.array_equal(a,b));self.assertEqual(a.shape,(180,320,3));self.assertGreater(a.std(),10)
 def test_easing_has_zero_endpoint_velocity(self):
  epsilon=1e-5;self.assertLess(ease(epsilon)/epsilon,1e-6);self.assertLess((1-ease(1-epsilon))/epsilon,1e-6)

if __name__=='__main__':unittest.main()
