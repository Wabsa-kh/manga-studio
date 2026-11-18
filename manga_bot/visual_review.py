"""Inspect every page and transition, and hand off a cuttable Shotcut timeline."""
import argparse,json,math,shutil,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from .core import read,save,sha,digest
from .render_v11 import Frames
from .media import ff

def editable(target,data,audio,frames=None):
 cfg=data['config'];fps=cfg['fps'];frames=frames if frames is not None else read(target/'complete.json')['frames']
 if Path(audio).resolve()!=(target/'narration.wav').resolve():shutil.copy2(audio,target/'narration.wav')
 root=ET.Element('mlt',LC_NUMERIC='C',producer='tractor',title='Manga visual review')
 ET.SubElement(root,'profile',width=str(cfg['width']),height=str(cfg['height']),progressive='1',sample_aspect_num='1',sample_aspect_den='1',display_aspect_num='16',display_aspect_den='9',frame_rate_num=str(fps),frame_rate_den='1',colorspace='709')
 for ident,resource,service in [('white','white','color'),('picture','video.mp4','avformat'),('voice','narration.wav','avformat')]:
  p=ET.SubElement(root,'producer',id=ident);ET.SubElement(p,'property',name='mlt_service').text=service;ET.SubElement(p,'property',name='resource').text=resource
  if ident=='picture':ET.SubElement(p,'property',name='audio_index').text='-1'
  if ident=='voice':ET.SubElement(p,'property',name='video_index').text='-1'
 bg=ET.SubElement(root,'playlist',id='background');ET.SubElement(bg,'entry',producer='white',**{'in':'0','out':str(frames-1)})
 v=ET.SubElement(root,'playlist',id='V1');ET.SubElement(v,'property',name='shotcut:name').text='Source-linked page shots';markers=[]
 for i,s in enumerate(data['shots']):
  start=round(s['start']*fps);end=round(data['shots'][i+1]['start']*fps) if i+1<len(data['shots']) else frames;ET.SubElement(v,'entry',producer='picture',**{'in':str(start),'out':str(end-1)});markers.append(dict(start=start,end=start,text=s['page_id']))
 a=ET.SubElement(root,'playlist',id='A1');ET.SubElement(a,'property',name='shotcut:name').text='Narration';ET.SubElement(a,'entry',producer='voice',**{'in':'0','out':str(frames-1)})
 tractor=ET.SubElement(root,'tractor',id='tractor',shotcut='1',**{'in':'0','out':str(frames-1)});ET.SubElement(tractor,'property',name='shotcut').text='1';ET.SubElement(tractor,'track',producer='background');ET.SubElement(tractor,'track',producer='V1',hide='audio');ET.SubElement(tractor,'track',producer='A1',hide='video')
 for service,btrack in [('frei0r.cairoblend',1),('mix',2)]:
  transition=ET.SubElement(tractor,'transition',**{'in':'0','out':str(frames-1)})
  for k,val in dict(mlt_service=service,a_track=0,b_track=btrack,always_active=1).items():ET.SubElement(transition,'property',name=k).text=str(val)
 properties=ET.SubElement(tractor,'properties',name='shotcut:markers')
 for i,m in enumerate(markers):
  p=ET.SubElement(properties,'properties',name=str(i))
  for k,val in m.items():ET.SubElement(p,'property',name=k).text=str(val)
 ET.indent(root);ET.ElementTree(root).write(target/'editable.mlt',encoding='utf-8',xml_declaration=True);save(target/'markers.json',markers)

