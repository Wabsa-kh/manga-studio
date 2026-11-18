import json,tempfile,unittest,time
from pathlib import Path
from unittest.mock import patch
import requests
from manga_bot.core import Pending,Attention,Budget
from manga_bot.routing import Router
from manga_bot.credentials import Pool,ContentRejected,load_credentials

SCHEMA={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
class Response:
 def __init__(self,code=200,data=None,headers=None):self.status_code=code;self.data=data or {};self.headers=headers or {};self.ok=200<=code<300;self.text=json.dumps(self.data)
 def json(self):return self.data
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def close(self):pass
 def raise_for_status(self):
  if not self.ok:raise requests.HTTPError('fixture')
def google():return Response(data={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"answer":"ok"}'}]}}],'usageMetadata':{'totalTokenCount':3}})
def chat():return Response(data={'choices':[{'finish_reason':'stop','message':{'content':'{"answer":"ok"}'}}],'usage':{'total_tokens':3}})
def credential(ident,provider='google',project=''):
 return {'id':ident,'provider':provider,'api_key':'fixture-credential-'+ident,'project_id':project}
def environment(rows):return patch.dict('os.environ',{'MODEL_CREDENTIALS_JSON':json.dumps({'credentials':rows})})
def routes(**changes):return {'reader':{'provider':'google','model':'fixture-model','daily_requests':100,'rpm':100,**changes}}
class RoutingTests(unittest.TestCase):
 def test_speech_rotates_keys_and_reuses_finished_audio(self):
  import io,wave,base64
  blob=io.BytesIO()
  with wave.open(blob,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0\0'*2400)
  response=Response(data={'steps':[{'type':'model_output','content':[{'type':'audio','data':base64.b64encode(blob.getvalue()).decode()}]}],'usage':{'total_tokens':3}})
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('b')]),patch('requests.post',return_value=response) as post:
   api=Router(d);self.assertTrue(api.tts('one',Path(d)/'one')['complete']);self.assertTrue(api.tts('two',Path(d)/'two')['complete'])
   self.assertNotEqual(post.call_args_list[0].kwargs['headers'],post.call_args_list[1].kwargs['headers']);api.tts('one',Path(d)/'one');self.assertEqual(post.call_count,2)
 def test_short_pacing_waits_checkpoint_and_continue_same_run(self):
  from manga_bot.manage import short_wait
  from unittest.mock import Mock
  checkpoint=Mock()
  with patch('time.time',side_effect=[100,100,102,102]),patch('time.sleep') as sleep:
   self.assertTrue(short_wait(Pending('minute pacing',102),{'short_wait_seconds':120},1000,checkpoint))
  checkpoint.assert_called_once();sleep.assert_called_once()
 def test_long_quota_wait_ends_run_instead_of_sleeping_overnight(self):
  from manga_bot.manage import short_wait
  from unittest.mock import Mock
  checkpoint=Mock()
  with patch('time.time',return_value=100),patch('time.sleep') as sleep:self.assertFalse(short_wait(Pending('daily quota',10000),{},20000,checkpoint))
  checkpoint.assert_not_called();sleep.assert_not_called()
 def test_cooldown_elapsed_during_saving_does_not_stop_the_day(self):
  from manga_bot.manage import short_wait
  from unittest.mock import Mock
  checkpoint=Mock()
  with patch('time.time',return_value=100),patch('time.sleep') as sleep:self.assertTrue(short_wait(Pending('pacing already elapsed',99),{},1000,checkpoint))
  checkpoint.assert_called_once();sleep.assert_not_called()
 def test_schema_projection_preserves_facts_and_invalid_values(self):
  from manga_bot.routing import schema_projection
  schema={'type':'object','properties':{'fact':{'type':'string','enum':['known']}},'required':['fact'],'additionalProperties':False}
  dropped=[];result=schema_projection({'fact':'unsupported','extra':'commentary'},schema,dropped=dropped)
  self.assertEqual(result,{'fact':'unsupported'});self.assertEqual(dropped,['$.extra'])
  from efficient_pipeline import schema_errors
  self.assertTrue(schema_errors(schema,result));self.assertTrue(schema_errors(schema,schema_projection({},schema)))
 def test_rotation_is_persistent_and_success_is_cached(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('b')]),patch('requests.post',side_effect=lambda *a,**kw:google()) as post:
   api=Router(d,options=routes());api.generate('reader','s',{'n':1},[],SCHEMA);Router(d,options=routes()).generate('reader','s',{'n':2},[],SCHEMA)
   self.assertNotEqual(post.call_args_list[0].kwargs['headers'],post.call_args_list[1].kwargs['headers']);api.generate('reader','s',{'n':1},[],SCHEMA);self.assertEqual(post.call_count,2)
 def test_same_project_does_not_get_extra_budget(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a',project='shared'),credential('b',project='shared')]),patch('requests.post',return_value=google()) as post:
   api=Router(d,options=routes(daily_requests=1));api.generate('reader','s',{'n':1},[],SCHEMA)
   with self.assertRaises(Pending):api.generate('reader','s',{'n':2},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_unmapped_google_keys_share_budget(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('b')]),patch('requests.post',return_value=google()) as post:
   api=Router(d,options=routes(daily_requests=1));api.generate('reader','s',{'n':1},[],SCHEMA)
   with self.assertRaises(Pending):api.generate('reader','s',{'n':2},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_partial_project_mapping_does_not_create_extra_capacity(self):
  with environment([credential('a',project='known'),credential('b')]):
   rows=load_credentials();self.assertEqual({r['quota_group'] for r in rows},{'unmapped'})
 def test_owner_reported_accounts_do_not_require_project_numbers(self):
  rows=[{**credential('a'),'quota_group':'account-a','scope_evidence':'owner_reported_separate_account'},{**credential('b'),'quota_group':'account-b','scope_evidence':'owner_reported_separate_account'}]
  with environment(rows):self.assertEqual({r['quota_group'] for r in load_credentials()},{'account-a','account-b'})
 def test_observed_shared_project_merges_counts_without_losing_usage(self):
  rows=[{**credential('a'),'quota_group':'account-a','scope_evidence':'owner_reported_separate_account'},{**credential('b'),'quota_group':'account-b','scope_evidence':'owner_reported_separate_account'}]
  body=json.dumps({'error':{'details':[{'@type':'type.googleapis.com/google.rpc.ErrorInfo','metadata':{'consumer':'projects/123456789'}}]}})
  with tempfile.TemporaryDirectory() as d,environment(rows):
   api=Router(d)
   for row in api.pool.rows:api.pool.reserve(row,'m',10,10);api.pool.observe(row,body)
   summary=api.budget.summary();self.assertEqual(len(summary),1);self.assertEqual(summary[0]['requests'],2);self.assertIn('123456789',summary[0]['model'])
 def test_last_automatically_discovered_project_releases_shared_group(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a',project='123456789'),credential('b')]):
   api=Router(d)
   for row in api.pool.rows:api.pool.reserve(row,'m',10,10)
   api.pool.observe(api.pool.rows[1],json.dumps({'error':{'details':[{'@type':'type.googleapis.com/google.rpc.ErrorInfo','metadata':{'consumer':'projects/987654321'}}]}}))
   self.assertEqual({r['model'] for r in api.budget.summary()},{'google|123456789|m','google|987654321|m'})
   self.assertEqual(sum(r['requests'] for r in api.budget.summary()),2)
 def test_separate_projects_can_use_separate_budgets(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a',project='project-a'),credential('b',project='project-b')]),patch('requests.post',return_value=google()) as post:
   api=Router(d,options=routes(daily_requests=1));api.generate('reader','s',{'n':1},[],SCHEMA);api.generate('reader','s',{'n':2},[],SCHEMA);self.assertEqual(post.call_count,2)
 def test_401_quarantines_only_rejected_key(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('b')]),patch('requests.post',side_effect=[Response(401),google(),google()]) as post:
   api=Router(d,options=routes());api.generate('reader','s',{'n':1},[],SCHEMA);api.generate('reader','s',{'n':2},[],SCHEMA)
   self.assertEqual(post.call_count,3);self.assertEqual(len(api.pool.candidates('google')),1)
 def test_429_tries_another_verified_project(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a',project='project-a'),credential('b',project='project-b')]),patch('requests.post',side_effect=[Response(429,{'error':'daily quota'}),google()]) as post:
   api=Router(d,options=routes());self.assertTrue(api.generate('reader','s',{},[],SCHEMA)['complete']);self.assertEqual(post.call_count,2)
 def test_google_retryinfo_is_honored(self):
  from manga_bot.credentials import http_error,QuotaWait
  body=json.dumps({'error':{'details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'3s'}]}})
  with tempfile.TemporaryDirectory() as d,environment([credential('a')]),patch('time.time',return_value=100):
   api=Router(d)
   with self.assertRaises(QuotaWait) as wait:http_error(api.pool,api.pool.rows[0],'m',429,body,{})
   self.assertEqual(wait.exception.resume,103)
 def test_unknown_google_acceptance_does_not_rotate(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('b')]),patch('requests.post',side_effect=requests.Timeout('fixture')) as post:
   api=Router(d,options=routes())
   with self.assertRaises(Pending):api.generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_unknown_acceptance_remains_blocked_after_restart_and_route_change(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('n','nim')]),patch('requests.post',side_effect=requests.Timeout('fixture')) as post:
   api=Router(d,options=routes())
   with self.assertRaises(Pending):api.generate('reader','s',{},[],SCHEMA)
   with patch('time.time',return_value=time.time()+4000):
    with self.assertRaises(Attention):Router(d,options={'reader':{'provider':'nim','model':'fixture-vl'}}).generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_known_service_failure_can_fall_back_to_nim(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('n','nim')]),patch('requests.post',side_effect=[Response(503),chat()]) as post:
   api=Router(d,options=routes(fallbacks=[{'provider':'nim','model':'fixture-vl'}]));result=api.generate('reader','s',{},[],SCHEMA)
   self.assertEqual(result['provider'],'nim');self.assertEqual(post.call_count,2)
 def test_content_rejection_never_reroutes(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a'),credential('n','nim')]),patch('requests.post',return_value=Response(data={'promptFeedback':{'blockReason':'SAFETY'}})) as post:
   api=Router(d,options=routes(fallbacks=[{'provider':'nim','model':'fixture-vl'}]))
   with self.assertRaises(Attention):api.generate('reader','s',{},[],SCHEMA)
   with self.assertRaises(ContentRejected):Router(d,options={'reader':{'provider':'nim','model':'fixture-vl'}}).generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_paid_openrouter_is_rejected_before_dispatch(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('o','openrouter')]),patch('requests.post') as post:
   with self.assertRaises(Attention):Router(d,options={'reader':{'provider':'openrouter','model':'paid-model'}}).generate('reader','s',{},[],SCHEMA)
   post.assert_not_called()
 def test_openrouter_429_does_not_cycle_keys(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a','openrouter'),credential('b','openrouter')]),patch('requests.post',return_value=Response(429,{'error':'shared free limit'})) as post:
   api=Router(d,options={'reader':{'provider':'openrouter','model':'openrouter/free'}})
   with self.assertRaises(Pending):api.generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_nim_async_poll_completes_without_second_generation(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('n','nim')]),patch('requests.post',return_value=Response(202,headers={'NVCF-REQID':'12345678-1234-1234-1234-123456789abc'})) as post,patch('requests.get',return_value=chat()) as get,patch('time.sleep'):
   api=Router(d,options={'reader':{'provider':'nim','model':'fixture-vl'}});self.assertTrue(api.generate('reader','s',{},[],SCHEMA)['complete']);self.assertEqual(post.call_count,1);self.assertEqual(get.call_count,1)
 def test_accepted_nim_request_with_failed_poll_does_not_reroute(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('n','nim'),credential('a')]),patch('requests.post',return_value=Response(202,headers={'NVCF-REQID':'12345678-1234-1234-1234-123456789abc'})) as post,patch('requests.get',return_value=Response(503)),patch('time.sleep'):
   api=Router(d,options={'reader':{'provider':'nim','model':'fixture-vl','fallbacks':[{'provider':'google','model':'fixture-model'}]}})
   with self.assertRaises(Pending):api.generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_shared_quota_limits_can_be_configured(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('n','nim')]):
   api=Router(d,quota_limits={'nim':{'rpm':1,'daily_requests':2}});row=api.pool.rows[0];api.pool.reserve(row,'one',10,10)
   with self.assertRaises(Pending):api.pool.reserve(row,'two',10,10)
 def test_long_manga_parts_cover_every_unit_once(self):
  from manga_bot.core import choose_part
  units=[{'id':i,'words':1250,'boundary':{'score':4 if i%9==8 else 2}} for i in range(53)];remaining=list(units);parts=[]
  while remaining:
   n=choose_part(remaining,45,60,207,at_end=True);self.assertGreater(n,0);parts.append(remaining[:n]);remaining=remaining[n:]
  self.assertEqual([u['id'] for part in parts for u in part],list(range(53)))
  for part in parts[:-1]:self.assertTrue(45<=sum(u['words'] for u in part)/207<=60)
 def test_unknown_chat_is_not_replayed_across_keys(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a','nim'),credential('b','nim')]),patch('requests.post',side_effect=requests.Timeout('fixture')) as post:
   api=Router(d,options={'reader':{'provider':'nim','model':'fixture-vl'}})
   for _ in range(2):
    with self.assertRaises(Pending):api.generate('reader','s',{},[],SCHEMA)
   self.assertEqual(post.call_count,1)
 def test_shared_provider_budget_covers_different_models(self):
  with tempfile.TemporaryDirectory() as d:
   budget=Budget(Path(d)/'quota.sqlite');budget.reserve('nim|account|model-a',100,10,shared_prefix='nim|',shared_daily=1)
   with self.assertRaises(Pending):budget.reserve('nim|account|model-b',100,10,shared_prefix='nim|',shared_daily=1)
 def test_replacement_key_recovers_from_quarantine(self):
  with tempfile.TemporaryDirectory() as d,environment([credential('a')]):
   api=Router(d);api.pool.reject(api.pool.rows[0]);self.assertEqual(api.pool.candidates('google'),[])
   replacement=credential('a');replacement['api_key']='fixture-new-replacement'
   with environment([replacement]):self.assertEqual(len(Router(d).pool.candidates('google')),1)
if __name__=='__main__':unittest.main()
