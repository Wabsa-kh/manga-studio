"""Native structured output experiment; validation is separate from source truth."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from nim_client import Client
from nim_benchmark import FOCUSED,TEXT_SCHEMA
from storybench import ROOT,inventory,DEFAULT_SOURCE

OUT=ROOT/'experiments/free-capacity-v3/nim'
SUPER='nvidia/nemotron-3.5-super-vl-120b-a12b'
def native(schema):return {'response_format':{'type':'json_schema','json_schema':{'name':'manga_reading','strict':True,'schema':schema}}}

if __name__=='__main__':
    c=Client(OUT,max_calls=24,planning_budget=450000,rpm=20)
    pages=inventory(Path(DEFAULT_SOURCE),[0])
    def work(n):return c.run(f'super-native-p{n+1}',FOCUSED,'Extract the supplied page into the required JSON. Preserve text-block order; unknown speakers use actual JSON null.',[pages[n]],max_tokens=8192,reasoning_budget=1024,model=SUPER,options=native(TEXT_SCHEMA),wall_limit=180)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(work,[1,6]))
