import tempfile,unittest,json
from pathlib import Path
from unittest.mock import Mock
from manga_bot.core import sha,save,read,Attention
from manga_bot.publishing import upload

class UploadTests(unittest.TestCase):
 def fixture(self,d):
  p=Path(d)/'video.mp4';p.write_bytes(b'x'*300000)
  return {'path':str(p),'sha256':sha(p),'privacy':'private','title':'Example','description':'Example recap'},Path(d)/'youtube-upload.json'
 def response(self,status,body=None,headers=None):
  return Mock(status_code=status,json=lambda:body or {},headers=headers or {},text='')
 def client(self):
  c=Mock();c.get.return_value=self.response(200,{'items':[{'id':'expected'}]});c.post.return_value=self.response(200,headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=example'});return c
 def test_chunks_and_completed_receipt_never_upload_twice(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);c=self.client();c.put.side_effect=[self.response(308),self.response(308,headers={'Range':'bytes=0-262143'}),self.response(200,{'id':'done'})]
   upload(v,p,'expected',lambda:None,c,chunk_bytes=262144)
   self.assertEqual(read(p)['state'],'uploaded');self.assertEqual(c.post.call_args.kwargs['json']['status']['privacyStatus'],'private')
   upload(v,p,'expected',lambda:None,c);self.assertEqual(c.post.call_count,1);self.assertEqual(c.put.call_count,3)
 def test_resume_uses_server_offset_without_reinitializing(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);save(p,dict(sha256=v['sha256'],channel='expected',privacy='private',state='uploading',session='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=example',offset=0));c=self.client();c.put.side_effect=[self.response(308,headers={'Range':'bytes=0-262143'}),self.response(201,{'id':'done'})]
   upload(v,p,'expected',lambda:None,c);c.post.assert_not_called();self.assertEqual(c.put.call_args.kwargs['headers']['Content-Range'],'bytes 262144-299999/300000')
 def test_lost_final_response_recovers_completion_by_probe(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);save(p,dict(sha256=v['sha256'],channel='expected',privacy='private',state='uploading',session='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=example',final_may_have_been_sent=True));c=self.client();c.put.return_value=self.response(200,{'id':'done'})
   upload(v,p,'expected',lambda:None,c);c.post.assert_not_called();self.assertEqual(c.put.call_count,1)
 def test_expired_session_is_held_instead_of_duplicate(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);save(p,dict(sha256=v['sha256'],channel='expected',privacy='private',state='uploading',session='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=example'));c=self.client();c.put.return_value=self.response(404)
   with self.assertRaises(Attention):upload(v,p,'expected',lambda:None,c)
   self.assertEqual(read(p)['state'],'needs_review');c.post.assert_not_called()
 def test_wrong_channel_blocks_before_upload(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);c=self.client()
   with self.assertRaises(Attention):upload(v,p,'other',lambda:None,c)
   c.post.assert_not_called()
 def test_initialization_unknown_never_restarts(self):
  with tempfile.TemporaryDirectory() as d:
   v,p=self.fixture(d);save(p,dict(sha256=v['sha256'],channel='expected',privacy='private',state='initiating_unknown'));c=self.client()
   with self.assertRaises(Attention):upload(v,p,'expected',lambda:None,c)
   c.post.assert_not_called()
if __name__=='__main__':unittest.main()
