import json, re, sys

sys.stdout.reconfigure(encoding='utf-8')


def lines(p):
    return open(p, encoding='utf-8').read().splitlines()


svc = lines('app/services/live_recommendation_service.py')
pnl = lines('app/ui/recommendation_panel.py')
tst = lines('scratch/test_live_recommendations.py')

out = []


def P(s=''):
    out.append(s)


for name, ls in (('SERVICE', svc), ('PANEL', pnl), ('TESTS', tst)):
    P(f'--- MAP {name} ({len(ls)} lines) ---')
    for i, l in enumerate(ls):
        if re.match(r'\s*(def |class )', l):
            P(f'{i+1}: {l.rstrip()}')
P('')


def body(ls, tag, pat, maxn=320):
    for i, l in enumerate(ls):
        if re.match(pat, l):
            ind = len(l) - len(l.lstrip())
            P(f'--- BODY {tag} @ {i+1}: {l.strip()} ---')
            j, n = i, 0
            while j < len(ls) and n < maxn:
                cur = ls[j]
                if j > i and cur.strip() and (len(cur) - len(cur.lstrip())) <= ind and (
                        cur.strip().startswith(('def ', 'class ')) or cur.strip().startswith('@')):
                    break
                P(f'{j+1}: {cur.rstrip()}')
                j += 1
                n += 1
            P('')
            return
    P(f'--- BODY {tag}: NOT FOUND ({pat}) ---')
    P('')


body(svc, 'svc.analyze', r'\s*def analyze\b')
body(svc, 'svc._rank', r'\s*def _rank\b')
body(svc, 'svc._threats', r'\s*def _threats\b')
body(svc, 'svc._mark_strength', r'\s*def _mark_strength\b')
for pat in (r'\s*def \w*purchase\w*\b', r'\s*def \w*compatib\w*\b', r'\s*def \w*elixir\w*\b',
            r'\s*def \w*cost\w*\b', r'\s*def \w*candidate\w*\b'):
    body(svc, f'svc[{pat}]', pat, 160)

seen = set()
for i, l in enumerate(pnl):
    m = re.match(r'\s*def (\w+)', l)
    if m and re.search(r'recom|rival|threat|synergy|section|secc|header|card|row|refresh|render|build', m.group(1), re.I):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        body(pnl, f'pnl.{m.group(1)}', rf'\s*def {m.group(1)}\b')

text = '\n'.join(out)
open('scratch/EDIT_CTX.txt', 'w', encoding='utf-8').write(text)
open('scratch/PANEL_FULL.txt', 'w', encoding='utf-8').write(
    '\n'.join(f'{i+1}: {l}' for i, l in enumerate(pnl)))
print(f'WROTE scratch/EDIT_CTX.txt ({len(text)} chars) + scratch/PANEL_FULL.txt')

# stdout compacto: mapas + cuerpos críticos + catálogo
for block in out:
    if block.startswith('--- MAP') or block.startswith('PNL-CAND'):
        print(block)
for block in out:
    tag = block.split(' ')[1] if block.startswith('--- BODY') else ''
    if block.startswith('--- BODY') and tag in ('svc.analyze', 'svc._rank'):
        print(block)

d = json.load(open('data/items.json', encoding='utf-8'))
data = d.get('data', d)
print(f'--- CATALOG type={type(d).__name__} entries={len(data)}')
k0 = next(iter(data))
print('SAMPLE', k0, json.dumps(data[k0], ensure_ascii=False)[:400])
for iid in ('2137', '2138', '2139', '2140'):
    it = data.get(iid)
    if it:
        print('ELX', iid, it.get('name'), 'gold', json.dumps(it.get('gold'), ensure_ascii=False),
              'tags', it.get('tags'), 'from', it.get('from'))
for iid in ('3123', '3033'):
    it = data.get(iid)
    if it:
        print(iid, it.get('name'), 'gold', json.dumps(it.get('gold'), ensure_ascii=False),
              'from', it.get('from'), 'into', it.get('into'))
extra = 0
for iid, it in data.items():
    nm = str(it.get('name', ''))
    if 'lixir' in nm or 'frasco' in nm.lower():
        extra += 1
        if extra <= 8:
            print('ELX-SCAN', iid, nm, json.dumps(it.get('gold'), ensure_ascii=False))
