"""Freeze and pack speech across units, then split at measured spoken boundaries."""
from pathlib import Path
from .core import read,save,digest,sha,Attention
from .media import transcribe,listing,ff
from tts_jobs import chunks
import series_av_v9 as av

def prepare(api,root,part,config):
 root=Path(root);folder=root/'parts'/part['id']/'speech';folder.mkdir(parents=True,exist_ok=True);drafts=[read(root/'units'/u['id']/'draft.json') for u in part['units']];beats=[b for d in drafts for b in d['beats']];old=read(folder/'scope.json');limit=old['max_words'] if old else config.get('tts_batch_words',2200);groups=chunks(beats,limit);scope=dict(texts=[d['text_sha256'] for d in drafts],groups=[[b['id'] for b in g] for g in groups],max_words=limit)
 if old and old!=scope:raise Attention('Frozen part speech scope changed')
 save(folder/'scope.json',scope);fragments={d['chapter']:[] for d in drafts};names=list(dict.fromkeys(e['name'] for d in drafts for e in d['entities'] if e['name']))
 for i,group in enumerate(groups):
  batch=folder/f'batch-{i:03}';batch.mkdir(exist_ok=True);text=' '.join(b['text'] for b in group);api.tts(text,batch);audio=batch/'voice.wav';timing=transcribe(audio,batch,group,names);cues=timing['cues'];owners=[b['id'].split('-beat-')[0] for b in group];start=0
  while start<len(group):
   owner=owners[start];end=start+1
   while end<len(group) and owners[end]==owner:end+=1
   begin=cues[start]['start'];finish=cues[end-1]['end'];out=batch/(owner+'.wav');note=out.with_suffix('.json');signature=digest(dict(audio=sha(audio),start=begin,end=finish));prior=read(note)
   if not out.exists() or not prior or prior['signature']!=signature:
    ff(['-i',audio,'-af',f'atrim=start={begin:.8f}:end={finish:.8f},asetpts=PTS-STARTPTS','-ar','48000','-ac','1',out]);save(note,{'signature':signature})
   fragments[owner].append(out);start=end
 for draft in drafts:
  target=root/'units'/draft['chapter'];audio=target/'narration.wav';note=target/'audio-prepared.json';sig=digest(dict(fragments=[sha(p) for p in fragments[draft['chapter']]],text=draft['text_sha256'],wpm=config.get('words_per_minute',207)));old=read(note)
  if old and old.get('signature')==sig and audio.exists() and old['audio_sha256']==sha(audio):continue
  raw=sum(av.duration(p) for p in fragments[draft['chapter']]);tempo=config.get('words_per_minute',207)/(draft['words']/raw*60)
  if not .5<=tempo<=2:raise Attention('Speech pace is outside the supported correction range')
  concat=target/'prepared-fragments.txt';listing(concat,fragments[draft['chapter']]);ff(['-f','concat','-safe','0','-i',concat,'-af',f'atempo={tempo:.8f},loudnorm=I=-16:TP=-1.5:LRA=11','-ar','48000','-ac','1',audio]);save(note,dict(signature=sig,text_sha256=draft['text_sha256'],audio_sha256=sha(audio),path=str(audio),duration=av.duration(audio),model=api.models['tts'],voice='Charon',part=part['id']))
 save(folder/'complete.json',dict(scope_sha256=digest(scope),tts_requests=len(groups),words=sum(d['words'] for d in drafts),units=[d['chapter'] for d in drafts]))
