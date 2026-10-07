import json, urllib.request, time
cands=['bronze_2','bronze_1','bronze_4','iron_2','silver_2','gold_2','gold_4','platinum_4','emerald_4','bronze_plus','iron_plus','silver_plus','challenger_plus','gold_plus','all','unranked']
for t in cands:
    url=f'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier={t}&ep=rune'
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        j=json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        n=(j.get('header') or {}).get('n') if isinstance(j,dict) else None
        print(t, 'OK n='+str(n) if 'summary' in j else j)
    except Exception as e: print(t,'ERR',e)
    time.sleep(0.2)
