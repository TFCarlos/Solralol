import json, re
p = r'd:\Accesos\Desktop\Solralol\scratch\ugg_main.js'
text = open(p, encoding='utf-8', errors='replace').read()
# Find enum definitions containing CHALLENGER
for m in re.finditer(r'CHALLENGER\s*=\s*\d+', text):
    s = max(0, m.start()-700); e = min(len(text), m.end()+700)
    print(text[s:e].replace('\n',' ')[:1500])
    print('='*100)
