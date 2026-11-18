import tempfile,unittest
from pathlib import Path
from manga_bot.catalog import sync,ordered
from manga_bot.core import save,read,Attention

class CatalogTests(unittest.TestCase):
 def test_sync_pause_and_settings_preserve_progress(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)/'state';path=Path(folder)/'list.json';cfg={'manga_list_file':str(path)}
   save(path,{'manga':[{'url':'https://weebcentral.com/series/ABC/Example','title':'Example','part_minutes':[30,45],'priority':2}]});sync(root,cfg)
   library=read(root/'library.json');item=library['manga'][0];item.update(state='waiting',resume_epoch=123,download_complete=True);save(root/'library.json',library)
   save(path,{'manga':[]});sync(root,cfg);item=read(root/'library.json')['manga'][0]
   self.assertFalse(item['enabled']);self.assertTrue(item['download_complete']);self.assertEqual(item['state'],'waiting')
   save(path,{'manga':[{'url':'https://weebcentral.com/series/ABC','title':'Renamed','enabled':True}]});sync(root,cfg);item=read(root/'library.json')['manga'][0]
   self.assertTrue(item['enabled']);self.assertNotIn('part_minutes',item);self.assertEqual(item['resume_epoch'],123);self.assertEqual(item['title'],'Renamed')
 def test_invalid_list_does_not_partially_add_jobs(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)/'state';path=Path(folder)/'list.json'
   save(path,{'manga':[{'url':'https://weebcentral.com/series/ABC'},{'url':'https://weebcentral.com/series/DEF','part_minutes':[60,30]}]})
   with self.assertRaises(Attention):sync(root,{'manga_list_file':str(path)})
   self.assertFalse((root/'library.json').exists())
 def test_duplicate_canonical_links_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'list.json';save(p,{'manga':[{'url':'https://weebcentral.com/series/ABC/One'},{'url':'https://www.weebcentral.com/series/ABC/Two'}]})
   with self.assertRaises(Attention):sync(Path(folder)/'state',{'manga_list_file':str(p)})
 def test_priority_then_file_order(self):
  result=ordered({'manga':[{'id':'second','priority':2,'list_order':0},{'id':'third','priority':2,'list_order':1},{'id':'first','priority':1}]})
  self.assertEqual([x['id'] for x in result],['first','second','third'])
if __name__=='__main__':unittest.main()
