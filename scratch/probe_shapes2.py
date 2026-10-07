import json, urllib.request, time, pathlib
OUT = pathlib.Path(r'd:\Accesos\Desktop\Solralol\scratch')
UA = {'User-Agent': 'Mozilla/5.0'}

def get(u):
    try:
        r = urllib.request.Request(u, headers=UA)
        return json.loads(urllib.request.urlopen(r, timeout=25).read().decode())
    except Exception as e:
        return {'ERR': str(e)}

# Lolalytics: ep=rune full dump
u = 'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier=emerald_plus&ep=rune'
d = get(u)
if 'ERR' in d:
    print('rune ERR', d)
else:
    (OUT/'shape_lola_rune.json').write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    print('RUNE top keys:', list(d.keys()))
    print('header:', json.dumps(d.get('header'), ensure_ascii=False))
    s = d.get('summary', {})
    print('summary keys:', list(s.keys()))
    r = s.get('runes', {})
    print('runes keys:', list(r.keys()) if isinstance(r, dict) else type(r))
    if isinstance(r, dict):
        for k, v in r.items():
            if isinstance(v, dict):
                print(' ', k, 'subkeys:', list(v.keys()))
                st = v.get('set')
                if isinstance(st, list) and st:
                    print('    set[0]:', json.dumps(st[0], ensure_ascii=False)[:500])
                    print('    set len:', len(st))
            elif isinstance(v, list) and v:
                print(' ', k, 'list len', len(v), 'first:', json.dumps(v[0], ensure_ascii=False)[:500])

time.sleep(0.4)
# ep=build-itemset
u = 'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier=emerald_plus&ep=build-itemset'
d = get(u)
if 'ERR' in d:
    print('itemset ERR', d)
else:
    (OUT/'shape_lola_items.json').write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    print('ITEMSET top keys:', list(d.keys()))
    iss = d.get('itemSets') or {}
    print('itemSets keys:', list(iss.keys()) if isinstance(iss, dict) else type(iss))
    if isinstance(iss, dict):
        for k, v in iss.items():
            if isinstance(v, list):
                print(' ', k, 'len', len(v), 'first3:', json.dumps(v[:3], ensure_ascii=False)[:400])

time.sleep(0.4)
# ep=counter
u = 'https://a1.lolalytics.com/mega/?v=1&c=aatrox&queue=ranked&region=all&lane=top&patch=16.19&tier=emerald_plus&ep=counter'
d = get(u)
if 'ERR' in d:
    print('counter ERR', d)
else:
    (OUT/'shape_lola_counter.json').write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    print('COUNTER top keys:', list(d.keys()))
    c = d.get('counters')
    if isinstance(c, dict):
        print('counters keys:', list(c.keys()))
        for k, v in c.items():
            if isinstance(v, list) and v:
                print(' ', k, 'len', len(v), 'first:', json.dumps(v[0], ensure_ascii=False)[:400])
            else:
                print(' ', k, type(v), str(v)[:200])
    elif isinstance(c, list) and c:
        print('counters len', len(c), 'first:', json.dumps(c[0], ensure_ascii=False)[:400])
    print('stats:', json.dumps(d.get('stats'), ensure_ascii=False)[:400])

time.sleep(0.4)
# OP.GG with GOLD_PLUS on the champions endpoint used in code
u = 'https://lol-api-champion.op.gg/api/global/champions/ranked/aatrox/top?tier=GOLD_PLUS'
d = get(u)
if 'ERR' in d:
    print('OPGG ERR', d)
else:
    a = (d.get('data', {}).get('summary', {}) or {}).get('average_stats') or {}
    print('OPGG GOLD_PLUS play/win:', a.get('play'), a.get('win_rate'))
    print('OPGG top keys:', list(d.get('data', {}).keys()))
    print('rune_pages[0]:', json.dumps((d['data'].get('rune_pages') or [None])[0], ensure_ascii=False)[:400])
    print('core_items[0]:', json.dumps((d['data'].get('core_items') or [None])[0], ensure_ascii=False)[:300])
