import json, time, urllib.request, urllib.parse

CHAMP = 'aatrox'
LANE = 'top'
EPS = ['rune', 'build-itemset', 'counter']
TIERS = [
    'all', 'gold_plus', 'platinum_plus', 'emerald_plus', 'diamond_plus', 'master_plus', 'challenger_plus',
    'iron', 'bronze', 'silver', 'gold', 'platinum', 'emerald', 'diamond', 'master', 'grandmaster', 'challenger',
    'unranked',
]

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {'ERR': str(e)}

for ep in EPS:
    print('#####', ep)
    for t in TIERS:
        params = urllib.parse.urlencode({'ep': ep, 'v': 1, 'patch': '16.19', 'c': CHAMP, 'tier': t,
                                         'queue': 'ranked', 'region': 'all', 'lane': LANE})
        d = get(f'https://a1.lolalytics.com/mega/?{params}')
        if isinstance(d, dict) and 'summary' in d:
            n = (d.get('header') or {}).get('n')
            print(f'  {t:18s} OK n={n}')
        else:
            print(f'  {t:18s} BAD {d if isinstance(d, dict) and "ERR" in d else d.get("status")}')
        time.sleep(0.25)
