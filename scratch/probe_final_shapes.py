import json, time, urllib.request, urllib.parse

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def get_html(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read().decode('utf-8', 'replace')

# --- 1. U.GG exact pd structure ---
d = get('https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/103/1.5.0.json')  # Ahri, mid='5'
pd = d['12']['17']['5'][0]
print('pd type/len:', type(pd).__name__, len(pd))
for i, el in enumerate(pd):
    print(f'  pd[{i}] type={type(el).__name__} len={len(el) if hasattr(el, "__len__") else "-"} = {str(el)[:220]}')
print('top-level per position: d["12"]["17"]["5"] len =', len(d['12']['17']['5']))
print()

# --- 2. Lolalytics itemSets keys + counter stats ---
params = urllib.parse.urlencode({'ep': 'build-itemset', 'v': 1, 'patch': '16.19', 'c': 'aatrox', 'tier': 'gold', 'queue': 'ranked', 'region': 'all', 'lane': 'top'})
b = get(f'https://a1.lolalytics.com/mega/?{params}')
print('itemSets keys:', list(b.get('itemSets', {}).keys()))
for k, v in b.get('itemSets', {}).items():
    print(f'  {k}: n={len(v)} first={v[:2]}')
time.sleep(0.3)
params = urllib.parse.urlencode({'ep': 'counter', 'v': 1, 'patch': '16.19', 'c': 'aatrox', 'tier': 'gold', 'queue': 'ranked', 'region': 'all', 'lane': 'top'})
c = get(f'https://a1.lolalytics.com/mega/?{params}')
print('counter top keys:', list(c.keys()))
print('stats:', json.dumps(c.get('stats', {}))[:400])
print('counters[0:3]:', json.dumps(c.get('counters', [])[:3])[:600])
print('counters sorted by vsWr?', [e.get('vsWr') for e in c.get('counters', [])[:8]])

# --- 3. Lolalytics HTML tier param honored? ---
try:
    s1, h1 = get_html('https://lolalytics.com/lol/ahri/build/?lane=middle&tier=gold_plus')
    s2, h2 = get_html('https://lolalytics.com/lol/ahri/build/?lane=middle&tier=challenger')
    import re
    def wr_sample(h):
        m = re.findall(r'"winRate"[^0-9]*([0-9.]+)', h)
        return m[:3], len(h)
    print('html gold_plus:', s1, wr_sample(h1))
    print('html challenger:', s2, wr_sample(h2))
    print('same content:', h1 == h2, 'len1', len(h1), 'len2', len(h2))
except Exception as e:
    print('html tier probe error:', e)
