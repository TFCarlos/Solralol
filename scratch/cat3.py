import json
d = json.load(open('data/items.json', encoding='utf-8'))
its = d['items'] if isinstance(d, dict) and 'items' in d else d
print('ROOT_KEYS', list(d.keys())[:6] if isinstance(d, dict) else type(d).__name__)
for k in ['2138','2139','2140','2003','2031','3123','3033','6609','3340','3006','1036']:
    it = its.get(k) if isinstance(its, dict) else None
    if not it:
        print(k, 'MISSING'); continue
    print(k, '|', it.get('name'), '| gold:', it.get('gold'), '| into:', it.get('into'), '| from:', it.get('from'), '| tags:', it.get('tags'))
print('--- Potion/Consumable/Trinket tags ---')
n = 0
for k, it in sorted(its.items()):
    tags = it.get('tags') or []
    if any(t in tags for t in ('Potion', 'Consumable', 'Trinket')):
        print(k, it.get('name'), tags, (it.get('gold') or {}).get('total'))
        n += 1
        if n > 25: break
