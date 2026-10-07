import json, urllib.request
url='https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier=emerald_plus&ep=rune'
req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
j=json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
print('top keys:', list(j.keys()))
s=j.get('summary', {})
print('summary keys:', list(s.keys()))
r=s.get('runes', {})
print('runes keys:', list(r.keys()) if isinstance(r,dict) else type(r))
pick=r.get('pick', {})
print('pick keys:', list(pick.keys()) if isinstance(pick,dict) else type(pick))
sets=pick.get('set')
print('set type:', type(sets), 'len:', len(sets) if isinstance(sets,list) else None)
if isinstance(sets, list):
    print('first 3 sets:')
    for e in sets[:3]: print(' ', json.dumps(e)[:400])
print('header:', json.dumps(j.get('header'))[:300])
print('setId sample?', json.dumps(s.get('set'))[:200] if 'set' in s else 'n/a')
