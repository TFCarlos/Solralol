import json, urllib.request, time
# 1) pd entry structure (U.GG)
url='https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/86/1.5.0.json'
req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
d=json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
print('top keys:', sorted(d.keys(), key=int))
print('rank keys @12:', sorted((d['12'] or {}).keys(), key=int))
b=d['12']['8']  # overall
print('pos keys:', sorted(b.keys(), key=int) if isinstance(b,dict) else type(b))
pd=b['4'][0]
print('pd len', len(pd), 'first 4 entries:')
for e in pd[:4]: print('  ', e)
# 2) lolalytics: comprobar si 4043 depende de ep/patch/region
for ep in ['rune','build-itemset','counter']:
  for tier in ['bronze_plus','silver_plus','iron_plus','gold_plus','challenger_plus']:
    url=f'https://a1.lolalytics.com/mega/?v=1&c=ahri&queue=ranked&region=all&lane=middle&patch=16.19&tier={tier}&ep={ep}'
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        raw=urllib.request.urlopen(req, timeout=20).read().decode()
        j=json.loads(raw)
        print(ep, tier, 'OK' if 'summary' in j else j)
    except Exception as e: print(ep, tier, 'ERR', e)
    time.sleep(0.25)
