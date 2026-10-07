import json, time, urllib.request, urllib.parse

def get(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'ERR': str(e)}

TIERS = ['all','iron','bronze','silver','gold','gold_plus','platinum','platinum_plus','emerald','emerald_plus',
         'diamond','diamond_plus','master','master_plus','grandmaster','challenger']
EXPECT = {'rune': 'summary', 'build-itemset': 'itemSets', 'counter': 'counters'}
for ep, key in EXPECT.items():
    print('####', ep)
    for t in TIERS:
        params = urllib.parse.urlencode({'ep': ep, 'v': 1, 'patch': '16.19', 'c': 'aatrox', 'tier': t,
                                         'queue': 'ranked', 'region': 'all', 'lane': 'top'})
        d = get(f'https://a1.lolalytics.com/mega/?{params}')
        ok = isinstance(d, dict) and key in d
        n = (d.get('header') or {}).get('n') if isinstance(d, dict) else None
        print(f'  {t:16s} {"OK" if ok else "BAD"} {n if n is not None else (d.get("status") if isinstance(d, dict) else d)}')
        time.sleep(0.15)

print('#### OP.GG')
for t in ['ALL','IRON','BRONZE','SILVER','GOLD','GOLD_PLUS','PLATINUM','PLATINUM_PLUS','EMERALD','EMERALD_PLUS',
          'DIAMOND','DIAMOND_PLUS','MASTER','MASTER_PLUS','GRANDMASTER','CHALLENGER']:
    d = get(f'https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top?tier={t}')
    ok = isinstance(d, dict) and d.get('data') and (d['data'].get('summary') or {}).get('average_stats')
    play = ((d.get('data') or {}).get('summary') or {}).get('average_stats', {}).get('play') if ok else None
    print(f'  {t:16s} {"OK" if ok else "BAD"} play={play}')
    time.sleep(0.12)
