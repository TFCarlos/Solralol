import io
import re
import sys

OUT = open('scratch/ctx2.txt', 'w', encoding='utf-8')


def w(*a):
    print(*a, file=OUT)


def head(lines, n, tag):
    w('#' * 20, tag, f'(first {n})')
    for i in range(min(n, len(lines))):
        w(f'{i + 1}: {lines[i]}')


def method_map(path, tag):
    lines = open(path, encoding='utf-8').read().splitlines()
    w('#' * 20, tag, f'({len(lines)} lines)')
    for i, l in enumerate(lines, 1):
        if re.match(r'\s*(def |class )', l):
            w(f'{i}: {l}')
    return lines


def find(lines, pat, ctx=35, cap=160):
    seen = []
    for i, l in enumerate(lines):
        if re.search(pat, l):
            a, b = max(0, i - ctx), min(len(lines), i + ctx)
            if any(a <= s <= b or s <= a <= e for s, e in seen):
                continue
            seen.append((a, b))
            w(f'--- match {pat!r} near {i + 1} (lines {a + 1}-{b})')
            for k in range(a, b):
                w(f'{k + 1}: {lines[k]}')
            if len(seen) * (b - a) > cap * 2:
                w('--- (more matches suppressed)')


svc = method_map('app/services/live_recommendation_service.py', 'SERVICE MAP')
pan = method_map('app/ui/recommendation_panel.py', 'PANEL MAP')
tes = method_map('scratch/test_live_recommendations.py', 'TEST MAP')

head(svc, 60, 'SERVICE HEAD')
head(pan, 70, 'PANEL HEAD')
head(tes, 150, 'TEST HEAD')

w('#' * 20, 'SERVICE CONTEXT')
find(svc, r'def analyze', 80)
find(svc, r'def _rank\b', 110)
find(svc, r'def _rank_items', 80)
find(svc, r'def purchase', 60)
find(svc, r'def compatible', 40)
find(svc, r'def _threats', 70)
find(svc, r'inventario|inventory', 30)
find(svc, r'elixir|2138|2139|2140', 25)
find(svc, r'reasons|responses', 25)
find(svc, r'recommendations', 40)

w('#' * 20, 'PANEL CONTEXT')
find(pan, r'3 objetos', 55)
find(pan, r'oro pendiente', 45)
find(pan, r'def _ordered_threats', 30)
find(pan, r'Fuerte|FUERTE', 30)
find(pan, r'pts', 25)
find(pan, r'setToolTip', 20)
find(pan, r'def update|def refresh|def _sync|def set_report|def set_data', 70)

w('#' * 20, 'TEST HEAD REST')
head(tes[150:], 0, 'noop') if False else None
for i in range(150, min(340, len(tes))):
    w(f'{i + 1}: {tes[i]}')
OUT.close()
print('written scratch/ctx2.txt')
