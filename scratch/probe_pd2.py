import json, urllib.request
for champ, cid in [('ahri',103), ('jinx',222)]:
    url=f'https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/{cid}/1.5.0.json'
    req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    d=json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    pd=d['12']['17']['5'][0] if champ=='ahri' else d['12']['17']['3'][0]
    print('==',champ,'len',len(pd))
    for i,b in enumerate(pd):
        print(' ',i, json.dumps(b)[:200])
