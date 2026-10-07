import json, urllib.request, time
base='https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top'
for t in ['','FOOBAR','all','ALL','IRON','IRON_PLUS','BRONZE','BRONZE_PLUS','SILVER','SILVER_PLUS','GOLD','GOLD_PLUS','PLATINUM','PLATINUM_PLUS','EMERALD','EMERALD_PLUS','DIAMOND','DIAMOND_PLUS','MASTER','MASTER_PLUS','GRANDMASTER','GRANDMASTER_PLUS','CHALLENGER','CHALLENGER_PLUS']:
    q=('?tier='+t) if t else ''
    try:
        req=urllib.request.Request(base+q, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        j=json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        d=j.get('data') or {}
        s=d.get('summary') or {}
        print(t or '(none)', 'sum=', {k:s.get(k) for k in list(s)[:6]})
    except Exception as e: print(t,'ERR',e)
    time.sleep(0.15)