def inspect(target):
 target=Path(target);data=read(target/'camera-plan.json');cfg=data['config'];fps=cfg['fps'];folder=target/'qa';folder.mkdir(exist_ok=True);frames=read(target/'complete.json')['frames'];requests=[]
 for s in data['shots']:
  for label,t in [('entry',s['start']+.06),('mid',(s['start']+s['end'])/2),('exit',s['end']-.04)]:requests.append(dict(page_id=s['page_id'],label=label,time=max(s['start'],min(s['end']-.01,t))))
 numbers=sorted(set(min(frames-1,max(0,round(r['time']*fps))) for r in requests))
 def combine(parts):
  if len(parts)==1:return parts[0]
  mid=len(parts)//2;return '('+combine(parts[:mid])+'+'+combine(parts[mid:])+')'
 select=combine([f'eq(n,{n})' for n in numbers]);ff(['-threads','4','-i',target/'video.mp4','-vf',"select='"+select+"'",'-fps_mode','vfr','-q:v','2','-frames:v',len(numbers),folder/'%03d.jpg']);paths={n:folder/f'{i+1:03}.jpg' for i,n in enumerate(numbers)};renderer=Frames(data);metrics=[]
 for r in requests:
  n=min(frames-1,max(0,round(r['time']*fps)));r['frame']=n;r['path']=str(paths[n]);actual=np.asarray(Image.open(paths[n]).convert('RGB'));spread=float(actual.std());flat=spread<1.5;error=None
  if r['label']=='mid':
   expected=renderer.frame(n/fps);error=float(np.abs(actual.astype(np.float32)-expected.astype(np.float32)).mean())
  metrics.append(dict(page_id=r['page_id'],label=r['label'],flat=flat,mean_absolute_render_difference=error))
 for label in ['entry','mid','exit']:
  rows=[r for r in requests if r['label']==label];sheet=Image.new('RGB',(1280,205*math.ceil(len(rows)/4)),(24,24,24));draw=ImageDraw.Draw(sheet)
  for i,r in enumerate(rows):
   with Image.open(r['path']) as im:sheet.paste(im.resize((320,180)),(i%4*320,i//4*205+25))
   draw.text((i%4*320+5,i//4*205+6),f"{r['time']:.1f}s {r['page_id']}",fill='white')
  sheet.save(target/f'contact-{label}.jpg',quality=88)
 report=dict(video_sha256=sha(target/'video.mp4'),plan_sha256=digest(data),samples=len(requests),page_shots=len(data['shots']),flat_samples=sum(r['flat'] for r in metrics),max_midframe_render_difference=max(r['mean_absolute_render_difference'] or 0 for r in metrics),metrics=metrics);save(target/'qa-manifest.json',report);save(target/'qa-samples.json',requests);return report

def comparison(target,old,seconds=60):
 target=Path(target);bg=Image.new('RGBA',(1280,720),'white');d=ImageDraw.Draw(bg)
 try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24)
 except OSError:font=ImageFont.load_default(size=24)
 d.text((320,135),'PREVIOUS',font=font,fill='black',anchor='mm');d.text((960,135),'NEW CAMERA',font=font,fill='black',anchor='mm');d.text((640,590),'Same narration and source pages',font=font,fill=(65,65,65),anchor='mm');bg.save(target/'comparison-labels.png')
 graph='[0:v]scale=640:360,setsar=1,fps=30[l];[1:v]scale=640:360,setsar=1,fps=30[r];[2:v][l]overlay=0:180[a];[a][r]overlay=640:180[out]';(target/'comparison.filter').write_text(graph,encoding='utf-8');ff(['-i',old,'-i',target/'video.mp4','-loop','1','-i',target/'comparison-labels.png','-/filter_complex',target/'comparison.filter','-map','[out]','-map','1:a','-t',seconds,'-c:v','libx264','-preset','veryfast','-crf','20','-threads','4','-c:a','aac','-b:a','160k','-movflags','+faststart',target/'comparison-60s.mp4'])

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--target',required=True);p.add_argument('--audio',required=True);p.add_argument('--old',required=True);a=p.parse_args();target=Path(a.target);data=read(target/'camera-plan.json');editable(target,data,a.audio);r=inspect(target);print({k:v for k,v in r.items() if k!='metrics'},flush=True);comparison(target,a.old)
