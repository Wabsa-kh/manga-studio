"""Conservative provider/model quota holds; keys never imply additional capacity."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

def state_key(provider,model):return provider+'|'+model

def read_state(path):
    if not Path(path).exists():return {}
    return json.loads(Path(path).read_text(encoding='utf-8'))

def hold_reason(path,provider,model,now=None):
    now=time.time() if now is None else now
    state=read_state(path).get(state_key(provider,model),{})
    if state.get('retryable') is False:return state
    if state.get('blocked_until_epoch',0)>now:return state
    return None

def learn_limit(path,provider,model,result,now=None):
    now=time.time() if now is None else now
    state=read_state(path)
    entry=state.get(state_key(provider,model),{})
    entry.update(last_status=result.get('status'),observed_utc=datetime.fromtimestamp(now,timezone.utc).isoformat())
    headers={k.lower():v for k,v in (result.get('headers') or {}).items()}
    entry['headers']=headers
    if result.get('status')==200:
        # An explicit eligibility probe may establish recovery after owner action.
        # Remove the stale hold only after an actually successful response.
        for field in ['retryable','reason','blocked_until_epoch','resume_utc','quota_violations']:
            entry.pop(field,None)
    if result.get('status')==429:
        try:error=json.loads(result.get('body','{}')).get('error',{})
        except (ValueError,AttributeError):error={}
        metadata=error.get('metadata',{})
        if metadata.get('retryable') is False:
            entry.update(retryable=False,reason=metadata.get('reason',error.get('code')))
        delay=None
        for detail in error.get('details',[]):
            if detail.get('@type','').endswith('RetryInfo'):
                try:delay=float(detail['retryDelay'].rstrip('s'))
                except (ValueError,KeyError):pass
            if detail.get('@type','').endswith('QuotaFailure'):
                entry['quota_violations']=detail.get('violations',[])
        if delay is None and headers.get('retry-after'):
            try:delay=float(headers['retry-after'])
            except ValueError:pass
        if delay is None:
            match=re.search(r'retry in\s+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?',error.get('message',''),re.I)
            if match and any(match.groups()):
                h,m,s=(int(x or 0) for x in match.groups())
                delay=h*3600+m*60+s
        if delay is not None:
            entry.update(blocked_until_epoch=now+delay+1,retryable=True,
                         resume_utc=datetime.fromtimestamp(now+delay+1,timezone.utc).isoformat())
        elif not entry.get('retryable') is False:
            entry.update(reason='429 without a reset time; inspect before retry',retryable=False)
    state[state_key(provider,model)]=entry
    Path(path).write_text(json.dumps(state,indent=2),encoding='utf-8')
    return entry
