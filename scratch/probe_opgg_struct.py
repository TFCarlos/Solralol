import json, urllib.request
req=urllib.request.Request('https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top?tier=EMERALD', headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
j=json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
d=j['data']
for k in ['summary','rune_pages','starter_items','summoner_spells','core_items']:
    print('##',k, json.dumps(d.get(k))[:700])
