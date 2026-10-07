import re
text = open('scratch/ugg_main.js', encoding='utf-8', errors='replace').read()
for pat in ['diamond_2_plus','master_plus','platinum_plus','overall']:
    print('#####', pat, text.count(pat))
    for m in list(re.finditer(re.escape(pat), text))[:6]:
        s=max(0,m.start()-400); print(repr(text[s:m.start()+400])); print('-'*80)
