"""Resumable Gemini 3.8 TTS chunks with the shared local budget and no cloud fallback."""
import argparse,hashlib,json,uuid,wave
from pathlib import Path
from datetime import datetime,timezone
from job_store import JobStore
from storybench import ROOT,dump
from render_sample import synthesize

def chunks(beats,max_words=450):
    result=[];current=[];words=0
    for beat in beats:
        n=len(beat['text'].split())
        if n>max_words:raise ValueError('A spoken beat exceeds the chunk bound; split it at a meaningful source boundary')
        if current and words+n>max_words:result.append(current);current=[];words=0
        current.append(beat);words+=n
    if current:result.append(current)
    return result

def synthesize_chunks(draft,out,max_words=450,retry=False,store=None,evaluation=False):
    import os
    if not evaluation and (not draft.get('source_reviewed') or draft.get('issues')):
        raise RuntimeError('Production audio requires a source-reviewed draft with no unresolved issues; evaluation must be explicit')
    out.mkdir(parents=True,exist_ok=True);store=store or JobStore(ROOT/'jobs.sqlite');manifest=[]
    for index,group in enumerate(chunks(draft['beats'],max_words)):
        text='\n\n'.join(b['text'] for b in group);model='gemini-3.8-flash-tts'
        digest=hashlib.sha256((model+'|Charon|'+text).encode()).hexdigest();folder=out/digest;folder.mkdir(exist_ok=True)
        audio=folder/'voice.wav';receipt=folder/'stage.json'
        old=json.loads(receipt.read_text()) if receipt.exists() else None
        # Recover a completed provider result if only the wrapper's final write
        # was interrupted. Never replay the upload to repair local bookkeeping.
        meta_path=audio.with_suffix('.json')
        if old and old.get('status')!='complete' and audio.exists() and meta_path.exists():
            meta=json.loads(meta_path.read_text())
            if meta.get('status')==200 and meta.get('digest')==digest:
                with wave.open(str(audio)) as wav:duration=wav.getnframes()/wav.getframerate()
                if duration<=0:raise ValueError('Recovered TTS audio is empty')
                usage=meta.get('usage') or {}
                if old.get('reservation_id'):store.settle(old['reservation_id'],200,usage.get('total_tokens',usage.get('totalTokenCount')))
                old.update(status='complete',duration=duration,audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),usage=usage,recovered_local_receipt=True)
                dump(receipt,old)
        cached=old and old.get('status')=='complete' and audio.exists() and old.get('audio_sha256')==hashlib.sha256(audio.read_bytes()).hexdigest()
        if not cached:
            if old and (not retry or old.get('attempts',1)>=2):raise RuntimeError('TTS interrupted/failed; explicit bounded retry required')
            ident=uuid.uuid4().hex;reservation=round(len(text.split())*12+len(text)/2)
            if not store.reserve(ident,reservation,int(os.environ.get('MANGA_DAILY_REQUESTS','24')),int(os.environ.get('MANGA_DAILY_TOKEN_RESERVATION','180000'))):raise RuntimeError('Shared local daily budget reached; resume after reset')
            status=dict(status='interrupted_unknown',digest=digest,model=model,voice='Charon',attempts=(old or {}).get('attempts',0)+1,
                started_utc=datetime.now(timezone.utc).isoformat(),reservation_id=ident)
            dump(receipt,status);(folder/'narration.txt').write_text(text,encoding='utf-8')
            try:
                synthesize(text,audio,model)
                with wave.open(str(audio)) as wav:duration=wav.getnframes()/wav.getframerate()
                meta=json.loads(audio.with_suffix('.json').read_text());usage=meta.get('usage') or {}
                store.settle(ident,200,usage.get('total_tokens',usage.get('totalTokenCount')))
                status.update(status='complete',duration=duration,audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),usage=usage)
                dump(receipt,status)
            except Exception as exc:
                # An interrupted or timed-out upload can have consumed allowance.
                store.settle(ident,type(exc).__name__);status.update(status='failed_or_unknown',error_type=type(exc).__name__);dump(receipt,status);raise
        row=json.loads(receipt.read_text());manifest.append(dict(index=index,beat_ids=[b['id'] for b in group],path=str(audio.resolve()),
            duration=row['duration'],digest=digest,voice='Charon',model=model,manual_prose_edits=False))
        dump(out/'audio-manifest.json',dict(chunks=manifest,complete=False,evaluation_only=evaluation))
    dump(out/'audio-manifest.json',dict(chunks=manifest,complete=True,evaluation_only=evaluation));return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--beats',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--max-words',type=int,default=450);p.add_argument('--retry-failed',action='store_true');p.add_argument('--evaluation-only',action='store_true');a=p.parse_args();synthesize_chunks(json.loads(a.beats.read_text(encoding='utf-8')),a.output,a.max_words,a.retry_failed,evaluation=a.evaluation_only)
