"""Vuelca a fichero la info del catalogo de objetos necesaria para el plan."""
import json

root = json.load(open('data/items.json', encoding='utf-8'))
data = root.get('data', root)
out = []
for iid in ('2138', '2139', '2140', '2137', '3033', '3123', '3036'):
    it = data.get(iid)
    if isinstance(it, dict):
        out.append(f"{iid}: name={it.get('name')} gold={it.get('gold')} into={it.get('into')} from={it.get('from')} tags={it.get('tags')}")
    else:
        out.append(f"{iid}: MISSING")
els = [(k, v.get('name'), (v.get('gold') or {}).get('total'), v.get('into')) for k, v in data.items()
       if isinstance(v, dict) and 'Consumable' in (v.get('tags') or []) and 'Elixir' in str(v.get('name', ''))]
out.append('ELIXIRS: ' + repr(els))
open('scratch/cat_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('OK')
