import json, urllib.request, time
base='https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top'
for q in ['', '?tier=all', '?tier=EMERALD_PLUS', '?tier=EMERALD', '?tier=GOLD_PLUS', '?tier=CHALLENGER', '?tier=MASTER_PLUS', '?tier=IRON', '?tier=PLATINUM_PLUS', '?tier=GRANDMASTER', '?tier=DIAMOND_PLUS']:
    try:
        req=urllib.request.Request(base+q, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        raw=urllib.request.urlopen(req, timeout=15).read().decode()
        j=json.loads(raw)
        d=j.get('data') or {}
        print(repr(q), 'keys=', list(j.keys()), 'status=', j.get('status'), 'datakeys=', list(d.keys())[:8] if isinstance(d,dict) else type(d))
    except Exception as e:
        print(repr(q), 'ERR', e)
    time.sleep(0.2)
