import json, urllib.request
url='https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/86/1.5.0.json'
req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
d=json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
pd=d['12']['8']['4'][0]
print('len', len(pd))
for i, block in enumerate(pd):
    s=json.dumps(block)
    print(i, s[:300])
