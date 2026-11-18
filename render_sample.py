"""Render source-linked narration with real segment audio and bounded page pans.

Google Gemini 3.8 TTS is explicit; no paid or alternate-provider fallback.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import wave
import requests
from storybench import ROOT, credentials, redact
from quota_control import hold_reason, learn_limit

def append_log(event):
    with (ROOT/'usage-ledger.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(event)+'\n')

def synthesize(text,out,model):
    digest=hashlib.sha256((model+'|Charon|'+text).encode()).hexdigest()
    meta=out.with_suffix('.json')
    if out.exists() and meta.exists() and json.loads(meta.read_text())['digest']==digest:
        return
    hold=hold_reason(ROOT/'quota-state.json','gemini',model)
    if hold:raise RuntimeError('TTS quota hold: '+str(hold.get('resume_utc',hold.get('reason'))))
    key=credentials('gemini',0)
    payload={'model':model,'input':[{'type':'user_input','content':[{'type':'text','text':text,
             'annotations':[{'type':'speech_metadata','style':
                'Clear, engaged third-person storytelling. Natural neutral English. Measured pace around 180 words per minute; avoid theatrical exaggeration.'}]}]}],
             'response_format':{'type':'audio'},'generation_config':{'speech_config':[{'voice':'Charon'}]}}
    event_id=uuid.uuid4().hex
    append_log({'event_id':event_id,'phase':'started','utc':datetime.now(timezone.utc).isoformat(),
                'provider':'gemini','model':model,'stage':'tts','characters':len(text)})
    started=time.monotonic()
    r=requests.post('https://generativelanguage.googleapis.com/v1beta/interactions',
                    headers={'x-goog-api-key':key},json=payload,timeout=(90,240))
    if not r.ok:
        body=redact(r.text,key)
        result={'status':r.status_code,'body':body,'headers':dict(r.headers)}
        learn_limit(ROOT/'quota-state.json','gemini',model,result)
        meta.write_text(json.dumps({'digest':digest,'error':body,'status':r.status_code},indent=2))
        append_log({'event_id':event_id,'phase':'finished','provider':'gemini','model':model,
                    'status':r.status_code,'seconds':time.monotonic()-started})
        raise RuntimeError('TTS HTTP '+str(r.status_code)+': '+body[:400])
    data=r.json()
    blocks=[c for step in data.get('steps',[]) if step.get('type')=='model_output'
            for c in step.get('content',[]) if c.get('type')=='audio']
    if not blocks:raise ValueError('No audio in TTS response; response schema needs inspection')
    # The current unary API returns a WAV container, not headerless PCM.
    audio=base64.b64decode(blocks[-1]['data'])
    if audio[:4]!=b'RIFF':raise ValueError('Expected WAV output; do not guess its encoding')
    out.write_bytes(audio)
    usage=data.get('usage',data.get('usage_metadata'))
    meta.write_text(json.dumps({'digest':digest,'model':model,'usage':usage,
                   'seconds':time.monotonic()-started,'status':r.status_code},indent=2))
    append_log({'event_id':event_id,'phase':'finished','provider':'gemini','model':model,
                'status':r.status_code,'usage':usage,'seconds':time.monotonic()-started,'stage':'tts'})

def duration(path):
    with wave.open(str(path),'rb') as w:return w.getnframes()/w.getframerate()

def render(args):
    job=json.loads(Path(args.job).read_text(encoding='utf-8'))
    if not job.get('source_reviewed'):raise ValueError('Sample requires source-reviewed narration')
    out=Path(args.output_dir) if args.output_dir else ROOT/'video-sample'
    out.mkdir(parents=True,exist_ok=True)
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('ffmpeg unavailable')
    segments=[];timeline=[];cursor=0.0
    for i,segment in enumerate(job['segments']):
        wav=out/f'audio-{i:02}.wav'
        print('TTS',i+1,'/',len(job['segments']),flush=True)
        synthesize(segment['text'],wav,segment.get('tts_model',args.tts_model))
        dt=duration(wav)
        clip=out/f'clip-{i:02}.mp4'
        # Pan over reviewed page regions; clamp to image bounds. Crop preserves aspect.
        y0,y1=segment.get('pan_y',[0,0.55])
        pan=f'max(0,min(ih-oh,({y0}+( {y1}-{y0})*t/{dt})*ih))'
        vf=f"scale=1440:-2,crop=1280:720:x=(iw-ow)/2:y='{pan}',setsar=1,format=yuv420p"
        cmd=[ffmpeg,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate','24',
             '-i',segment['source_path'],'-i',str(wav),'-vf',vf,'-t',str(dt),
             '-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','160k',
             '-ar','24000','-ac','1','-movflags','+faststart',str(clip)]
        print('Rendering',segment['page_id'],round(dt,1),'seconds',flush=True)
        subprocess.run(cmd,check=True,capture_output=True)
        segments.append(clip)
        timeline.append({**segment,'start':round(cursor,3),'duration':round(dt,3),'audio':str(wav)})
        cursor+=dt
    concat=out/'concat.txt'
    concat.write_text('\n'.join("file '"+p.name+"'" for p in segments),encoding='utf-8')
    final=out/'chapter-0-recap-sample.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0',
                    '-i',str(concat),'-c','copy','-movflags','+faststart',str(final)],
                   check=True,capture_output=True)
    (out/'timeline.json').write_text(json.dumps({'duration':cursor,'segments':timeline,
              'timing':'Measured duration of independently synthesized segments; no word-level alignment'},indent=2))
    print('Video saved:',final,'seconds:',round(cursor,2),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--job',required=True)
    ap.add_argument('--tts-model',default='gemini-3.8-flash-tts')
    ap.add_argument('--output-dir',help='Separate output folder for revised samples')
    render(ap.parse_args())
