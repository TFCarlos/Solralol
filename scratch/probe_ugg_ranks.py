import json, urllib.request
# U.GG overview: mapear indices de rango (segundo indice) y posicion
ids = {'Garen':86, 'Jinx':222, 'LeeSin':64, 'Ahri':103}
for name, cid in ids.items():
    url=f'https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/{cid}/1.5.0.json'
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            d=json.loads(r.read().decode())
    except Exception as e:
        print(name,'ERR',e); continue
    region = d.get('12') or d.get(12)
    print('==', name, 'regions keys:', list(d.keys())[:20] if isinstance(d,dict) else type(d))
    if not isinstance(region, dict): continue
    for rank in sorted(region, key=lambda x: int(x)):
        bucket = region[rank]
        # bucket: posicion -> [ pd, winrate?, ...]
        entry = {}
        for pos, val in (bucket.items() if isinstance(bucket, dict) else enumerate(bucket)):
            try:
                slot = val[0] if isinstance(val, list) else None
                n = slot[1] if isinstance(slot, list) and len(slot)>1 else None
                entry[pos]=n
            except Exception:
                pass
        print('  rank', rank, entry)
