import json, urllib.request
for tier in ['emerald_plus','bronze','challenger']:
  url=f'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier={tier}&ep=rune'
  req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
  j=json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
  s=j.get('summary',{}).get('runes',{})
  print('==',tier, 'pick:', json.dumps(s.get('pick'))[:400])
  print('   win:', json.dumps(s.get('win'))[:300])
