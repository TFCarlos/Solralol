import json, urllib.request, time
for ep in ['build','counter','build-itemset','rune']:
    for t in ['iron','bronze_plus','all','gold_plus','challenger']:
        url=f'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier={t}&ep={ep}'
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            j=json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
            ok='summary' in j
            print(ep,t,'OK' if ok else j)
        except Exception as e: print(ep,t,'ERR',e)
        time.sleep(0.15)
