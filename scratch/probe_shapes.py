import json, urllib.request, time, pathlib
OUT = pathlib.Path(r'd:\Accesos\Desktop\Solralol\scratch')
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}

def get(u):
    try:
        r = urllib.request.Request(u, headers=UA)
        return json.loads(urllib.request.urlopen(r, timeout=20).read().decode())
    except Exception as e:
        return {'ERR': str(e)}

# 1. U.GG available rank keys region 12
u = 'https://stats2.u.gg/lol/1.5/overview/16_19/ranked_solo_5x5/266/1.5.0.json'
d = get(u)
if 'ERR' not in d:
    print('UGG region12 rank keys:', sorted(d.get('12', {}).keys()))
    b = d['12']
    for k in sorted(b.keys(), key=lambda x: int(x)):
        v = b[k]
        role = '4'
        if isinstance(v, dict) and role in v and isinstance(v[role], list):
            g = v[role][0][0] if isinstance(v[role][0], list) else '?'
        else:
            g = '?'
        print(' rank', k, 'topgames', g)

# 2. lolalytics ep=rune shape (emerald_plus)
u = 'https://lolalytics.com/lol/aatrox/build/?patch=16.19&mode=ranked&tier=emerald_plus&lane=top&region=world&ep=rune'
r = get(u)
if 'ERR' not in r:
    rl = r.get('response', r)
    (OUT / 'shape_lola_rune.json').write_text(json.dumps(rl, indent=1, ensure_ascii=False), encoding='utf-8')
    print('lola rune keys:', list(r.keys()))
    summ = r.get('summary', {})
    print(' summary keys:', list(summ.keys()))
    rr = summ.get('runes', {})
    print(' runes keys:', list(rr.keys()) if isinstance(rr, dict) else type(rr))
    if isinstance(rr, dict):
        for kk, vv in rr.items():
            if isinstance(vv, list) and vv:
                print('  ', kk, 'first entry:', json.dumps(vv[0], ensure_ascii=False)[:600])
else:
    print('lola rune ERR', r)

time.sleep(1)
# 3. lolalytics ep=build-itemset
u = 'https://lolalytics.com/lol/aatrox/build/?patch=16.19&mode=ranked&tier=emerald_plus&lane=top&region=world&ep=build-itemset'
r = get(u)
if 'ERR' not in r:
    (OUT / 'shape_lola_items.json').write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding='utf-8')
    print('lola itemset keys:', list(r.keys()))
    iss = r.get('itemSets') or r.get('response', {}).get('itemSets')
    if isinstance(iss, dict):
        for kk, vv in iss.items():
            print('  ', kk, json.dumps(vv[:3] if isinstance(vv, list) else vv, ensure_ascii=False)[:400])
else:
    print('lola itemset ERR', r)

time.sleep(1)
# 4. lolalytics ep=counter
u = 'https://lolalytics.com/lol/aatrox/build/?patch=16.19&mode=ranked&tier=emerald_plus&lane=top&region=world&ep=counter'
r = get(u)
if 'ERR' not in r:
    (OUT / 'shape_lola_counter.json').write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding='utf-8')
    print('lola counter keys:', list(r.keys()))
    c = r.get('counters')
    if isinstance(c, list) and c:
        print('  counter[0]:', json.dumps(c[0], ensure_ascii=False)[:400])
        print('  counter[-1]:', json.dumps(c[-1], ensure_ascii=False)[:400])
    print('  stats:', json.dumps(r.get('stats'), ensure_ascii=False)[:300])
else:
    print('lola counter ERR', r)

# 5. OP.GG gold_plus check
u = 'https://op.gg/api/v1.0/internal/bypass/summoners/kr/Aatrox/statistics?region=kr&tier=GOLD_PLUS'
r = get(u)
if 'ERR' in r:
    print('OPGG GOLD_PLUS ERR', r)
else:
    s = (r.get('data') or {}).get('summary') or {}
    a = s.get('average_stats') or {}
    print('OPGG GOLD_PLUS play/win:', a.get('play'), a.get('win_rate'))
